# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- build stage
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt ./
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

# -------------------------------------------------------------- runtime stage
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:${PATH}"

RUN groupadd --system --gid 10001 jukebox \
    && useradd --system --uid 10001 --gid jukebox --home-dir /app --shell /usr/sbin/nologin jukebox

WORKDIR /app
COPY --from=builder /venv /venv
COPY jukebox ./jukebox

RUN mkdir -p /data && chown -R jukebox:jukebox /app /data

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import os, sys, urllib.request; port = os.environ.get('HEALTH_PORT', '8080'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + port + '/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "jukebox"]
