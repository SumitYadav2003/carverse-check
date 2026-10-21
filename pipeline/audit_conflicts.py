"""
Second audit: look inside the conflicting tests, and check our numbers against DVSA's.

Usage (project folder, venv active):
    python pipeline/audit_conflicts.py

Writes data/warehouse/audit_conflicts.txt. Read-only.
"""

import sys
import time
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("DuckDB is missing. Run:  pip install duckdb")

WAREHOUSE = Path("data/warehouse/mot.duckdb")
REPORT = Path("data/warehouse/audit_conflicts.txt")

RESULT_COLS = ["vehicle_id", "test_date", "test_class_id", "test_type", "test_result",
               "test_mileage", "postcode_area", "make", "model", "colour", "fuel_type",
               "cylinder_capacity", "first_use_date", "completed_date"]

# Every distinct version of a test, header lines removed. A test with more than one version
# here has copies that disagree with each other.
VERSIONS = ("(SELECT DISTINCT * EXCLUDE (source_file, loaded_at) FROM raw.test_result "
            "WHERE test_id <> 'test_id')")


def per_column_sql():
    parts = ", ".join(f"count(*) FILTER (WHERE n_{c} > 1) AS {c}" for c in RESULT_COLS)
    inner = ", ".join(f"count(DISTINCT coalesce({c}, '<null>')) AS n_{c}" for c in RESULT_COLS)
    return (f"WITH v AS (SELECT test_id, {inner} FROM {VERSIONS} GROUP BY test_id "
            f"HAVING count(*) > 1) SELECT count(*) AS conflicting_tests, {parts} FROM v")


CHECKS = [
    ("Conflicting tests: in how many does each column differ between versions?",
     per_column_sql()),

    ("How many versions do conflicting tests have?",
     f"SELECT versions, count(*) AS tests FROM (SELECT test_id, count(*) AS versions "
     f"FROM {VERSIONS} GROUP BY test_id HAVING count(*) > 1) GROUP BY 1 ORDER BY 1"),

    ("Five conflicting tests, every version side by side",
     f"""WITH c AS (SELECT test_id FROM {VERSIONS} GROUP BY test_id HAVING count(*) > 1
                     ORDER BY hash(test_id) LIMIT 5)
         SELECT v.* FROM {VERSIONS} v JOIN c USING (test_id) ORDER BY test_id, completed_date"""),

    ("Exact duplicate item rows on tests whose result row is NOT duplicated: five examples",
     """WITH single AS (SELECT test_id FROM raw.test_result WHERE test_id <> 'test_id'
                        GROUP BY test_id HAVING count(*) = 1),
             dup_items AS (SELECT test_id, rfr_id, rfr_type_code, mot_test_rfr_location_type_id,
                                  dangerous_mark, completed_date, count(*) AS copies
                           FROM raw.test_item WHERE test_id <> 'test_id'
                           GROUP BY ALL HAVING count(*) > 1)
         SELECT d.* FROM dup_items d JOIN single USING (test_id)
         ORDER BY hash(d.test_id) LIMIT 5"""),

    ("Check against DVSA's published figures: April-December 2024, classes 3 and 4, "
     "normal tests with result P, F or PRS",
     f"""WITH t AS (
             SELECT test_id,
                    bool_or(test_result IN ('F', 'PRS')) AS initial_fail,
                    bool_or(test_result = 'F') AS final_fail,
                    count(DISTINCT test_result) AS results_seen
             FROM {VERSIONS}
             WHERE test_class_id IN ('3', '4') AND test_type = 'NT'
               AND test_result IN ('P', 'F', 'PRS')
               AND test_date BETWEEN '2024-04-01' AND '2024-12-31'
             GROUP BY test_id)
         SELECT count(*) AS tests,
                round(100.0 * count(*) FILTER (WHERE initial_fail) / count(*), 2) AS initial_fail_pct,
                round(100.0 * count(*) FILTER (WHERE final_fail) / count(*), 2) AS final_fail_pct,
                count(*) FILTER (WHERE results_seen > 1) AS tests_with_disagreeing_results,
                24157139 AS dvsa_tests, 28.17 AS dvsa_initial_fail_pct, 22.72 AS dvsa_final_fail_pct
         FROM t"""),
]


def main():
    if not WAREHOUSE.exists():
        sys.exit(f"{WAREHOUSE} not found. Run pipeline/ingest.py first.")
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    con.execute(f"SET temp_directory = '{(WAREHOUSE.parent / 'duckdb_tmp').as_posix()}'")
    lines = [f"Conflict audit of {WAREHOUSE}"]
    for title, sql in CHECKS:
        started = time.time()
        print(f"Running: {title} ...")
        try:
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except Exception as exc:
            lines += ["", f"## {title}", f"ERROR: {exc}"]
            continue
        lines += ["", f"## {title}  ({time.time() - started:.0f}s)", " | ".join(cols)]
        for row in rows:
            lines.append(" | ".join(f"{v:,}" if isinstance(v, int) and not isinstance(v, bool)
                                    else str(v) for v in row))
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved {REPORT}. Upload that file here.")


if __name__ == "__main__":
    main()