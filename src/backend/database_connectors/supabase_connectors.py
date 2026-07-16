import os
from pathlib import Path
from typing import Any, Iterable, Optional

import psycopg2 as psy
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _find_project_root(start_path: Path) -> Path:
    """
    Walk upward until we find the repository's Python project root.
    """
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

class SupabaseConnector:
    """
    A connector for the Supabase database.
    """
    def __init__(self):
        """
        Initialize the connector.
        """
        logger.info("Initializing SupabaseConnector")
        self.db_host = os.environ.get("SUPABASE_DB_HOST")
        self.db_port = int(os.environ.get("SUPABASE_DB_PORT"))
        self.db_name = os.environ.get("SUPABASE_DB_NAME")
        self.db_user = os.environ.get("SUPABASE_DB_USER")
        self.db_password = os.environ.get("SUPABASE_DB_PASSWORD", "")
        print(self.db_host, self.db_port, self.db_name, self.db_user)

    def _connect(self) -> psy.Connection:
        """
        Connect to the Supabase database.
        """
        logger.info("Connecting to Supabase database")
        try:
            return psy.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                sslmode="disable",
            )
        except Exception as e:
            logger.error(f"Error connecting to Supabase database: {e}")
            raise e
        
    def fetch_all(self, sql: str, params: Optional[Iterable[Any]] = None) -> list[dict[str, Any]]:
        """
        Fetch all rows from the database.
        """
        logger.info(f"Fetching all rows from the database: {sql}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return list(cur.fetchall())
            
    def fetch_one(self, sql: str, params: Optional[Iterable[Any]] = None) -> Optional[dict[str, Any]]:
        """
        Fetch one row from the database.
        """
        logger.info(f"Fetching one row from the database: {sql}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return cur.fetchone()
            
    def execute(self, sql: str, params: Optional[Iterable[Any]] = None) -> None:
        """
        Execute a SQL statement.
        """
        logger.info(f"Executing a SQL statement: {sql}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
            conn.commit()

def main():
    """
    Main function to test the connector.
    """
    logger.info("Starting main function")
    connector = SupabaseConnector()
    logger.info(connector.fetch_all("SELECT 1"))
    logger.info(connector.fetch_one("SELECT 1"))

if __name__ == "__main__":
    main()