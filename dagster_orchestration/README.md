# Dagster Orchestration

This is a separate Dagster project. Run it from **this directory**, not the repo root.

The repo root `.venv` has Dagster installed, but it does **not** include the
`dagster_orchestration` package. If you start Dagster from the root, imports like
`dagster_orchestration.definitions` will fail.

## Start the UI

```bash
cd dagster_orchestration
./dev.sh
```

Or without the script:

```bash
cd dagster_orchestration
uv sync
uv run dg dev
```

## Run the sample dbt job from the CLI

```bash
cd dagster_orchestration
uv run dagster job execute -m dagster_orchestration.definitions -j dbt_select_one_plus_ten_job
```

## If you must launch from the repo root

Use the Dagster subproject environment and point at the definitions file:

```bash
uv run --directory dagster_orchestration dagster dev \
  -f src/dagster_orchestration/definitions.py \
  -d .
```
