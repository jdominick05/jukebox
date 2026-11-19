# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""A minimal aiohttp server exposing ``/healthz`` for Docker and operators."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

__all__ = ["HealthServer"]

_log = logging.getLogger(__name__)

StatusProvider = Callable[[], dict[str, Any]]


class HealthServer:
    def __init__(self, host: str, port: int, status_provider: StatusProvider) -> None:
        self._host = host
        self._port = port
        self._status_provider = status_provider
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._bound_port: int | None = None

    @property
    def port(self) -> int | None:
        """The actual listening port (useful when configured with port 0)."""
        return self._bound_port

    async def _handle_health(self, request: web.Request) -> web.Response:
        try:
            payload = self._status_provider()
        except Exception:  # pragma: no cover - defensive; provider should not raise
            _log.exception("health status provider failed")
            payload = {"status": "error"}
        http_status = 200 if payload.get("status") == "ok" else 503
        return web.json_response(payload, status=http_status)

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/healthz", self._handle_health)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        addresses = self._runner.addresses
        if addresses:
            self._bound_port = addresses[0][1]
        _log.info("health server listening", extra={"host": self._host, "port": self._bound_port})

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
