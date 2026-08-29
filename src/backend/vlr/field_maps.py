"""Remap unlabeled vlrggapi columns so JSON landings can keep both raw and warehouse names."""

from __future__ import annotations

# Why: /v2/match/details drops thead labels; VLR column order is stable on the Performance tab.
PERFORMANCE_ADV_KEYS = {
    "2": "multi_2k",
    "3": "multi_3k",
    "4": "multi_4k",
    "5": "multi_5k",
    "6": "clutch_1v1",
    "7": "clutch_1v2",
    "8": "clutch_1v3",
    "9": "clutch_1v4",
    "10": "clutch_1v5",
    "11": "econ",
    "12": "plants",
    "13": "defuses",
}

# Why: Economy tab thead is also dropped; order matches Team / Pistol / Eco / Semi / $ / Full.
ECONOMY_TEAM_KEYS = {
    "0": "team",
    "1": "pistol",
    "2": "eco",
    "3": "semi_eco",
    "4": "semi_buy",
    "5": "full_buy",
}


def remap_keys(row: dict, mapping: dict[str, str]) -> dict:
    """Keep player/team identity and rename numbered cells for warehouse facts."""
    out = {mapping.get(str(k), k): v for k, v in row.items()}
    return out
