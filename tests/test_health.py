# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from typing import Any

import aiohttp
from jukebox.health import HealthServer


async def _get(port: int) -> tuple[int, dict[str, Any]]:
    async with (
        aiohttp.ClientSession() as session,
        session.get(f"http://127.0.0.1:{port}/healthz") as response,
    ):
        return response.status, await response.json()


async def test_health_ok() -> None:
    server = HealthServer("127.0.0.1", 0, lambda: {"status": "ok", "players": 2})
    await server.start()
    try:
        assert server.port is not None
        status, payload = await _get(server.port)
        assert status == 200
        assert payload["players"] == 2
    finally:
        await server.stop()


async def test_health_starting_returns_503() -> None:
    server = HealthServer("127.0.0.1", 0, lambda: {"status": "starting"})
    await server.start()
    try:
        assert server.port is not None
        status, payload = await _get(server.port)
        assert status == 503
        assert payload["status"] == "starting"
    finally:
        await server.stop()


async def test_provider_failure_is_contained() -> None:
    def broken() -> dict[str, Any]:
        raise RuntimeError("boom")

    server = HealthServer("127.0.0.1", 0, broken)
    await server.start()
    try:
        assert server.port is not None
        status, payload = await _get(server.port)
        assert status == 503
        assert payload["status"] == "error"
    finally:
        await server.stop()
