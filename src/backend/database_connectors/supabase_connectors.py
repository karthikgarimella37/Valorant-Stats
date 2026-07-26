import io
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

import polars as pl
import psycopg2 as psy
from dotenv import load_dotenv
from psycopg2 import sql

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _find_project_root(start_path: Path) -> Path:
    """Walk upward until we find the repository's Python project root."""
    for path in (start_path, *start_path.parents):
        if (path / "pyproject.toml").exists():
            return path
    return start_path


PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)
ENV_PATHS = [PROJECT_ROOT / ".env", PROJECT_ROOT / "src" / "config" / ".env"]
for env_path in ENV_PATHS:
    if env_path.exists():
        logger.info("Loading environment variables from %s", env_path)
        load_dotenv(env_path, override=False)


_POLARS_TO_PG = {
    pl.Int8: "SMALLINT",
    pl.Int16: "SMALLINT",
    pl.Int32: "INTEGER",
    pl.Int64: "BIGINT",
    pl.UInt8: "INTEGER",
    pl.UInt16: "INTEGER",
    pl.UInt32: "BIGINT",
    pl.UInt64: "BIGINT",
    pl.Float32: "DOUBLE PRECISION",
    pl.Float64: "DOUBLE PRECISION",
    pl.Boolean: "BOOLEAN",
    pl.Utf8: "TEXT",
    pl.String: "TEXT",
    pl.Date: "DATE",
    pl.Datetime: "TIMESTAMP",
    pl.Time: "TIME",
    pl.Null: "TEXT",
}


def _pg_type_for(dtype: pl.DataType) -> str:
    for polars_type, pg_type in _POLARS_TO_PG.items():
        if dtype == polars_type:
            return pg_type
    # Structs / lists / unknowns land as TEXT (JSON already stringified upstream).
    return "TEXT"


def _safe_ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise RuntimeError(f"Invalid SQL identifier: {name!r}")
    return name


class SupabaseConnector:
    """A connector for the Supabase / Postgres database."""

    def __init__(self):
        logger.info("Initializing SupabaseConnector")
        self.db_host = os.environ.get("SUPABASE_DB_HOST")
        self.db_port = int(os.environ.get("SUPABASE_DB_PORT", "5432"))
        self.db_name = os.environ.get("SUPABASE_DB_NAME")
        self.db_user = os.environ.get("SUPABASE_DB_USER")
        self.db_password = os.environ.get("SUPABASE_DB_PASSWORD", "")
        self.sslmode = os.environ.get("SUPABASE_DB_SSLMODE", "require")

    def _connect(self) -> psy.extensions.connection:
        logger.info("Connecting to Supabase database")
        try:
            return psy.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                sslmode=self.sslmode,
            )
        except Exception as e:
            logger.error("Error connecting to Supabase database: %s", e)
            raise

    def fetch_all(self, sql_text: str, params: Optional[Iterable[Any]] = None) -> list[Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text, params or ())
                return list(cur.fetchall())

    def fetch_one(self, sql_text: str, params: Optional[Iterable[Any]] = None) -> Optional[Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text, params or ())
                return cur.fetchone()

    def execute(self, sql_text: str, params: Optional[Iterable[Any]] = None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text, params or ())
            conn.commit()

    def ensure_schema(self, schema: str = "valorant") -> None:
        schema = _safe_ident(schema)
        self.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        logger.info('Ensured schema "%s"', schema)

    def replace_table_from_parquet(
        self,
        parquet_path: Path,
        *,
        schema: str = "valorant",
        table: str,
        primary_key: str = "id",
    ) -> int:
        """
        Create/replace schema.table from a parquet file (parquet schema = source of truth).

        Uses a staging table + rename swap, then COPY via CSV buffer for portability.
        """
        schema = _safe_ident(schema)
        table = _safe_ident(table)
        primary_key = _safe_ident(primary_key)

        path = Path(parquet_path)
        if not path.exists():
            raise FileNotFoundError(path)

        df = pl.read_parquet(path)
        if df.is_empty() and df.width == 0:
            logger.warning("Skipping empty parquet with no columns: %s", path)
            return 0

        # Normalize null-only columns to text so CREATE TABLE succeeds.
        cast_exprs = []
        for col_name, dtype in zip(df.columns, df.dtypes):
            if dtype == pl.Null:
                cast_exprs.append(pl.col(col_name).cast(pl.Utf8))
            else:
                cast_exprs.append(pl.col(col_name))
        df = df.select(cast_exprs)

        staging = f"{table}__staging"
        columns_ddl = ", ".join(
            f'"{_safe_ident(col)}" {_pg_type_for(dtype)}'
            for col, dtype in zip(df.columns, df.dtypes)
        )
        pk_clause = f', PRIMARY KEY ("{primary_key}")' if primary_key in df.columns else ""

        create_staging_sql = f'''
            CREATE TABLE "{schema}"."{staging}" (
                {columns_ddl}
                {pk_clause}
            )
        '''

        # Write CSV for COPY
        csv_buf = io.StringIO()
        df.write_csv(csv_buf, include_header=False, null_value="")
        csv_buf.seek(0)

        col_list = sql.SQL(", ").join(sql.Identifier(c) for c in df.columns)
        copy_sql = sql.SQL("COPY {}.{} ({}) FROM STDIN WITH (FORMAT csv, NULL '')").format(
            sql.Identifier(schema),
            sql.Identifier(staging),
            col_list,
        )

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{schema}"."{staging}"')
                cur.execute(create_staging_sql)
                cur.copy_expert(copy_sql.as_string(conn), csv_buf)
                cur.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')
                cur.execute(f'ALTER TABLE "{schema}"."{staging}" RENAME TO "{table}"')
            conn.commit()

        logger.info(
            'Loaded %s rows into %s.%s from %s',
            df.height,
            schema,
            table,
            path,
        )
        return df.height

    def load_parquet_dir(
        self,
        entity_to_path: dict[str, Path],
        *,
        schema: str = "valorant",
    ) -> dict[str, int]:
        """Load multiple entity parquet files into valorant.<entity> tables."""
        logger.info("[load] Ensuring schema %s exists...", schema)
        self.ensure_schema(schema)
        counts: dict[str, int] = {}
        items = list(entity_to_path.items())
        for index, (table, path) in enumerate(items, start=1):
            if path is None or not Path(path).exists():
                logger.warning(
                    "[load] (%s/%s) Missing parquet for %s: %s — skipping",
                    index,
                    len(items),
                    table,
                    path,
                )
                continue
            logger.info(
                "[load] (%s/%s) Replacing %s.%s from %s ...",
                index,
                len(items),
                schema,
                table,
                path,
            )
            counts[table] = self.replace_table_from_parquet(
                path,
                schema=schema,
                table=table,
            )
        logger.info("[load] Finished. Row counts: %s", counts)
        return counts


def main() -> None:
    logger.info("Starting main function")
    connector = SupabaseConnector()
    logger.info(connector.fetch_all("SELECT 1"))
    logger.info(connector.fetch_one("SELECT 1"))


if __name__ == "__main__":
    main()
