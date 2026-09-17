"""Fuzzy-join rib series to VLR series so overlay facts carry both ids."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.rib_gg.paths import matches_jsonl_path as rib_matches_jsonl_path
from backend.vlr.dim.util import matches_jsonl_path as vlr_matches_jsonl_path
from backend.vlr.fact.player_ids import load_player_id_lookup
from backend.vlr.fact.util import team_match_keys, to_float

logger = logging.getLogger(__name__)


@dataclass
class VlrMatchRef:
    """Enough VLR series fields to score a rib overlay join."""

    vlr_match_id: str
    vlr_event_id: str | None
    match_date: str | None
    event_name: str | None
    team_1_id: str | None
    team_2_id: str | None
    team_1_name: str | None
    team_2_name: str | None
    team_1_keys: set[str]
    team_2_keys: set[str]


@dataclass
class JoinHit:
    """Best VLR series for one rib series (or unmatched)."""

    vlr_match_id: str | None
    vlr_event_id: str | None
    vlr_team_a_id: str | None
    vlr_team_b_id: str | None
    join_method: str
    join_score: float


def _s(value: Any) -> str | None:
    """Blank is not a join key."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _event_tokens(name: Any) -> set[str]:
    """Loose tokens so 'VCT 2026: Americas Stage 2' matches VLR event series text."""
    text = (_s(name) or "").lower()
    return {tok for tok in text.replace(":", " ").replace("-", " ").split() if len(tok) > 1}


def _load_vlr_index(repo_root: Path) -> dict[str, list[VlrMatchRef]]:
    """Index VLR matches.jsonl by project date. Missing file → empty (rib rows still parse)."""
    path = vlr_matches_jsonl_path(repo_root)
    by_date: dict[str, list[VlrMatchRef]] = {}
    if not path.exists():
        logger.warning("[rib_join] VLR matches.jsonl missing at %s", path)
        return by_date
    scanned = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            match_id = _s(obj.get("vlr_match_id"))
            if not match_id:
                continue
            detail = obj.get("detail") if isinstance(obj.get("detail"), dict) else {}
            event = detail.get("event") if isinstance(detail.get("event"), dict) else {}
            ref = VlrMatchRef(
                vlr_match_id=match_id,
                vlr_event_id=_s(obj.get("vlr_event_id") or event.get("id")),
                match_date=_s(obj.get("match_date")),
                event_name=_s(event.get("name") or obj.get("event_series")),
                team_1_id=_s(obj.get("vlr_team_1_id")),
                team_2_id=_s(obj.get("vlr_team_2_id")),
                team_1_name=_s(obj.get("team_1_name")),
                team_2_name=_s(obj.get("team_2_name")),
                team_1_keys=team_match_keys(obj.get("team_1_name")),
                team_2_keys=team_match_keys(obj.get("team_2_name")),
            )
            by_date.setdefault(ref.match_date or "", []).append(ref)
            if scanned % 2000 == 0:
                logger.info("[rib_join] VLR index progress lines=%s", scanned)
    logger.info("[rib_join] VLR index done dates=%s lines=%s", len(by_date), scanned)
    return by_date


def _team_overlap(keys: set[str], ref_keys: set[str]) -> int:
    """How many normalized name keys the two teams share."""
    if not keys or not ref_keys:
        return 0
    return len(keys & ref_keys)


def score_pair(rib: dict[str, Any], ref: VlrMatchRef) -> tuple[float, str, str | None, str | None]:
    """Date + both teams; event name breaks ties. Returns score, method, vlr team A, vlr team B."""
    team_a = rib.get("team_a") if isinstance(rib.get("team_a"), dict) else {}
    team_b = rib.get("team_b") if isinstance(rib.get("team_b"), dict) else {}
    keys_a = team_match_keys(team_a.get("name"), team_a.get("short_name"))
    keys_b = team_match_keys(team_b.get("name"), team_b.get("short_name"))
    a1 = _team_overlap(keys_a, ref.team_1_keys)
    a2 = _team_overlap(keys_a, ref.team_2_keys)
    b1 = _team_overlap(keys_b, ref.team_1_keys)
    b2 = _team_overlap(keys_b, ref.team_2_keys)
    same = min(a1, b2)
    swapped = min(a2, b1)
    if same == 0 and swapped == 0:
        return 0.0, "none", None, None
    if same >= swapped:
        team_score = float(same + b2)
        vlr_a, vlr_b = ref.team_1_id, ref.team_2_id
        method = "date+teams"
    else:
        team_score = float(swapped + b1)
        vlr_a, vlr_b = ref.team_2_id, ref.team_1_id
        method = "date+teams_swapped"
    event_overlap = len(_event_tokens(rib.get("event_name")) & _event_tokens(ref.event_name))
    score = team_score + min(event_overlap, 5) * 0.1
    if event_overlap:
        method = method + "+event"
    return score, method, vlr_a, vlr_b


def match_one(rib: dict[str, Any], by_date: dict[str, list[VlrMatchRef]]) -> JoinHit:
    """Best unique VLR series on the same project date; unmatched if score ties or is 0."""
    date_key = _s(rib.get("match_date")) or ""
    candidates = list(by_date.get(date_key) or [])
    if not date_key:
        candidates = [ref for refs in by_date.values() for ref in refs]
    scored: list[tuple[float, str, str | None, str | None, VlrMatchRef]] = []
    for ref in candidates:
        score, method, vlr_a, vlr_b = score_pair(rib, ref)
        if score <= 0:
            continue
        scored.append((score, method, vlr_a, vlr_b, ref))
    if not scored:
        return JoinHit(None, None, None, None, "unmatched", 0.0)
    scored.sort(key=lambda row: row[0], reverse=True)
    best = scored[0]
    if len(scored) > 1 and scored[1][0] == best[0]:
        return JoinHit(None, None, None, None, "ambiguous", best[0])
    ref = best[4]
    return JoinHit(ref.vlr_match_id, ref.vlr_event_id, best[2], best[3], best[1], best[0])


def build_crosswalk(repo_root: Path) -> dict[str, dict[str, Any]]:
    """rib_match_id → join fields for parse. Also used as the crosswalk fact rows."""
    logger.info("[rib_join] Start")
    by_date = _load_vlr_index(repo_root)
    path = rib_matches_jsonl_path(repo_root)
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        logger.warning("[rib_join] rib matches.jsonl missing at %s", path)
        return out
    scanned = 0
    hits = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            try:
                rib = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rib, dict):
                continue
            match_id = _s(rib.get("rib_match_id"))
            if not match_id:
                continue
            hit = match_one(rib, by_date)
            team_a = rib.get("team_a") if isinstance(rib.get("team_a"), dict) else {}
            team_b = rib.get("team_b") if isinstance(rib.get("team_b"), dict) else {}
            row = {
                "rib_match_id": match_id,
                "rib_event_id": _s(rib.get("rib_event_id")),
                "vlr_match_id": hit.vlr_match_id,
                "vlr_event_id": hit.vlr_event_id,
                "vlr_team_a_id": hit.vlr_team_a_id,
                "vlr_team_b_id": hit.vlr_team_b_id,
                "match_date": rib.get("match_date"),
                "event_name": rib.get("event_name"),
                "team_a_name": team_a.get("name"),
                "team_b_name": team_b.get("name"),
                "join_method": hit.join_method,
                "join_score": hit.join_score,
                "has_replay": bool(rib.get("has_replay")),
            }
            out[match_id] = row
            if hit.vlr_match_id:
                hits += 1
    logger.info("[rib_join] Done scanned=%s joined=%s unmatched=%s", scanned, hits, scanned - hits)
    return out


def player_lookup(repo_root: Path):
    """Reuse VLR IGN+team resolver for overlay player ids."""
    return load_player_id_lookup(repo_root)


def resolve_vlr_player(lookup, vlr_team_id: str | None, ign: str | None) -> str | None:
    """None when the VLR landings cannot map this rib IGN."""
    if lookup is None:
        return None
    return lookup.resolve(vlr_team_id, ign)


def resolve_rib_team_id(payload: dict[str, Any], side: str | None) -> str | None:
    """Map A/B (or team1/team2) onto numeric rib team id."""
    token = (side or "").strip().upper()
    team_a = payload.get("team_a") if isinstance(payload.get("team_a"), dict) else {}
    team_b = payload.get("team_b") if isinstance(payload.get("team_b"), dict) else {}
    if token in {"A", "TEAM1", "1"}:
        return _s(team_a.get("id"))
    if token in {"B", "TEAM2", "2"}:
        return _s(team_b.get("id"))
    return None


def resolve_vlr_team_id(cross: dict[str, Any] | None, side: str | None) -> str | None:
    """Map A/B onto the VLR team id chosen by the fuzzy join."""
    if not cross:
        return None
    token = (side or "").strip().upper()
    if token in {"A", "TEAM1", "1"}:
        return _s(cross.get("vlr_team_a_id"))
    if token in {"B", "TEAM2", "2"}:
        return _s(cross.get("vlr_team_b_id"))
    return None
