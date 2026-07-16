# dbt Project

This folder is a standalone dbt project that should run in its own Python 3.13 virtual environment.

## Why it is separate

The main repository targets Python 3.14 for app code and Dagster, while the supported dbt setup in this repository runs more reliably on Python 3.13.

## Create the dbt environment

Run these commands from `src/backend/sql`:

```bash
uv venv .venv --python 3.13
source .venv/bin/activate
uv pip install -r <(python - <<'PY'
import tomllib
from pathlib import Path

deps = tomllib.loads(Path("pyproject.toml").read_text())["project"]["dependencies"]
print("\n".join(deps))
PY
)
```

If your shell does not support process substitution, install the packages directly:

```bash
uv pip install "dbt-core>=1.11.11,<1.12" "dbt-postgres>=1.10.1"
```

## Required environment variables

Dagster and dbt both read these values:

- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`
- `SUPABASE_DB_SSLMODE` (optional, defaults to `require`)
- `DBT_SUPABASE_SCHEMA` (optional, defaults to `analytics`)
- `DBT_THREADS` (optional, defaults to `4`)

## Local dbt commands

```bash
source .venv/bin/activate
.venv/bin/dbt debug --project-dir . --profiles-dir .
.venv/bin/dbt build --project-dir . --profiles-dir . --select select_1_plus_10
```
