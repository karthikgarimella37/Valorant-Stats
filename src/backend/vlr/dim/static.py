"""Seed vlr.dim_vct_regions, dim_regions, dim_economy from in-repo lists (no VLR API)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.regions import LOCAL_REGIONS, LOCAL_TO_VCT, VCT_REGIONS

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]

# Credit bands used when mapping VLR economy-tab loadout to this dim.
ECONOMY_SEED: tuple[tuple[str, str, int, int], ...] = (
    ("pistol", "Pistol", 0, 800),
    ("eco", "Eco", 0, 2000),
    ("semi", "Semi buy", 2000, 3900),
    ("force", "Force buy", 2000, 3900),
    ("full", "Full buy", 3900, 9000),
)

VCT_COLS = ("vct_region_code", "vct_region_name", "insert_date", "update_date")
VCT_TYPES = {
    "row_number": "BIGINT",
    "vct_region_code": "TEXT",
    "vct_region_name": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}

REGION_COLS = ("region_code", "region_name", "vct_region_code", "insert_date", "update_date")
REGION_TYPES = {
    "row_number": "BIGINT",
    "region_code": "TEXT",
    "region_name": "TEXT",
    "vct_region_code": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}

ECONOMY_COLS = (
    "economy_code",
    "economy_name",
    "min_loadout",
    "max_loadout",
    "insert_date",
    "update_date",
)
ECONOMY_TYPES = {
    "row_number": "BIGINT",
    "economy_code": "TEXT",
    "economy_name": "TEXT",
    "min_loadout": "INTEGER",
    "max_loadout": "INTEGER",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}


def _root(repo_root: Path | None) -> Path:
    return repo_root or REPO_ROOT


def apply_static_schema(repo_root: Path | None = None) -> None:
    """Create the three seed dims so later jsonl loads can join region codes."""
    load_project_env(repo_root)
    root = _root(repo_root)
    apply_dim_schema(root, "vlr_dim_vct_regions.sql", "dim_vct_regions", VCT_TYPES)
    apply_dim_schema(root, "vlr_dim_regions.sql", "dim_regions", REGION_TYPES)
    apply_dim_schema(root, "vlr_dim_economy.sql", "dim_economy", ECONOMY_TYPES)


def seed_vct_rows() -> list[dict[str, Any]]:
    """Four VCT circuits from regions.py."""
    return stamp_rows(
        [{"vct_region_code": code, "vct_region_name": name} for code, name in VCT_REGIONS]
    )


def seed_region_rows() -> list[dict[str, Any]]:
    """Local ranking codes with optional parent circuit (gc has none)."""
    return stamp_rows(
        [
            {
                "region_code": code,
                "region_name": name,
                "vct_region_code": LOCAL_TO_VCT.get(code),
            }
            for code, name in LOCAL_REGIONS
        ]
    )


def seed_economy_rows() -> list[dict[str, Any]]:
    """Buy-type lookup used later by economy facts."""
    return stamp_rows(
        [
            {
                "economy_code": code,
                "economy_name": name,
                "min_loadout": lo,
                "max_loadout": hi,
            }
            for code, name, lo, hi in ECONOMY_SEED
        ]
    )


def load_static(repo_root: Path | None = None) -> dict[str, int]:
    """Upsert seed dims. Serial: 21 rows, no I/O to parallelize."""
    load_project_env(repo_root)
    apply_static_schema(repo_root)
    counts = {
        "dim_vct_regions": upsert_dim_rows(
            seed_vct_rows(), table="dim_vct_regions", columns=VCT_COLS, conflict_column="vct_region_code"
        ),
        "dim_regions": upsert_dim_rows(
            seed_region_rows(), table="dim_regions", columns=REGION_COLS, conflict_column="region_code"
        ),
        "dim_economy": upsert_dim_rows(
            seed_economy_rows(), table="dim_economy", columns=ECONOMY_COLS, conflict_column="economy_code"
        ),
    }
    logger.info("[static] Done counts=%s", counts)
    return counts
