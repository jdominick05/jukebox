# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from jukebox.health import HealthServer

from .harness import World

pytestmark = pytest.mark.integration


async def _fetch(port: int) -> tuple[int, dict[str, Any]]:
    async with (
        aiohttp.ClientSession() as session,
        session.get(f"http://127.0.0.1:{port}/healthz") as response,
    ):
        return response.status, await response.json()


async def test_healthz_is_healthy_then_unhealthy_when_node_dies(world: World, stack, service) -> None:
    server = HealthServer("127.0.0.1", 0, world.bot._health_payload)
    await server.start()
    assert server.port is not None
    try:
        status, payload = await _fetch(server.port)
        assert status == 200
        assert payload["status"] == "ok"
        assert payload["lavalink"]["available"] is True

        stack.stop_node()
        await world.wait_for(lambda: not service.available, timeout=15)

        status, payload = await _fetch(server.port)
        assert status == 503
        assert payload["status"] == "degraded"
        assert payload["lavalink"]["available"] is False
    finally:
        stack.start_node()
        await world.wait_for(lambda: service.available, timeout=30)
        await server.stop()
