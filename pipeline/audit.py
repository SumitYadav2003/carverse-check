"""
Audit the raw tables: measure the data-quality problems exactly, before we decide how to clean.

Usage (project folder, venv active, after ingest.py):
    python pipeline/audit.py

Writes data/warehouse/audit.txt. Read-only: it never changes the warehouse.
"""

import sys
import time
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("DuckDB is missing. Run:  pip install duckdb")

WAREHOUSE = Path("data/warehouse/mot.duckdb")
REPORT = Path("data/warehouse/audit.txt")

# Rows that are a repeat of the header line are excluded everywhere except where we count them.
R = "(SELECT * EXCLUDE (source_file, loaded_at) FROM raw.test_result WHERE test_id <> 'test_id')"
I = "(SELECT * EXCLUDE (source_file, loaded_at) FROM raw.test_item WHERE test_id <> 'test_id')"

CHECKS = [
    ("Files and rows loaded",
     "SELECT target_table, count(*) AS files, sum(row_count) AS rows FROM raw._load_manifest "
     "GROUP BY 1 ORDER BY 1"),

    ("Header lines repeated inside the data",
     "SELECT 'test_result' AS tbl, count(*) FROM raw.test_result WHERE test_id = 'test_id' "
     "UNION ALL SELECT 'test_item', count(*) FROM raw.test_item WHERE test_id = 'test_id'"),

    ("Results: rows vs exact-distinct rows vs distinct test_id",
     f"SELECT count(*) AS rows, (SELECT count(*) FROM (SELECT DISTINCT * FROM {R})) AS distinct_rows, "
     f"count(DISTINCT test_id) AS distinct_test_ids FROM {R}"),

    ("Results: test_ids that have more than one DIFFERENT version (conflicts, not copies)",
     f"SELECT count(*) AS conflicting_test_ids FROM (SELECT test_id FROM (SELECT DISTINCT * FROM {R}) "
     f"GROUP BY test_id HAVING count(*) > 1)"),

    ("Results: do copies of the same test sit in more than one monthly file?",
     "SELECT count(*) AS test_ids_in_2plus_files FROM (SELECT test_id FROM raw.test_result "
     "WHERE test_id <> 'test_id' GROUP BY test_id HAVING count(DISTINCT source_file) > 1)"),

    ("Items: rows vs exact-distinct rows",
     f"SELECT count(*) AS rows, (SELECT count(*) FROM (SELECT DISTINCT * FROM {I})) AS distinct_rows FROM {I}"),

    ("Items: exact-duplicate item rows, split by whether that test's result row is also duplicated",
     f"""WITH dup_tests AS (SELECT test_id FROM {R} GROUP BY test_id HAVING count(*) > 1),
             item_counts AS (SELECT test_id, rfr_id, rfr_type_code, mot_test_rfr_location_type_id,
                                    dangerous_mark, completed_date, count(*) - 1 AS extra
                             FROM {I} GROUP BY ALL HAVING count(*) > 1)
         SELECT (ic.test_id IN (SELECT test_id FROM dup_tests)) AS result_row_also_duplicated,
                sum(extra) AS extra_item_rows
         FROM item_counts ic GROUP BY 1 ORDER BY 1"""),

    ("Items whose test_id has no result row (orphans)",
     f"SELECT count(*) AS orphan_item_rows FROM {I} i "
     f"WHERE NOT EXISTS (SELECT 1 FROM {R} r WHERE r.test_id = i.test_id)"),

    ("Distinct tests by vehicle class",
     f"SELECT test_class_id, count(DISTINCT test_id) AS tests FROM {R} GROUP BY 1 ORDER BY 2 DESC"),

    ("Distinct class 4 tests by type and result",
     f"SELECT test_type, test_result, count(DISTINCT test_id) AS tests FROM {R} "
     f"WHERE test_class_id = '4' GROUP BY 1, 2 ORDER BY 3 DESC"),

    ("Dates: does each monthly file only hold its own month?",
     "SELECT source_file, min(test_date) AS first, max(test_date) AS last, "
     "count(*) FILTER (WHERE substr(test_date, 1, 7) <> "
     "substr(regexp_extract(source_file, '(\\d{6})', 1), 1, 4) || '-' || "
     "substr(regexp_extract(source_file, '(\\d{6})', 1), 5, 2)) AS rows_outside_month "
     "FROM raw.test_result WHERE test_id <> 'test_id' GROUP BY 1 ORDER BY 1"),

    ("Mileage values (class 4, distinct tests)",
     f"""SELECT CASE WHEN test_mileage IS NULL OR trim(test_mileage) = '' THEN 'blank'
                     WHEN try_cast(test_mileage AS DOUBLE) IS NULL THEN 'not a number'
                     WHEN try_cast(test_mileage AS DOUBLE) = 0 THEN 'zero'
                     WHEN try_cast(test_mileage AS DOUBLE) <> floor(try_cast(test_mileage AS DOUBLE))
                          THEN 'has decimals'
                     WHEN try_cast(test_mileage AS DOUBLE) > 999999 THEN 'over 999,999'
                     ELSE 'whole number' END AS kind,
                count(*) AS tests
         FROM (SELECT DISTINCT test_id, test_mileage FROM {R} WHERE test_class_id = '4')
         GROUP BY 1 ORDER BY 2 DESC"""),

    ("Known DVSA placeholders (class 4, distinct tests)",
     f"""SELECT count(DISTINCT test_id) FILTER (WHERE first_use_date = '1971-01-01') AS first_use_1971,
                count(DISTINCT test_id) FILTER (WHERE upper(make) = 'UNCLASSIFIED') AS make_unclassified,
                count(DISTINCT test_id) FILTER (WHERE postcode_area = 'XX') AS postcode_xx
         FROM {R} WHERE test_class_id = '4'"""),

    ("Items: rfr types, and whether every rfr_id exists in item_detail for class 4",
     f"""SELECT i.rfr_type_code, count(*) AS rows,
                count(*) FILTER (WHERE d.rfr_id IS NULL) AS no_matching_detail
         FROM (SELECT DISTINCT * FROM {I}) i
         JOIN (SELECT DISTINCT test_id FROM {R} WHERE test_class_id = '4') r USING (test_id)
         LEFT JOIN raw.item_detail d ON d.rfr_id = i.rfr_id AND d.test_class_id = '4'
         GROUP BY 1 ORDER BY 2 DESC"""),

    ("Initial failure rate, class 4, normal tests only (DVSA's published method)",
     f"""SELECT count(*) AS normal_tests,
                round(100.0 * count(*) FILTER (WHERE test_result IN ('F', 'PRS')) / count(*), 2)
                    AS initial_fail_pct,
                round(100.0 * count(*) FILTER (WHERE test_result = 'F') / count(*), 2) AS final_fail_pct
         FROM (SELECT DISTINCT test_id, test_result FROM {R}
               WHERE test_class_id = '4' AND test_type = 'NT' AND test_result IN ('P', 'F', 'PRS'))"""),
]


def main():
    if not WAREHOUSE.exists():
        sys.exit(f"{WAREHOUSE} not found. Run pipeline/ingest.py first.")
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    # the DISTINCT checks over ~66M rows need more memory than most laptops have; spill to disk
    con.execute(f"SET temp_directory = '{(WAREHOUSE.parent / 'duckdb_tmp').as_posix()}'")
    lines = [f"Audit of {WAREHOUSE}"]
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
            lines.append(" | ".join(f"{v:,}" if isinstance(v, int) else str(v) for v in row))
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved {REPORT}. Upload that file here.")


if __name__ == "__main__":
    main()
