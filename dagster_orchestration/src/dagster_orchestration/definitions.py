import os
import subprocess
from pathlib import Path

import psycopg2
from dagster import AssetExecutionContext, Definitions, asset, define_asset_job
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
DBT_PROJECT_DIR = REPO_ROOT / "src" / "backend" / "sql"
DBT_BIN = DBT_PROJECT_DIR / ".venv" / "bin" / "dbt"
ENV_PATHS = [REPO_ROOT / ".env", REPO_ROOT / "src" / "config" / ".env"]

for env_path in ENV_PATHS:
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _run_command(context: AssetExecutionContext, command: list[str], cwd: Path) -> None:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
    )

    assert process.stdout is not None
    for line in process.stdout:
        context.log.info(line.rstrip())

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Command failed with exit code {return_code}: {' '.join(command)}")


def _get_required_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@asset(group_name="dbt")
def dbt_build_select_one_plus_ten(context: AssetExecutionContext) -> None:
    """
    Run the dbt model that materializes `select 1 + 10` in Supabase.
    """
    if not DBT_BIN.exists():
        raise RuntimeError(
            "dbt executable not found. Create the dbt virtualenv in "
            "`src/backend/sql` and install dbt there first."
        )

    command = [
        str(DBT_BIN),
        "build",
        "--project-dir",
        str(DBT_PROJECT_DIR),
        "--profiles-dir",
        str(DBT_PROJECT_DIR),
        "--select",
        "select_1_plus_10",
    ]
    _run_command(context, command, cwd=DBT_PROJECT_DIR)


@asset(group_name="dbt", deps=[dbt_build_select_one_plus_ten])
def log_select_one_plus_ten_result(context: AssetExecutionContext) -> None:
    """
    Query the dbt-built relation in Supabase and emit the result to Dagster logs.
    """
    schema = os.getenv("DBT_SUPABASE_SCHEMA", "analytics")
    relation = f'{schema}."select_1_plus_10"'
    sql = f"select result from {relation} limit 1"

    with psycopg2.connect(
        host=_get_required_env_var("SUPABASE_DB_HOST"),
        port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
        dbname=_get_required_env_var("SUPABASE_DB_NAME"),
        user=_get_required_env_var("SUPABASE_DB_USER"),
        password=os.getenv("SUPABASE_DB_PASSWORD", ""),
        sslmode=os.getenv("SUPABASE_DB_SSLMODE", "require"),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("The dbt model ran, but no rows were returned from Supabase.")

    context.log.info("Supabase query result from %s: %s", relation, row[0])


@asset(group_name="dbt")
def dbt_build_star_schema(context: AssetExecutionContext) -> None:
    """
    Run the dbt build command to materialize all Star Schema models in Supabase.
    """
    if not DBT_BIN.exists():
        raise RuntimeError(
            "dbt executable not found. Create the dbt virtualenv in "
            "`src/backend/sql` and install dbt there first."
        )

    # Construct dbt command with multiple --select arguments
    models = [
        "dim_events",
        "dim_teams",
        "dim_players",
        "dim_agents",
        "dim_maps",
        "dim_matches",
        "fact_match_overall_stats",
        "fact_match_performance",
        "fact_match_economy",
    ]
    command = [
        str(DBT_BIN),
        "build",
        "--project-dir",
        str(DBT_PROJECT_DIR),
        "--profiles-dir",
        str(DBT_PROJECT_DIR),
    ]
    for model in models:
        command.extend(["--select", model])
    
    try:
        context.log.info(f"Starting DBT Build for models: {', '.join(models)}")
        _run_command(context, command, cwd=DBT_PROJECT_DIR)
        context.log.info("DBT run completed successfully. Tables created/updated in Supabase!")
    except Exception as e:
        context.log.error(f"DBT run failed! SQL execution failed with error: {e}")
        raise e



dbt_job = define_asset_job(
    "dbt_select_one_plus_ten_job",
    selection=[dbt_build_select_one_plus_ten, log_select_one_plus_ten_result],
)

dbt_star_schema_job = define_asset_job(
    "dbt_star_schema_job",
    selection=[dbt_build_star_schema],
)

defs = Definitions(
    assets=[dbt_build_select_one_plus_ten, log_select_one_plus_ten_result, dbt_build_star_schema],
    jobs=[dbt_job, dbt_star_schema_job],
)