"""
Prefect flow that refreshes the MOT data end to end:

    1. ingest     load new or changed DVSA files into DuckDB (unchanged files are skipped)
    2. transform  dbt build: every model and every test runs as its own Prefect task
    3. publish    copy the marts into the website's database (manage.py load_mot_marts)

If step 1 finds nothing new, steps 2 and 3 are skipped, so running it again is cheap and
safe. Use --force to rebuild and publish anyway (after changing a dbt model, say).

Run once (Prefect starts a temporary local server if none is running):
    python -m orchestration.flow run
    python -m orchestration.flow run --force

Run on a schedule, with the Prefect UI showing every run:
    prefect server start                      (terminal 1, UI at http://127.0.0.1:4200)
    python -m orchestration.flow serve        (terminal 2: 06:00 on the 2nd of each month)
"""

import argparse
import gc
import json
import os
import subprocess
import sys
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.schedules import Cron
from prefect_dbt import PrefectDbtRunner, PrefectDbtSettings

from pipeline.ingest import run as ingest_files

ROOT = Path(__file__).resolve().parent.parent
TRANSFORM = ROOT / "transform"
WAREHOUSE = Path(os.environ.get("MOT_WAREHOUSE", ROOT / "data" / "warehouse" / "mot.duckdb")).resolve()

# dbt's profile reads these. Absolute paths, so dbt finds the warehouse wherever it's run from.
os.environ["MOT_WAREHOUSE"] = str(WAREHOUSE)
os.environ.setdefault("MOT_WAREHOUSE_TMP", str(WAREHOUSE.parent / "duckdb_tmp"))


def release_warehouse() -> None:
    """dbt-duckdb keeps one DuckDB handle open per process after dbt finishes. DuckDB lets
    only one process write to a file, so the publish step (a separate process) couldn't
    open the warehouse until this one let go of it. Close it explicitly."""
    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    env = DuckDBConnectionManager._ENV
    if env is not None:
        env.close()
    DuckDBConnectionManager.close_all_connections()
    gc.collect()


@task(name="ingest", retries=1, retry_delay_seconds=30)
def ingest(raw_dir: str) -> dict:
    """Load new or changed files. Returns how many were loaded and skipped."""
    logger = get_run_logger()
    return ingest_files(ROOT / raw_dir, warehouse=WAREHOUSE, log=logger.info)


def transform(dbt_vars: dict | None, skip_reconciliation: bool) -> None:
    """dbt build. Not a task itself: prefect-dbt turns each dbt model and test into its
    own task, so the run shows exactly which one failed. A failing test stops the flow
    here, before anything reaches the website."""
    args = ["build"]
    if dbt_vars:
        args += ["--vars", json.dumps(dbt_vars)]
    if skip_reconciliation:
        # only meaningful on the real data (CI runs on generated sample data)
        args += ["--exclude", "assert_matches_dvsa_published_rates"]
    settings = PrefectDbtSettings(project_dir=TRANSFORM, profiles_dir=TRANSFORM)
    try:
        PrefectDbtRunner(settings=settings, raise_on_failure=True).invoke(args)
    finally:
        release_warehouse()


@task(name="publish", retries=2, retry_delay_seconds=60)
def publish() -> None:
    """Copy the marts into the website's database. It's one transaction inside
    load_mot_marts, so a retry after a dropped connection is safe."""
    logger = get_run_logger()
    result = subprocess.run(
        [sys.executable, str(ROOT / "manage.py"), "load_mot_marts", "--warehouse", str(WAREHOUSE)],
        cwd=ROOT, capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        if line.strip():
            logger.info(line)
    if result.returncode != 0:
        raise RuntimeError(f"load_mot_marts failed with exit code {result.returncode}")


@flow(name="refresh-mot-data")
def refresh_mot_data(raw_dir: str = "data/raw/2024", force: bool = False,
                     dbt_vars: dict | None = None, skip_reconciliation: bool = False) -> dict:
    logger = get_run_logger()
    counts = ingest(raw_dir)
    if counts["loaded"] == 0 and not force:
        logger.info("No new or changed files, so nothing to rebuild or publish.")
        return {"status": "up to date", **counts}
    transform(dbt_vars, skip_reconciliation)
    publish()
    logger.info("Refresh finished: warehouse rebuilt, tested and published to the website.")
    return {"status": "refreshed", **counts}


def main():
    parser = argparse.ArgumentParser(description="Refresh the MOT data with Prefect.")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="run the flow once")
    run_cmd.add_argument("--raw-dir", default="data/raw/2024")
    run_cmd.add_argument("--force", action="store_true", help="rebuild and publish even if nothing new was loaded")
    run_cmd.add_argument("--dbt-vars", type=json.loads, default=None, help="JSON, e.g. '{\"min_tests_per_group\": 20}'")
    run_cmd.add_argument("--skip-reconciliation", action="store_true")

    serve_cmd = commands.add_parser("serve", help="keep running and refresh on a schedule")
    serve_cmd.add_argument("--raw-dir", default="data/raw/2024")
    serve_cmd.add_argument("--cron", default="0 6 2 * *", help="UK time; default 06:00 on the 2nd of each month")

    args = parser.parse_args()
    if args.command == "run":
        result = refresh_mot_data(raw_dir=args.raw_dir, force=args.force, dbt_vars=args.dbt_vars,
                                  skip_reconciliation=args.skip_reconciliation)
        print(json.dumps(result))
    else:
        refresh_mot_data.serve(name="monthly-refresh",
                               schedule=Cron(args.cron, timezone="Europe/London"),
                               parameters={"raw_dir": args.raw_dir})


if __name__ == "__main__":
    main()
