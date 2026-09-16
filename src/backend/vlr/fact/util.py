"""Shared number / key helpers for vlr fact extract from matches.jsonl."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.vlr.field_maps import PERFORMANCE_ADV_KEYS

REPO_ROOT = Path(__file__).resolve().parents[4]

UNKNOWN_ID = "-1"

WIN_METHOD_CODES = {
    "elim": 1,
    "elimination": 1,
    "boom": 2,
    "spike": 2,
    "exploded": 2,
    "defuse": 3,
    "defused": 3,
    "time": 4,
    "expired": 4,
}

DURATION_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d+)$")
PLAYED_WON_RE = re.compile(r"(-?\d+)\s*\(\s*(-?\d+)\s*\)")
VETO_PART_RE = re.compile(
    r"^\s*(.+?)\s+(ban|pick)s?\s+(.+?)\s*$",
    re.I,
)
REMAINS_RE = re.compile(r"^\s*(.+?)\s+remains\s*$", re.I)


def facts_dir(repo_root: Path) -> Path:
    """Landing folder so fact jsonl can retry load without re-parsing matches.jsonl."""
    return repo_root / "data" / "vlr" / "facts"


def fact_jsonl_path(repo_root: Path, stem: str) -> Path:
    """One jsonl per fact table."""
    return facts_dir(repo_root) / f"{stem}.jsonl"


def to_int(value: Any) -> int | None:
    """Scoreboard strings like '+9' or '24' into ints."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "").replace("+", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return int(float(text))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    """ACS/ADR/rating/percent strings into numerics."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def duration_sec(raw: Any) -> int | None:
    """Map clock '32:10' or '1:04:12' to seconds."""
    text = str(raw or "").strip()
    match = DURATION_RE.match(text)
    if not match:
        return to_int(raw)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def played_won(raw: Any) -> tuple[int | None, int | None]:
    """VLR economy cell: '7 (4)' is played (won); bare '2' is both."""
    if raw is None or raw == "":
        return None, None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    pair = PLAYED_WON_RE.search(text)
    if pair:
        return int(pair.group(1)), int(pair.group(2))
    n = to_int(text)
    return n, n


def win_method_code(raw: Any) -> int | None:
    """1=elim, 2=boom, 3=defuse, 4=time. Current /v2 rounds often omit method."""
    if not raw:
        return None
    return WIN_METHOD_CODES.get(str(raw).strip().lower())


def other_team_id(winner_id: str | None, team_1_id: str | None, team_2_id: str | None) -> str | None:
    """Losing team on a round."""
    if not winner_id:
        return None
    if winner_id == team_1_id:
        return team_2_id
    if winner_id == team_2_id:
        return team_1_id
    return None


def remap_advanced(row: dict[str, Any]) -> dict[str, Any]:
    """Numbered performance cells → multi_2k / clutch_1v1 / econ / plants / defuses."""
    return {PERFORMANCE_ADV_KEYS.get(str(k), k): v for k, v in row.items()}


def match_advanced(player_name: str, series_advanced: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Scoreboard ign vs VLR 'Marved SEN' advanced_stats player label."""
    ign = (player_name or "").strip().lower()
    if not ign:
        return {}
    direct = series_advanced.get(ign)
    if direct:
        return direct
    for label, row in series_advanced.items():
        if label == ign or label.startswith(ign + " "):
            return row
    return {}


def parse_veto_actions(raw: str | None) -> list[dict[str, Any]]:
    """Split 'C9 ban Breeze; SEN pick Haven; Lotus remains' into ordered actions."""
    text = (raw or "").strip()
    if not text:
        return []
    out: list[dict[str, Any]] = []
    for order, chunk in enumerate((p.strip() for p in text.split(";") if p.strip()), start=1):
        remains = REMAINS_RE.match(chunk)
        if remains:
            out.append(
                {
                    "action_order": order,
                    "team_tag": None,
                    "map_name": remains.group(1).strip(),
                    "is_ban": False,
                    "is_pick": False,
                    "is_decider": True,
                }
            )
            continue
        match = VETO_PART_RE.match(chunk)
        if not match:
            continue
        action = match.group(2).lower()
        out.append(
            {
                "action_order": order,
                "team_tag": match.group(1).strip(),
                "map_name": match.group(3).strip(),
                "is_ban": action.startswith("ban"),
                "is_pick": action.startswith("pick"),
                "is_decider": False,
            }
        )
    return out
