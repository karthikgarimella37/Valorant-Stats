# Why: run Dagster + dbt jobs in Compose next to self-hosted vlrggapi.
FROM python:3.12-slim

WORKDIR /opt/dagster/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY dagster_orchestration/pyproject.toml dagster_orchestration/uv.lock* ./dagster_orchestration/
COPY src ./src
COPY dagster_orchestration/src ./dagster_orchestration/src
COPY docker/dagster/dagster.yaml /opt/dagster/dagster_home/dagster.yaml

ENV PYTHONPATH=/opt/dagster/app/src:/opt/dagster/app/dagster_orchestration/src
ENV DAGSTER_HOME=/opt/dagster/dagster_home

RUN pip install --no-cache-dir \
    "dagster==1.13.9" \
    "dagster-webserver==1.13.9" \
    "beautifulsoup4>=4.13.0" \
    "polars>=1.41.1" \
    "psycopg2-binary>=2.9.12" \
    "pyarrow>=20.0.0" \
    "python-dotenv>=1.2.2" \
    "requests>=2.34.2" \
    "requests-ip-rotator>=1.0.18"

WORKDIR /opt/dagster/app
EXPOSE 3000
