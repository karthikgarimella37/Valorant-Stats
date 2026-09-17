"""rib.gg overlay extract. Heavy imports are lazy so parse/tables load without polars."""

from __future__ import annotations

from typing import Any

__all__ = [
    "RibExtractPipeline",
    "extract_rib_matches",
    "landing_dir_for",
    "load_rib_facts",
    "parse_rib_facts",
    "run_rib_facts",
]


def __getattr__(name: str) -> Any:
    """Load extract/pipeline only when those names are used."""
    if name in {"RibExtractPipeline", "landing_dir_for"}:
        from .extract import RibExtractPipeline, landing_dir_for

        return RibExtractPipeline if name == "RibExtractPipeline" else landing_dir_for
    if name in {"extract_rib_matches", "load_rib_facts", "parse_rib_facts", "run_rib_facts"}:
        from . import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
