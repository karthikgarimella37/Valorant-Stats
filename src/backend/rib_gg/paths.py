"""Landing paths for rib.gg match RSC, replay blobs, and fact jsonl."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def rib_root(repo_root: Path) -> Path:
    """All rib landings stay under data/rib_gg."""
    path = Path(repo_root) / "data" / "rib_gg"
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_jsonl_path(repo_root: Path) -> Path:
    """Event cards so match extract can resume without re-listing /events."""
    path = rib_root(repo_root) / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def event_matches_jsonl_path(repo_root: Path) -> Path:
    """Per-event match lists."""
    path = rib_root(repo_root) / "event_matches.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def matches_jsonl_path(repo_root: Path) -> Path:
    """One index row per series (ids, teams, date, json paths) for join + resume."""
    path = rib_root(repo_root) / "matches.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def match_json_path(repo_root: Path, match_id: str) -> Path:
    """Parsed RSC match payload (maps, roundStats, economy). Re-runs overwrite."""
    path = rib_root(repo_root) / "json" / "matches" / f"{match_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def replay_json_path(repo_root: Path, match_id: str, map_id: str) -> Path:
    """Full replay-data blob (source JSON). Parse loads snapshots into vlr.fact_rib_replay_snapshot."""
    safe_map = str(map_id).replace("/", "_")
    path = rib_root(repo_root) / "json" / "replay" / str(match_id) / f"{safe_map}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def facts_dir(repo_root: Path) -> Path:
    """Parsed fact jsonl so load can retry without re-fetch."""
    path = rib_root(repo_root) / "facts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fact_jsonl_path(repo_root: Path, stem: str) -> Path:
    """One jsonl per rib fact table."""
    return facts_dir(repo_root) / f"{stem}.jsonl"


def crosswalk_jsonl_path(repo_root: Path) -> Path:
    """rib match → vlr match fuzzy join results."""
    return facts_dir(repo_root) / "match_crosswalk.jsonl"
