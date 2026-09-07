# Overlay official vlrggapi so scrapes to www.vlr.gg leave via AWS API Gateway IPs.
FROM ghcr.io/axsddlr/vlrggapi:latest

USER root
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
RUN uv pip install --system --no-cache requests-ip-rotator boto3
COPY docker/vlrggapi/rotator_mount.py /vlrggapi/utils/rotator_mount.py
COPY docker/vlrggapi/rotator_patch.py /tmp/rotator_patch.py
RUN cat /tmp/rotator_patch.py >> /vlrggapi/utils/http_client.py \
    && chown vlrggapi:vlrggapi /vlrggapi/utils/rotator_mount.py /vlrggapi/utils/http_client.py \
    && rm /tmp/rotator_patch.py

USER vlrggapi
