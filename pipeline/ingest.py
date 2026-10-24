"""
Ingest: load the raw DVSA anonymised MOT files into DuckDB, untouched.

Usage (project folder, venv active):
    python pipeline/ingest.py data/raw/2024

Reads every file in data/raw/<year>/extracted/ (created by profile_raw.py) and loads it into
data/warehouse/mot.duckdb, schema "raw":
    test_result_*.csv  -> raw.test_result
    test_item_*.csv    -> raw.test_item
    anything else      -> raw.<file name>   (the lookup tables)

Rules:
- Every value is stored as text, exactly as it is in the file. Cleaning and typing happen
  later, in dbt staging models, where the rules can be read and tested.
- Each row records which file it came from (source_file).
- raw._load_manifest records every file loaded: name, SHA-256, size, rows, time.
- Safe to re-run: a file whose SHA-256 is already in the manifest is skipped. If DVSA
  republishes a file with the same name but different content, its old rows are deleted
  and the new version loaded, all inside one transaction, so a failure never leaves a
  half-loaded file behind.
"""

import hashlib
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("DuckDB is missing. Run:  pip install duckdb")

# Set MOT_WAREHOUSE to use a different file, e.g. CI builds its own small warehouse
WAREHOUSE = Path(os.environ.get("MOT_WAREHOUSE", "data/warehouse/mot.duckdb"))


def target_table(path: Path) -> str:
    name = path.stem.lower()
    if name.startswith("test_result_"):
        return "test_result"
    if name.startswith("test_item_"):
        return "test_item"
    return re.sub(r"[^a-z0-9_]", "_", name)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def delimiter(path: Path) -> str:
    # The user guide says pipe-separated, but the 2024 monthly files are comma-separated.
    # Decide per file from its header line instead of trusting the guide.
    with path.open("r", encoding="utf-8", errors="replace") as f:
        header = f.readline()
    return "|" if header.count("|") > header.count(",") else ","


def reader_sql(path: Path) -> str:
    src = str(path).replace("\\", "/").replace("'", "''")
    delim = delimiter(path)
    if delim == "|":
        # Lookup tables: no quoting at all, so a stray " stays text. Small files, so any
        # malformed line should stop the load and be looked at.
        options = ", quote='', escape=''"
    else:
        # Monthly files: the rare value containing a comma is quoted ("IVECO ,MOTORHOME", line
        # 2,058,120 of January), and a quote inside a value is escaped with a backslash
        # ("STREETZONE 50 2T 12\""). Both are too rare for DuckDB's auto-detection, which only
        # samples the first ~20,000 lines, so the dialect is set explicitly.
        # store_rejects: a line that still can't be parsed is set aside in a rejects table
        # instead of stopping a 6-million-row load; load_file records and limits them.
        options = ", quote='\"', escape='\\', store_rejects=true"
    return f"read_csv('{src}', delim='{delim}', header=true, all_varchar=true{options})"


# If more than this share of a file's lines can't be parsed, stop: something is wrong with
# the file or with our reading of it, and loading the rest would hide it.
MAX_REJECTED_SHARE = 0.001  # 0.1%


def load_file(con, path: Path, digest: str):
    table = f"raw.{target_table(path)}"
    reader = reader_sql(path)
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute("BEGIN TRANSACTION")
    try:
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'raw' AND table_name = ?", [target_table(path)]
        ).fetchone()[0]
        if not exists:
            con.execute(f"CREATE TABLE {table} AS SELECT *, ''::VARCHAR AS source_file, "
                        f"NULL::TIMESTAMP AS loaded_at FROM {reader} LIMIT 0")
        # a changed file with the same name replaces its earlier rows
        con.execute(f"DELETE FROM {table} WHERE source_file = ?", [path.name])
        con.execute("DELETE FROM raw._load_manifest WHERE file_name = ?", [path.name])
        con.execute("DELETE FROM raw._rejects WHERE source_file = ?", [path.name])
        # DuckDB writes unparseable lines to these temporary tables; start each file empty
        con.execute("DROP TABLE IF EXISTS temp.reject_errors")
        con.execute("DROP TABLE IF EXISTS temp.reject_scans")
        # BY NAME: columns are matched by name, and a new or renamed column fails loudly
        con.execute(f"INSERT INTO {table} BY NAME SELECT *, ? AS source_file, ? AS loaded_at "
                    f"FROM {reader}", [path.name, loaded_at])
        rows = con.execute(f"SELECT count(*) FROM {table} WHERE source_file = ?",
                           [path.name]).fetchone()[0]

        rejected = 0
        has_rejects = con.execute("SELECT count(*) FROM duckdb_tables() "
                                  "WHERE temporary AND table_name = 'reject_errors'").fetchone()[0]
        if has_rejects:
            # one bad line can produce several error rows (one per problem column)
            con.execute("""INSERT INTO raw._rejects
                           SELECT ?, line, any_value(error_type), any_value(csv_line),
                                  any_value(error_message), ?
                           FROM temp.reject_errors GROUP BY line""", [path.name, loaded_at])
            rejected = con.execute("SELECT count(*) FROM raw._rejects WHERE source_file = ?",
                                   [path.name]).fetchone()[0]
        if rows and rejected / (rows + rejected) > MAX_REJECTED_SHARE:
            raise RuntimeError(
                f"{path.name}: {rejected:,} of {rows + rejected:,} lines could not be parsed, "
                f"more than {MAX_REJECTED_SHARE:.1%}. Nothing from this file was loaded.")

        con.execute("INSERT INTO raw._load_manifest VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [path.name, table, digest, path.stat().st_size, rows, loaded_at, rejected])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return table, rows, rejected


class IngestError(Exception):
    """A problem with the input folder, raised instead of exiting so callers can handle it."""


def run(raw_dir, warehouse=None, log=print):
    """Load every new or changed file under <raw_dir>/extracted into the warehouse.

    Returns {"loaded": n, "skipped": n}. Used by the command line (main, below) and by
    the Prefect flow in orchestration/flow.py, which skips the rest of the pipeline when
    nothing was loaded.
    """
    warehouse = Path(warehouse or WAREHOUSE)
    extracted = Path(raw_dir) / "extracted"
    if not extracted.is_dir():
        raise IngestError(f"{extracted} not found. Run profile_raw.py first; it unzips the files.")
    # Skip macOS zip junk: a __MACOSX folder of "._name.csv" metadata files that aren't data.
    files = sorted(p for p in extracted.rglob("*.csv")
                   if p.is_file() and not p.name.startswith(".") and "__MACOSX" not in p.parts)
    if not files:
        raise IngestError(f"No .csv files under {extracted}")

    warehouse.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(warehouse))
    try:
        # big loads: let DuckDB use less memory, and spill to disk instead of failing
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = '{(warehouse.parent / 'duckdb_tmp').as_posix()}'")
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        con.execute("""CREATE TABLE IF NOT EXISTS raw._load_manifest (
            file_name VARCHAR PRIMARY KEY, target_table VARCHAR, sha256 VARCHAR,
            size_bytes BIGINT, row_count BIGINT, loaded_at TIMESTAMP)""")
        # added after the first loads, so older warehouses get the column too
        con.execute("ALTER TABLE raw._load_manifest ADD COLUMN IF NOT EXISTS rejected_rows BIGINT DEFAULT 0")
        con.execute("""CREATE TABLE IF NOT EXISTS raw._rejects (
            source_file VARCHAR, line BIGINT, error_type VARCHAR, csv_line VARCHAR,
            error_message VARCHAR, loaded_at TIMESTAMP)""")

        loaded = skipped = 0
        for path in files:
            digest = sha256(path)
            already = con.execute("SELECT sha256 FROM raw._load_manifest WHERE file_name = ?",
                                  [path.name]).fetchone()
            if already and already[0] == digest:
                log(f"skip   {path.name} (already loaded, unchanged)")
                skipped += 1
                continue
            started = time.time()
            action = "reload" if already else "load  "
            table, rows, rejected = load_file(con, path, digest)
            note = f", {rejected:,} unparseable line(s) set aside in raw._rejects" if rejected else ""
            log(f"{action} {path.name} -> {table}: {rows:,} rows in {time.time() - started:.0f}s{note}")
            loaded += 1

        log(f"\nDone: {loaded} loaded, {skipped} skipped. Warehouse: {warehouse}")
        for t, n, r, rej in con.execute(
                "SELECT target_table, count(*), sum(row_count), sum(coalesce(rejected_rows, 0)) "
                "FROM raw._load_manifest GROUP BY 1 ORDER BY 1").fetchall():
            log(f"  {t}: {n} file(s), {r:,} rows" + (f", {rej:,} rejected" if rej else ""))
    finally:
        con.close()
    return {"loaded": loaded, "skipped": skipped}


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python pipeline/ingest.py data/raw/2024")
    try:
        run(sys.argv[1])
    except IngestError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
