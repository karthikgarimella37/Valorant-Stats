"""Route vlrggapi's httpx client through AWS API Gateway so scrapes leave from AWS IPs."""

from __future__ import annotations

import atexit
import logging
import os
import random
from ipaddress import IPv4Address

import httpx

logger = logging.getLogger(__name__)

VLR_SITE = "https://www.vlr.gg"
_MAX_IPV4 = (1 << 32) - 1
_gateway = None
_endpoints: list[str] = []


def _enabled() -> bool:
    flag = os.getenv("VLR_USE_IP_ROTATOR", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _regions() -> list[str] | None:
    """Split VLR_IP_ROTATOR_REGIONS; never treat a comma list as AWS_DEFAULT_REGION."""
    raw = os.getenv("VLR_IP_ROTATOR_REGIONS", "").strip().strip("\"'")
    if raw:
        return [part.strip().strip("\"'") for part in raw.split(",") if part.strip().strip("\"'")]
    default = os.getenv("AWS_DEFAULT_REGION", "").strip().strip("\"'")
    if "," in default:
        return [part.strip().strip("\"'") for part in default.split(",") if part.strip().strip("\"'")]
    return [default] if default else None


def _http_limits() -> httpx.Limits:
    """Allow many in-flight scrapes; 20 connections made match details crawl."""
    return httpx.Limits(
        max_connections=int(os.getenv("VLR_HTTP_MAX_CONN", "32")),
        max_keepalive_connections=int(os.getenv("VLR_HTTP_KEEPALIVE", "16")),
    )


class VlrGatewayTransport(httpx.AsyncHTTPTransport):
    """Rewrite www.vlr.gg URLs onto a random API Gateway endpoint."""

    def __init__(self, endpoints: list[str], **kwargs):
        kwargs.setdefault("limits", _http_limits())
        super().__init__(**kwargs)
        self.endpoints = endpoints

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        endpoint = random.choice(self.endpoints)
        raw_path = request.url.raw_path.decode()
        new_url = httpx.URL(f"https://{endpoint}/ProxyStage{raw_path}")
        headers = request.headers.copy()
        headers["host"] = endpoint
        headers.pop("x-forwarded-for", None)
        headers["x-my-x-forwarded-for"] = str(IPv4Address(random.randint(0, _MAX_IPV4)))
        forwarded = httpx.Request(
            request.method,
            new_url,
            headers=headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return await super().handle_async_request(forwarded)


def start_gateway() -> list[str]:
    """Create API Gateway proxies at container boot."""
    global _gateway, _endpoints
    if _endpoints:
        return _endpoints
    if not _enabled():
        logger.info("[vlrggapi_rotator] Off — set VLR_USE_IP_ROTATOR=1 to use AWS IPs")
        return []
    access_key_id = os.getenv("VLR_AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("VLR_AWS_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
    if not access_key_id or not access_key_secret:
        raise RuntimeError(
            "VLR_USE_IP_ROTATOR=1 but AWS keys are missing in the vlrggapi container. "
            "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in src/config/.env"
        )
    from requests_ip_rotator import ApiGateway

    kwargs: dict = {
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "verbose": os.getenv("VLR_IP_ROTATOR_VERBOSE", "1") not in ("0", "false", "False"),
    }
    regions = _regions()
    if regions:
        kwargs["regions"] = regions
    logger.info("[vlrggapi_rotator] Starting API Gateway for %s regions=%s", VLR_SITE, regions or "DEFAULT")
    _gateway = ApiGateway(VLR_SITE, **kwargs)
    _endpoints = list(_gateway.start() or [])
    atexit.register(_shutdown)
    print(f"[vlrggapi_rotator] Ready endpoints={len(_endpoints)}", flush=True)
    logger.info("[vlrggapi_rotator] Ready endpoints=%s", len(_endpoints))
    if not _endpoints:
        raise RuntimeError(
            "vlrggapi rotator created 0 AWS endpoints. "
            "IAM needs CreateRestApi/GetRestApis. Set VLR_IP_ROTATOR_REGIONS=us-east-1. "
            "Refusing to scrape vlr.gg from the container IP."
        )
    return _endpoints


def _shutdown() -> None:
    global _gateway, _endpoints
    if _gateway is None:
        return
    try:
        _gateway.shutdown()
    except RuntimeError:
        logger.warning("[vlrggapi_rotator] Shutdown skipped (interpreter exiting)")
    except Exception:
        logger.exception("[vlrggapi_rotator] Shutdown failed")
    _gateway = None
    _endpoints = []


def rotator_mounts() -> dict[str, httpx.AsyncBaseTransport] | None:
    """httpx mounts so only www.vlr.gg goes through AWS IPs."""
    endpoints = start_gateway()
    if not endpoints:
        return None
    return {VLR_SITE: VlrGatewayTransport(endpoints)}


if _enabled():
    try:
        start_gateway()
    except Exception:
        logger.exception("[vlrggapi_rotator] Failed to start; scrapes will use the container IP")
