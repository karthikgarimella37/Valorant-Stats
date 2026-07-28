import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import psycopg2
from dagster import AssetExecutionContext, Definitions, MetadataValue, asset, define_asset_job
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backend.api_connectors.ribs_connector import RibsConnector
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.rib_gg.extract import RibExtractPipeline, landing_dir_for, read_ndjson
from backend.vlr.extract import VlrExtractPipeline

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


def _get_dbt_schema() -> str:
    return os.getenv("DBT_SUPABASE_SCHEMA", "valorant")


def _run_date() -> date:
    raw = os.getenv("RIB_RUN_DATE")
    if raw:
        return date.fromisoformat(raw)
    return date.today()


def _supabase_connect():
    return psycopg2.connect(
        host=_get_required_env_var("SUPABASE_DB_HOST"),
        port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
        dbname=_get_required_env_var("SUPABASE_DB_NAME"),
        user=_get_required_env_var("SUPABASE_DB_USER"),
        password=os.getenv("SUPABASE_DB_PASSWORD", ""),
        sslmode=os.getenv("SUPABASE_DB_SSLMODE", "require"),
    )


def _ensure_schema(context: AssetExecutionContext, schema: str) -> None:
    """Create the target Postgres schema in Supabase if it does not already exist."""
    if not schema.replace("_", "").isalnum():
        raise RuntimeError(f"Invalid schema name: {schema!r}")

    with _supabase_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        connection.commit()

    context.log.info('Ensured schema "%s" exists in Supabase', schema)


def _pipeline() -> RibExtractPipeline:
    return RibExtractPipeline(repo_root=REPO_ROOT, connector=RibsConnector(), run_date=_run_date())


def _vlr_run_date() -> date:
    raw = os.getenv("VLR_RUN_DATE") or os.getenv("RIB_RUN_DATE")
    if raw:
        return date.fromisoformat(raw)
    return date.today()


# ---------------------------------------------------------------------------
# dbt smoke / stub jobs
# ---------------------------------------------------------------------------


@asset(group_name="dbt")
def dbt_build_select_one_plus_ten(context: AssetExecutionContext) -> None:
    """Run the dbt model that materializes `select 1 + 10` in Supabase."""
    if not DBT_BIN.exists():
        raise RuntimeError(
            "dbt executable not found. Create the dbt virtualenv in "
            "`src/backend/sql` and install dbt there first."
        )

    _ensure_schema(context, _get_dbt_schema())

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
    """Query the dbt-built relation in Supabase and emit the result to Dagster logs."""
    schema = _get_dbt_schema()
    relation = f'{schema}."select_1_plus_10"'
    sql = f"select result from {relation} limit 1"

    with _supabase_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("The dbt model ran, but no rows were returned from Supabase.")

    context.log.info("Supabase query result from %s: %s", relation, row[0])


@asset(group_name="dbt")
def dbt_build_star_schema(context: AssetExecutionContext) -> None:
    """
    Ensure the `valorant` schema exists, then materialize rib-aligned stub dim_/fact_ tables via dbt.
    Prefer `rib_gg_star_schema_job` for populated parquet → Supabase loads.
    """
    if not DBT_BIN.exists():
        raise RuntimeError(
            "dbt executable not found. Create the dbt virtualenv in "
            "`src/backend/sql` and install dbt there first."
        )

    schema = _get_dbt_schema()
    _ensure_schema(context, schema)

    models = [
        "dim_events",
        "dim_teams",
        "dim_players",
        "dim_agents",
        "dim_maps",
        "dim_series",
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
        context.log.info(
            "Starting DBT Build into schema '%s' for models: %s",
            schema,
            ", ".join(models),
        )
        _run_command(context, command, cwd=DBT_PROJECT_DIR)
        context.log.info(
            "DBT run completed successfully. Tables created/updated as %s.dim_* / %s.fact_*",
            schema,
            schema,
        )
    except Exception as e:
        context.log.error("DBT run failed! SQL execution failed with error: %s", e)
        raise


# ---------------------------------------------------------------------------
# rib.gg extract → parquet → valorant.*
# ---------------------------------------------------------------------------


@asset(group_name="rib_gg")
def rib_probe_endpoints(context: AssetExecutionContext) -> dict:
    """
    Probe rib.gg endpoints and log status + sample columns.

    Soft-fails when the API is unhealthy (e.g. 503) so operators can see availability.
    """
    context.log.info("=== STEP rib_probe_endpoints: checking rib.gg API health ===")
    connector = RibsConnector()
    results = connector.probe_endpoints()
    ok_count = sum(1 for r in results if r.get("ok"))
    context.log.info("Probe complete: %s/%s endpoints OK", ok_count, len(results))

    healthy = [r["path"] for r in results if r.get("ok")]
    unhealthy = [r for r in results if not r.get("ok")]
    context.log.info("Healthy endpoints: %s", healthy or "(none)")
    for entry in unhealthy:
        context.log.warning(
            "Unhealthy: path=%s status=%s error=%s",
            entry.get("path"),
            entry.get("status_code"),
            entry.get("error"),
        )
    for entry in results:
        if entry.get("ok"):
            context.log.info(
                "OK path=%s status=%s rows=%s columns=%s",
                entry.get("path"),
                entry.get("status_code"),
                entry.get("n_returned"),
                entry.get("columns"),
            )

    if ok_count == 0:
        context.log.error(
            "All rib.gg probes failed. Typical causes: API 503, network block, or DNS. "
            "Extract steps will likely fail until https://be-prod.rib.gg recovers."
        )

    context.add_output_metadata(
        {
            "ok_count": ok_count,
            "total": len(results),
            "results": MetadataValue.json(results),
        }
    )
    return {"ok_count": ok_count, "total": len(results), "results": results}


@asset(group_name="rib_gg", deps=[rib_probe_endpoints])
def rib_extract_teams(context: AssetExecutionContext) -> str:
    """Fetch all teams from rib.gg and write parquet under data/rib_gg/dim_teams/."""
    context.log.info("=== STEP rib_extract_teams: GET /teams/all (fallback /teams) ===")
    try:
        path = _pipeline().extract_teams()
    except Exception:
        context.log.exception("rib_extract_teams failed while calling rib.gg or writing parquet")
        raise
    context.add_output_metadata({"parquet_path": MetadataValue.path(str(path))})
    context.log.info("Teams parquet written: %s", path)
    return str(path)


@asset(group_name="rib_gg", deps=[rib_probe_endpoints])
def rib_extract_events(context: AssetExecutionContext) -> str:
    """Fetch all events from rib.gg and write parquet under data/rib_gg/dim_events/."""
    context.log.info("=== STEP rib_extract_events: GET /events (paginated) ===")
    try:
        path = _pipeline().extract_events()
    except Exception:
        context.log.exception("rib_extract_events failed while calling rib.gg or writing parquet")
        raise
    context.add_output_metadata({"parquet_path": MetadataValue.path(str(path))})
    context.log.info("Events parquet written: %s", path)
    return str(path)


@asset(group_name="rib_gg", deps=[rib_probe_endpoints])
def rib_extract_series(context: AssetExecutionContext) -> dict:
    """
    Fetch all series (parallel) and land NDJSON + parquet for restart-safe normalize.
    """
    context.log.info(
        "=== STEP rib_extract_series: GET /series parallel (~100k rows, several minutes) ==="
    )
    try:
        parquet_path, ndjson_path, series = _pipeline().extract_series_raw()
    except Exception:
        context.log.exception("rib_extract_series failed while calling rib.gg or writing landing files")
        raise
    context.add_output_metadata(
        {
            "parquet_path": MetadataValue.path(str(parquet_path)),
            "ndjson_path": MetadataValue.path(str(ndjson_path)),
            "row_count": len(series),
        }
    )
    context.log.info(
        "Series landing complete: %s rows -> ndjson=%s parquet=%s",
        len(series),
        ndjson_path,
        parquet_path,
    )
    return {
        "parquet_path": str(parquet_path),
        "ndjson_path": str(ndjson_path),
        "row_count": len(series),
    }


@asset(
    group_name="rib_gg",
    deps=[rib_extract_series],
)
def rib_normalize_star(context: AssetExecutionContext) -> dict:
    """
    Explode series NDJSON into dim_series / dim_matches / dim_maps / dim_players parquet.
    """
    run_date = _run_date()
    ndjson_path = landing_dir_for(REPO_ROOT, "series_raw", run_date) / "data.ndjson"
    context.log.info(
        "=== STEP rib_normalize_star: explode series NDJSON at %s (run_date=%s) ===",
        ndjson_path,
        run_date,
    )
    if not ndjson_path.exists():
        raise FileNotFoundError(
            f"Missing series NDJSON at {ndjson_path}. Re-run rib_extract_series first."
        )

    series_records = read_ndjson(ndjson_path)
    context.log.info("Loaded %s series records from NDJSON", len(series_records))
    enrich = os.getenv("RIB_ENRICH_PLAYERS_VIA_API", "false").lower() in {"1", "true", "yes"}
    max_details_raw = os.getenv("RIB_MAX_TEAM_DETAILS")
    max_details = int(max_details_raw) if max_details_raw else 200
    context.log.info(
        "Normalize options: enrich_players_via_api=%s max_team_details=%s",
        enrich,
        max_details,
    )

    paths = _pipeline().normalize_star_from_series(
        series_records,
        enrich_players_via_api=enrich,
        max_team_details=max_details,
    )
    str_paths = {key: str(path) for key, path in paths.items()}
    context.add_output_metadata(
        {key: MetadataValue.path(value) for key, value in str_paths.items()}
    )
    context.log.info("Normalized star parquet paths: %s", str_paths)
    return str_paths


@asset(
    group_name="rib_gg",
    deps=[rib_extract_teams, rib_extract_events, rib_normalize_star],
)
def rib_load_valorant_tables(context: AssetExecutionContext) -> dict:
    """
    Create/replace valorant.dim_* tables in Supabase from parquet landings.
    """
    schema = _get_dbt_schema()
    run_date = _run_date()
    entity_paths = {
        "dim_teams": landing_dir_for(REPO_ROOT, "dim_teams", run_date) / "data.parquet",
        "dim_events": landing_dir_for(REPO_ROOT, "dim_events", run_date) / "data.parquet",
        "dim_series": landing_dir_for(REPO_ROOT, "dim_series", run_date) / "data.parquet",
        "dim_matches": landing_dir_for(REPO_ROOT, "dim_matches", run_date) / "data.parquet",
        "dim_maps": landing_dir_for(REPO_ROOT, "dim_maps", run_date) / "data.parquet",
        "dim_players": landing_dir_for(REPO_ROOT, "dim_players", run_date) / "data.parquet",
    }

    context.log.info(
        "=== STEP rib_load_valorant_tables: load parquet -> %s.* (run_date=%s) ===",
        schema,
        run_date,
    )
    for table, path in entity_paths.items():
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        context.log.info(
            "  %s <- %s exists=%s size_bytes=%s",
            table,
            path,
            exists,
            size,
        )

    connector = SupabaseConnector()
    context.log.info("Connecting to Supabase and replacing tables...")
    counts = connector.load_parquet_dir(entity_paths, schema=schema)
    context.add_output_metadata(
        {
            "schema": schema,
            "row_counts": MetadataValue.json(counts),
        }
    )
    context.log.info("Load complete into schema=%s row_counts=%s", schema, counts)
    return counts


# ---------------------------------------------------------------------------
# VLR.gg extract → parquet → vlr.*
# ---------------------------------------------------------------------------


@asset(group_name="vlr")
def vlr_extract_events(context: AssetExecutionContext) -> str:
    """Paginate completed events from vlr.orlandomm.net into data/vlr/dim_events."""
    context.log.info(
        "=== STEP vlr_extract_events: pages %s-%s status=%s api_workers=%s parallel=%s ===",
        os.getenv("VLR_EVENT_PAGE_START", "1"),
        os.getenv("VLR_EVENT_PAGE_END", "59"),
        os.getenv("VLR_EVENT_STATUS", "completed"),
        os.getenv("VLR_API_MAX_WORKERS", "10"),
        os.getenv("VLR_PARALLEL", "1"),
    )
    pipeline = VlrExtractPipeline(repo_root=REPO_ROOT, run_date=_vlr_run_date())
    path = pipeline.extract_events()
    context.add_output_metadata({"parquet_path": MetadataValue.path(str(path))})
    context.log.info("Events parquet: %s", path)
    return str(path)


@asset(group_name="vlr", deps=[vlr_extract_events])
def vlr_extract_event_matches(context: AssetExecutionContext) -> str:
    """Scrape /event/matches/{id}/ for each event into the match queue parquet."""
    context.log.info(
        "=== STEP vlr_extract_event_matches: scrape schedules ip_rotator=%s html_workers=%s ===",
        os.getenv("VLR_USE_IP_ROTATOR", "auto"),
        os.getenv("VLR_HTML_MAX_WORKERS", "auto"),
    )
    pipeline = VlrExtractPipeline(repo_root=REPO_ROOT, run_date=_vlr_run_date())
    path = pipeline.extract_event_matches()
    context.add_output_metadata({"parquet_path": MetadataValue.path(str(path))})
    context.log.info("Event match queue: %s", path)
    return str(path)


@asset(group_name="vlr", deps=[vlr_extract_event_matches])
def vlr_extract_match_details(context: AssetExecutionContext) -> dict:
    """
    Scrape overview/performance/economy tabs for each queued match.
    Writes dim_* and fact_* parquet under data/vlr/ (checkpointed).
    """
    context.log.info(
        "=== STEP vlr_extract_match_details: VLR_MAX_MATCHES=%s html_workers=%s delay=%ss ===",
        os.getenv("VLR_MAX_MATCHES", "unlimited"),
        os.getenv("VLR_HTML_MAX_WORKERS", "3"),
        os.getenv("VLR_REQUEST_DELAY_SEC", "0.35"),
    )
    pipeline = VlrExtractPipeline(repo_root=REPO_ROOT, run_date=_vlr_run_date())
    paths = pipeline.extract_match_details()
    str_paths = {key: str(path) for key, path in paths.items()}
    context.add_output_metadata(
        {key: MetadataValue.path(value) for key, value in str_paths.items()}
    )
    context.log.info("Match detail parquet paths: %s", str_paths)
    return str_paths


@asset(
    group_name="vlr",
    deps=[vlr_extract_events, vlr_extract_match_details],
)
def vlr_load_supabase(context: AssetExecutionContext) -> dict:
    """Create/replace vlr.* tables in Supabase from parquet landings."""
    run_date = _vlr_run_date()
    pipeline = VlrExtractPipeline(repo_root=REPO_ROOT, run_date=run_date)
    entity_paths = pipeline.entity_paths_for_load()
    schema = "vlr"
    primary_keys = {
        "dim_events": "id",
        "dim_teams": "id",
        "dim_players": "id",
        "dim_agents": "name",
        "dim_maps": "name",
        "dim_matches": "match_id",
    }

    context.log.info("=== STEP vlr_load_supabase: load parquet -> %s.* ===", schema)
    for table, path in entity_paths.items():
        context.log.info(
            "  %s <- %s exists=%s",
            table,
            path,
            path.exists(),
        )

    connector = SupabaseConnector()
    counts = connector.load_parquet_dir(
        entity_paths,
        schema=schema,
        primary_keys=primary_keys,
    )
    context.add_output_metadata(
        {
            "schema": schema,
            "row_counts": MetadataValue.json(counts),
        }
    )
    context.log.info("Loaded into %s: %s", schema, counts)
    return counts


dbt_job = define_asset_job(
    "dbt_select_one_plus_ten_job",
    selection=[dbt_build_select_one_plus_ten, log_select_one_plus_ten_result],
)

dbt_star_schema_job = define_asset_job(
    "dbt_star_schema_job",
    selection=[dbt_build_star_schema],
)

rib_gg_star_schema_job = define_asset_job(
    "rib_gg_star_schema_job",
    selection=[
        rib_probe_endpoints,
        rib_extract_teams,
        rib_extract_events,
        rib_extract_series,
        rib_normalize_star,
        rib_load_valorant_tables,
    ],
)

vlr_star_schema_job = define_asset_job(
    "vlr_star_schema_job",
    selection=[
        vlr_extract_events,
        vlr_extract_event_matches,
        vlr_extract_match_details,
        vlr_load_supabase,
    ],
)

defs = Definitions(
    assets=[
        dbt_build_select_one_plus_ten,
        log_select_one_plus_ten_result,
        dbt_build_star_schema,
        rib_probe_endpoints,
        rib_extract_teams,
        rib_extract_events,
        rib_extract_series,
        rib_normalize_star,
        rib_load_valorant_tables,
        vlr_extract_events,
        vlr_extract_event_matches,
        vlr_extract_match_details,
        vlr_load_supabase,
    ],
    jobs=[dbt_job, dbt_star_schema_job, rib_gg_star_schema_job, vlr_star_schema_job],
)
