"""Print row counts of the main warehouse tables. Usage: python pipeline/row_counts.py"""
import duckdb

con = duckdb.connect("data/warehouse/mot.duckdb", read_only=True)
for table in ["marts.fct_mot_tests", "marts.fct_test_defects",
              "marts.dim_vehicle_model", "marts.dim_defect"]:
    rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    print(f"{table}: {rows:,}")