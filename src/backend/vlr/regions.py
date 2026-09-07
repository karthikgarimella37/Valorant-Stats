"""Two region grains: VCT circuit vs local ranking code. Never store both in one column."""

from __future__ import annotations

from typing import Literal

# VCT international circuits (event/league grain).
VCT_REGIONS: tuple[tuple[str, str], ...] = (
    ("americas", "Americas"),
    ("emea", "EMEA"),
    ("pacific", "Pacific"),
    ("china", "China"),
)

# VLR local / ranking codes (team/country/challengers grain).
LOCAL_REGIONS: tuple[tuple[str, str], ...] = (
    ("na", "North America"),
    ("eu", "Europe"),
    ("br", "Brazil"),
    ("ap", "Asia Pacific"),
    ("kr", "Korea"),
    ("ch", "China"),
    ("jp", "Japan"),
    ("lan", "Latin America North"),
    ("las", "Latin America South"),
    ("oce", "Oceania"),
    ("mn", "MENA"),
    ("gc", "Game Changers"),
)

# VLR /v2/rankings query params that are not the canonical local code.
RANKING_API_ALIASES: dict[str, str] = {
    "cn": "ch",
    "la-n": "lan",
    "la-s": "las",
    "lan": "lan",
    "las": "las",
}

# Local code → VCT circuit. gc has no single circuit.
LOCAL_TO_VCT: dict[str, str] = {
    "na": "americas",
    "br": "americas",
    "lan": "americas",
    "las": "americas",
    "eu": "emea",
    "mn": "emea",
    "ap": "pacific",
    "kr": "pacific",
    "jp": "pacific",
    "oce": "pacific",
    "ch": "china",
}

RegionKind = Literal["vct", "local"]

_VCT_CODES = {code for code, _ in VCT_REGIONS}
_LOCAL_CODES = {code for code, _ in LOCAL_REGIONS}


def normalize_region_code(raw: str | None) -> tuple[RegionKind, str] | None:
    """Map a VLR string to exactly one grain so americas and na never share a column."""
    if raw is None:
        return None
    code = str(raw).strip().lower().replace(" ", "")
    if not code:
        return None
    if code in _VCT_CODES:
        return "vct", code
    aliased = RANKING_API_ALIASES.get(code, code)
    if aliased in _LOCAL_CODES:
        return "local", aliased
    return None


def infer_vct_region_from_text(*parts: str | None) -> str | None:
    """Read Americas/EMEA/Pacific/China from a VCT title so list `region=br` is not used."""
    blob = " ".join(p for p in parts if p).lower()
    if not blob:
        return None
    if "america" in blob:
        return "americas"
    if "emea" in blob or "europe" in blob:
        return "emea"
    if "pacific" in blob:
        return "pacific"
    if "china" in blob:
        return "china"
    return None


def split_event_region(raw: str | None) -> tuple[str | None, str | None]:
    """Return (vct_region_code, region_code) with at most one side set."""
    parsed = normalize_region_code(raw)
    if parsed is None:
        return None, None
    kind, code = parsed
    if kind == "vct":
        return code, None
    return None, code


def vct_for_local(region_code: str | None) -> str | None:
    """Circuit for a local ranking code (join path, not a second event region)."""
    if not region_code:
        return None
    return LOCAL_TO_VCT.get(region_code)
