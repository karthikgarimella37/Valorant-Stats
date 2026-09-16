"""HTTP client for valorant-api.com via AWS IP rotator. Static catalogs only."""

from __future__ import annotations

import logging
from typing import Any

from backend.api_connectors.rotating_http import rotating_session

logger = logging.getLogger(__name__)

BASE_URL = "https://valorant-api.com"
SITE = "https://valorant-api.com"


class ValorantApiConnector:
    """Fetch playable-agent kit and map radar data. Not used for matches."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = rotating_session(SITE, headers={"Accept": "application/json"})

    def _get_data(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """One catalog GET through AWS; refuse host IP."""
        url = f"{BASE_URL}{path}"
        logger.info("[valorant-api] GET %s params=%s via_rotator=1", url, params or {})
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"valorant-api.com {path} did not return data[]")
        return [row for row in rows if isinstance(row, dict)]

    def get_playable_agents(self) -> list[dict[str, Any]]:
        """One GET for every playable agent so dim_agents can upsert the full roster."""
        rows = self._get_data("/v1/agents", {"isPlayableCharacter": "true"})
        playable = [row for row in rows if row.get("isPlayableCharacter", True)]
        logger.info("[valorant-api] Agents fetched=%s", len(playable))
        return playable

    def get_maps(self) -> list[dict[str, Any]]:
        """Map list with radar multipliers, callout x/y, coordinates, official blurb."""
        rows = self._get_data("/v1/maps")
        logger.info("[valorant-api] Maps fetched=%s", len(rows))
        return rows
