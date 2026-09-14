
# Valorant-Stats overlay: header socials (e.g. @vorazune) + team ids from /team/{id}/ hrefs.
import re as _vs_re

_VS_TEAM_HREF_RE = _vs_re.compile(r"/team/(\d+)")
_VS_ORIG_PARSE_SOCIAL_LINKS = _parse_social_links
_VS_ORIG_PARSE_TEAMS = _parse_teams


def _parse_social_links(html: HTMLParser) -> list[dict]:
    """Keep a.social plus player-header links (twitter/x/twitch), skip vlr.gg chrome."""
    links = _VS_ORIG_PARSE_SOCIAL_LINKS(html)
    seen = {(str(item.get("url") or "").strip().lower().rstrip("/")) for item in links}
    header = html.css_first(".player-header") or html
    for anchor in header.css("a"):
        href = (anchor.attributes.get("href") or "").strip()
        if not href.startswith("http"):
            continue
        lower = href.lower()
        if "vlrdotgg" in lower or "discord.com/invite/vlr" in lower:
            continue
        key = lower.rstrip("/")
        if key in seen:
            continue
        platform = infer_platform(href)
        text = anchor.text(strip=True)
        if platform == "other" and text.startswith("@"):
            platform = "twitter"
        if platform == "other":
            continue
        links.append({"platform": platform, "url": href})
        seen.add(key)
    return links


def _parse_teams(html: HTMLParser) -> tuple[dict, list[dict]]:
    """Same current/past split, plus vlr team id from the module-item href."""
    current_team, past_teams = _VS_ORIG_PARSE_TEAMS(html)
    container = html.css_first(".player-summary-container-1")
    ids: list[str | None] = []
    if container:
        for item in container.css(".wf-module-item"):
            href = item.attributes.get("href") or ""
            match = _VS_TEAM_HREF_RE.search(href)
            ids.append(match.group(1) if match else None)
    idx = 0
    if current_team.get("name") and idx < len(ids):
        if ids[idx]:
            current_team["id"] = ids[idx]
        idx += 1
    for past in past_teams:
        if idx >= len(ids):
            break
        if ids[idx]:
            past["id"] = ids[idx]
        idx += 1
    return current_team, past_teams
