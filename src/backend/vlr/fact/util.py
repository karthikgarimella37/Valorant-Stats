"""Shared fact landing helpers. Event-only historical load does not write facts yet."""

from __future__ import annotations

from pathlib import Path


def fact_json_dir(repo_root: Path, entity: str) -> Path:
    """Reserve data/vlr/facts/<entity> so later historical facts match event JSON layout."""
    path = Path(repo_root) / "data" / "vlr" / "facts" / entity
    path.mkdir(parents=True, exist_ok=True)
    return path
