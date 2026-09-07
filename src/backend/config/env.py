"""Find every repo `.env` so AWS / Supabase keys work no matter which folder holds them."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".cursor",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".dagster",
}
_SKIP_ENV_NAMES = {".env_example", ".env.example", ".env.sample", ".env.template"}

_LOAD_LOCK = threading.Lock()
_LOADED_PATHS: list[Path] | None = None


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up to PROJECT_STATUS.md / .git so env search covers the whole repo."""
    here = Path(start or __file__).resolve()
    for path in (here, *here.parents):
        if (path / "PROJECT_STATUS.md").exists() or (path / ".git").is_dir():
            return path
    return here.parents[3] if len(here.parents) >= 3 else here.parent


def discover_env_files(repo_root: Path | None = None) -> list[Path]:
    """Return every `.env` under the repo, skipping venv/git/cache trees."""
    root = find_repo_root(repo_root)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIR_NAMES]
        for name in filenames:
            if name in _SKIP_ENV_NAMES:
                continue
            if name == ".env":
                found.append(Path(dirpath) / name)
    # Shallower files first so src/config/.env fills keys the root file omitted.
    found.sort(key=lambda path: (len(path.relative_to(root).parts), str(path)))
    return found


def load_project_env(repo_root: Path | None = None, *, force: bool = False) -> list[Path]:
    """Load all discovered `.env` files (override=False so process env wins)."""
    global _LOADED_PATHS
    with _LOAD_LOCK:
        if _LOADED_PATHS is not None and not force:
            return list(_LOADED_PATHS)
        paths = discover_env_files(repo_root)
        loaded: list[Path] = []
        for env_path in paths:
            if not env_path.exists():
                continue
            logger.info("[env] Loading %s", env_path)
            load_dotenv(env_path, override=False)
            loaded.append(env_path)
        if not loaded:
            logger.warning("[env] No .env files found under %s", find_repo_root(repo_root))
        _LOADED_PATHS = loaded
        return list(loaded)
