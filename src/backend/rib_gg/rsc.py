"""Pull JSON objects out of Next.js RSC flight text so rib.gg HTML routes become structured data."""

from __future__ import annotations

from typing import Any


def extract_json_after(text: str, key: str) -> list[Any]:
    """Find `"key":` then parse the following object/array. Skip `$undefined` refs."""
    marker = f'"{key}":'
    results: list[Any] = []
    start = 0
    while True:
        i = text.find(marker, start)
        if i < 0:
            break
        j = i + len(marker)
        while j < len(text) and text[j].isspace():
            j += 1
        if j >= len(text) or text[j] == "$":
            start = i + len(marker)
            continue
        opener = text[j]
        if opener not in "[{":
            start = j + 1
            continue
        closer = "]" if opener == "[" else "}"
        depth = 0
        in_str = False
        esc = False
        parsed = False
        for k in range(j, len(text)):
            ch = text[k]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    import json

                    try:
                        results.append(json.loads(text[j : k + 1]))
                    except json.JSONDecodeError:
                        pass
                    start = k + 1
                    parsed = True
                    break
        if not parsed:
            break
    return results


def first_maps_with(text: str, required_key: str) -> list[dict[str, Any]]:
    """First maps[] list whose items are dicts and contain required_key."""
    for payload in extract_json_after(text, "maps"):
        if not isinstance(payload, list) or not payload:
            continue
        if isinstance(payload[0], dict) and required_key in payload[0]:
            return [row for row in payload if isinstance(row, dict)]
    return []


def first_initial(text: str) -> dict[str, Any]:
    """Match page `initial` blob (teams, maps, scores). Empty dict if missing."""
    for payload in extract_json_after(text, "initial"):
        if isinstance(payload, dict) and (payload.get("maps") or payload.get("teamA")):
            return payload
    return {}
