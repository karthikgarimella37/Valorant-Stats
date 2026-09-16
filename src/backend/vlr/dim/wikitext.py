"""Parse Liquipedia Infobox / AbilityCard / Quote wikitext for agent and map catalogs."""

from __future__ import annotations

import re
from typing import Any

STAT_LINE_RE = re.compile(r"'''([^':]+)(?::)?'''\s*(.*)$")
COORD_RE = re.compile(
    r"(\d+)°\s*(\d+)['′]\s*(?:(\d+|[AZ])[\"″])?\s*([NS])[, ]+\s*"
    r"(\d+)°\s*(\d+)['′]\s*(?:(\d+|[AZ])[\"″])?\s*([EW])",
    re.I,
)


def text_or_none(value: Any) -> str | None:
    """Blank strings become null so upsert does not store empty kit fields."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def strip_wiki(value: Any) -> str | None:
    """Drop [[links]], {{templates}}, and '''bold''' from Infobox / AbilityCard text."""
    text = text_or_none(value)
    if not text:
        return None
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^}|]*\|([^}]+)\}\}", r"\1", text)
    text = re.sub(r"\{\{[^}]+\}\}", " ", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def as_int(value: Any) -> int | None:
    """Credits/orbs/uses; Free/none map to 0."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.lower() in {"free", "none", "n/a", "-"}:
        return 0
    match = re.search(r"\d+", text.replace(",", ""))
    if not match:
        return None
    return int(match.group(0))


def iter_templates(wikitext: str, name: str) -> list[str]:
    """Yield raw {{Name ...}} blocks, including nested {{ }} inside AbilityCard."""
    needle = "{{" + name.lower()
    lower = wikitext.lower()
    out: list[str] = []
    i = 0
    while True:
        i = lower.find(needle, i)
        if i < 0:
            break
        depth = 0
        j = i
        while j < len(wikitext) - 1:
            if wikitext.startswith("{{", j):
                depth += 1
                j += 2
                continue
            if wikitext.startswith("}}", j):
                depth -= 1
                j += 2
                if depth == 0:
                    out.append(wikitext[i:j])
                    i = j
                    break
                continue
            j += 1
        else:
            break
    return out


def template_fields(block: str) -> dict[str, str]:
    """Parse |key=value fields, including several on one Infobox line."""
    fields: dict[str, str] = {}
    body = block.strip()
    if body.startswith("{{"):
        body = body[2:]
    if body.endswith("}}"):
        body = body[:-2]
    extra_lines: list[str] = []
    for raw_line in body.splitlines()[1:]:
        line = raw_line.strip()
        if not line.startswith("|"):
            if line:
                extra_lines.append(line)
            continue
        for part in line[1:].split("|"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key.strip().lower()] = value.strip()
    if extra_lines:
        fields["_extra_lines"] = "\n".join(extra_lines)
    return fields


def extra_stat_lines(raw: str | None) -> dict[str, str]:
    """Turn '''Windup:''' 1.25 s style AbilityCard lines into a stats map."""
    out: dict[str, str] = {}
    if not raw:
        return out
    for line in raw.splitlines():
        match = STAT_LINE_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1).strip().lower().replace(" ", "_")
        value = strip_wiki(match.group(2)) or match.group(2).strip()
        if key and value:
            out[key] = value
    return out


def dms_to_decimal(deg: str, minutes: str, seconds: str | None, hemi: str) -> float:
    """Convert lore/DMS coordinates; A/Z seconds count as 0."""
    sec_raw = (seconds or "0").upper()
    sec = 0.0 if sec_raw in {"A", "Z"} else float(sec_raw)
    value = float(deg) + float(minutes) / 60.0 + sec / 3600.0
    if hemi.upper() in {"S", "W"}:
        value = -value
    return value


def parse_lat_lon(raw: str | None) -> tuple[float | None, float | None]:
    """Read the first DMS pair from Liquipedia / valorant-api coordinate text."""
    text = text_or_none(raw)
    if not text:
        return None, None
    match = COORD_RE.search(text.replace("\n", " "))
    if not match:
        return None, None
    lat = dms_to_decimal(match.group(1), match.group(2), match.group(3), match.group(4))
    lon = dms_to_decimal(match.group(5), match.group(6), match.group(7), match.group(8))
    return lat, lon


def earth_from_text(*parts: str | None) -> str | None:
    """Alpha Earth / Omega Earth from location or Infobox earth=."""
    blob = " ".join(p for p in parts if p)
    lower = blob.lower()
    if "omega earth" in lower or "omegaearth" in lower:
        return "Omega Earth"
    if "alpha earth" in lower or "alphaearth" in lower:
        return "Alpha Earth"
    return None


def quote_from_wikitext(wikitext: str) -> str | None:
    """Official map blurb from {{Quote|...}} when present."""
    for block in iter_templates(wikitext, "Quote"):
        body = block.strip()
        if body.startswith("{{"):
            body = body[2:]
        if body.endswith("}}"):
            body = body[:-2]
        parts = [p.strip() for p in body.split("|")]
        texts = [p for p in parts[1:] if p and "=" not in p]
        if texts:
            return strip_wiki(texts[0])
    return None
