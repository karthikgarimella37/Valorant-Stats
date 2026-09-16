"""Requests sessions that leave via AWS API Gateway. Catalog APIs must not use the host IP."""

from __future__ import annotations

import logging

import requests

from backend.api_connectors.ip_rotator_gateway import (
    VlrIpRotator,
    catalog_rotator_regions,
    ip_rotator_enabled,
)

logger = logging.getLogger(__name__)


class SiteBoundSession(requests.Session):
    """Refuse any URL that is not on the rotator-mounted site prefix."""

    def __init__(self, allowed_prefix: str) -> None:
        super().__init__()
        self.allowed_prefix = allowed_prefix.rstrip("/")

    def request(self, method: str, url: str, *args, **kwargs):  # type: ignore[override]
        if not str(url).startswith(self.allowed_prefix):
            raise RuntimeError(
                f"Refusing {url!r}: catalog HTTP must stay on rotator site {self.allowed_prefix}"
            )
        return super().request(method, url, *args, **kwargs)


def rotating_session(site: str, headers: dict[str, str] | None = None) -> SiteBoundSession:
    """Open a session whose outbound IP is AWS, never the laptop / Dagster host."""
    if not ip_rotator_enabled():
        raise RuntimeError(
            "VLR_USE_IP_ROTATOR must be 1. Catalog calls cannot use the host IP. "
            "Same rule as www.vlr.gg: AWS API Gateway only."
        )
    prefix = site.rstrip("/")
    session = SiteBoundSession(prefix)
    if headers:
        session.headers.update(headers)
    regions = catalog_rotator_regions()
    mounted = VlrIpRotator.mount(session, prefix, regions=regions)
    if not mounted:
        raise RuntimeError(
            f"AWS IP rotator did not mount for {prefix}. Refusing to send from the host IP."
        )
    logger.info("[rotator] Catalog session site=%s regions=%s (AWS IPs, not host)", prefix, regions)
    return session
