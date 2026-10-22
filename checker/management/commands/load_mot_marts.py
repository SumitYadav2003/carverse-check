"""
Copy the two dbt marts from the DuckDB warehouse into the website's database.

    python manage.py load_mot_marts
    python manage.py load_mot_marts --warehouse path/to/mot.duckdb

The website only ever reads these small summary tables (tens of thousands of rows). The
warehouse itself (tens of GB) stays on the machine that runs the pipeline.

Safe to re-run: all old rows are replaced inside one transaction, so the site never sees a
half-loaded state, and a failure leaves the previous data in place.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from checker.models import ModelYearDefectCategory, ModelYearFailRate

RATE_COLUMNS = ["model_year_key", "make", "model", "first_use_year", "tests",
                "initial_fail_rate_pct", "final_fail_rate_pct", "median_mileage", "peer_tests",
                "peer_initial_fail_rate_pct", "peer_final_fail_rate_pct",
                "initial_fail_rate_vs_peers_pts"]
CATEGORY_COLUMNS = ["model_year_key", "defect_category", "tests_with_failure_item",
                    "tests_with_advisory", "failure_share_pct", "advisory_share_pct",
                    "peer_failure_share_pct", "peer_advisory_share_pct"]


class Command(BaseCommand):
    help = "Load the MOT failure-rate marts from the DuckDB warehouse into the website database."

    def add_arguments(self, parser):
        default = getattr(settings, "MOT_WAREHOUSE_PATH",
                          Path(settings.BASE_DIR) / "data" / "warehouse" / "mot.duckdb")
        parser.add_argument("--warehouse", default=str(default))
        parser.add_argument("--batch-size", type=int, default=5000)

    def handle(self, *args, warehouse, batch_size, **options):
        try:
            import duckdb
        except ImportError:
            raise CommandError("DuckDB is not installed. Run: pip install duckdb")
        if not Path(warehouse).exists():
            raise CommandError(f"Warehouse not found: {warehouse}")
        try:
            con = duckdb.connect(warehouse, read_only=True)
        except duckdb.IOException as exc:
            raise CommandError(f"Could not open the warehouse (is dbt still running?): {exc}")

        try:
            first_year, last_year = con.execute(
                "SELECT min(year(test_date)), max(year(test_date)) FROM marts.fct_mot_tests"
            ).fetchone()
            rates = con.execute(
                f"SELECT {', '.join(RATE_COLUMNS)} FROM marts.mart_model_year_fail_rates"
            ).fetchall()
            categories = con.execute(
                f"SELECT {', '.join(CATEGORY_COLUMNS)} FROM marts.mart_model_year_defect_categories"
            ).fetchall()
        except duckdb.CatalogException as exc:
            raise CommandError(f"The marts are missing. Run dbt build first. ({exc})")
        finally:
            con.close()

        if first_year != last_year:
            # The marts aggregate every test in the warehouse; the site labels them with one year.
            self.stderr.write(self.style.WARNING(
                f"Tests span {first_year}-{last_year}; figures will be labelled {last_year}."))

        rate_objects = [ModelYearFailRate(test_year=last_year, **dict(zip(RATE_COLUMNS, row)))
                        for row in rates]
        category_objects = []
        for row in categories:
            values = dict(zip(CATEGORY_COLUMNS, row))
            values["model_year_id"] = values.pop("model_year_key")
            category_objects.append(ModelYearDefectCategory(**values))

        with transaction.atomic():
            ModelYearDefectCategory.objects.all().delete()
            ModelYearFailRate.objects.all().delete()
            ModelYearFailRate.objects.bulk_create(rate_objects, batch_size=batch_size)
            ModelYearDefectCategory.objects.bulk_create(category_objects, batch_size=batch_size)

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(rate_objects):,} model-year groups and "
            f"{len(category_objects):,} defect-category rows (MOT tests from {last_year})."))
