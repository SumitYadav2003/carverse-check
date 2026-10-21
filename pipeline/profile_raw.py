"""
Profile the raw DVSA anonymised MOT files before designing anything.

Usage (from the project folder, venv active):
    python pipeline/profile_raw.py data/raw/2024

What it does:
  1. Unzips every .zip in that folder into data/raw/<year>/extracted/ (skips ones already extracted).
     The original ZIPs are never changed.
  2. For every extracted data file, uses DuckDB to report: row count, column names,
     3 sample rows, and for each column how many values are blank and roughly how many distinct.
  3. Writes everything to data/raw/<year>/profile.txt so you can paste it back.

Everything is read as text on purpose: this step describes the data as it really is,
before we decide types. Choosing types comes next, in the staging models.
"""

import sys
import time
import zipfile
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("DuckDB is missing. Run:  pip install duckdb")

DATA_SUFFIXES = {".csv", ".txt", ".psv", ""}


def extract_all(folder: Path) -> Path:
    out = folder / "extracted"
    out.mkdir(exist_ok=True)
    for zpath in sorted(folder.glob("*.zip")):
        marker = out / f".{zpath.name}.done"
        if marker.exists():
            print(f"Already extracted: {zpath.name}")
            continue
        print(f"Extracting {zpath.name} ...")
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(out)
        marker.write_text("ok")
    return out


def data_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in DATA_SUFFIXES:
            yield p


def profile_file(con, path: Path, lines: list):
    src = str(path).replace("\\", "/").replace("'", "''")
    # quote='' because the files don't use quoting; a stray " in a model name must stay text
    reader = (f"read_csv('{src}', delim='|', header=true, all_varchar=true, "
              f"quote='', escape='')")
    head = ["", f"=== {path.name}  ({path.stat().st_size / 1e6:,.1f} MB)"]
    lines.extend(head)
    print("\n".join(head))
    started = time.time()
    try:
        cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()]
        sample = con.execute(f"SELECT * FROM {reader} LIMIT 3").fetchall()
    except Exception as exc:  # show the problem instead of crashing on one bad file
        msg = f"Could not read as pipe-separated with a header: {exc}"
        lines.append(msg)
        print(msg)
        return

    # One pass over the file for every statistic: these files have tens of millions of rows,
    # so scanning once per column would take far too long.
    parts = ["count(*)"]
    for c in cols:
        q = f'"{c}"'
        parts += [f"count(*) FILTER (WHERE {q} IS NULL OR trim({q}) = '')",
                  f"approx_count_distinct({q})", f"min({q})", f"max({q})"]
    print("Scanning the whole file (large files take a few minutes) ...")
    stats = con.execute(f"SELECT {', '.join(parts)} FROM {reader}").fetchone()

    rows = stats[0]
    lines.append(f"rows: {rows:,}")
    lines.append(f"columns ({len(cols)}): {', '.join(cols)}")
    lines.append("sample rows:")
    for row in sample:
        lines.append("  " + " | ".join("" if v is None else str(v) for v in row))
    lines.append("per column: blank values / approx distinct / min / max (as text)")
    for i, c in enumerate(cols):
        blank, distinct, lo, hi = stats[1 + i * 4: 5 + i * 4]
        lines.append(f"  {c}: blank {blank:,} / distinct ~{distinct:,} / min {lo!r} / max {hi!r}")
    lines.append(f"(profiled in {time.time() - started:.0f}s)")
    print(f"rows: {rows:,} - done in {time.time() - started:.0f}s")


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python pipeline/profile_raw.py data/raw/2024")
    folder = Path(sys.argv[1])
    if not folder.is_dir():
        sys.exit(f"Folder not found: {folder}")
    extracted = extract_all(folder)
    con = duckdb.connect()  # in-memory: profiling never writes a database
    lines = [f"Profile of {folder}"]
    files = list(data_files(extracted))
    if not files:
        sys.exit(f"No data files found under {extracted}")
    for f in files:
        profile_file(con, f, lines)
    report = folder / "profile.txt"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved {report}. Upload that file here.")


if __name__ == "__main__":
    main()