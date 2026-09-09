
# Valorant-Stats overlay: recreate the httpx client with AWS API Gateway mounts.
import os as _vlr_os
from utils.rotator_mount import rotator_mounts as _vlr_rotator_mounts


def get_http_client() -> httpx.AsyncClient:
    """Same singleton as upstream, plus www.vlr.gg → AWS IP rotator."""
    global _client
    if _client is None or _client.is_closed:
        mounts = _vlr_rotator_mounts()
        _client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=int(_vlr_os.getenv("VLR_HTTP_MAX_CONN", "256")),
                max_keepalive_connections=int(_vlr_os.getenv("VLR_HTTP_KEEPALIVE", "64")),
            ),
            mounts=mounts,
        )
    return _client
