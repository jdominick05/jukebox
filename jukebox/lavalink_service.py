# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""A thin, resilient wrapper around the Lavalink client library."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import lavalink

from .config import LavalinkConfig
from .errors import UserError

__all__ = ["LavalinkService"]

_log = logging.getLogger(__name__)


class LavalinkService:
    """Owns the Lavalink client and the connection to the audio node.

    The underlying library reconnects its WebSocket with exponential backoff
    (``lavalink.transport.ExponentialBackoff``); this class adds session
    resuming, a readiness signal for startup restoration, and error
    translation for command handlers.
    """

    def __init__(self, config: LavalinkConfig, user_id: int) -> None:
        self.config = config
        self.client = lavalink.Client(
            user_id,
            connect_back=True,
            request_timeout=aiohttp.ClientTimeout(total=20),
        )
        self._first_ready = asyncio.Event()
        self._started = False

    @property
    def available(self) -> bool:
        return any(node.available for node in self.client.node_manager.nodes)

    @property
    def nodes(self) -> list[dict[str, Any]]:
        return [
            {
                "name": node.name,
                "region": node.region,
                "available": node.available,
                "players": len(node.players),
            }
            for node in self.client.node_manager.nodes
        ]

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.client.add_event_hook(self._on_node_ready, event=lavalink.NodeReadyEvent)
        self.client.add_event_hook(self._on_node_disconnected, event=lavalink.NodeDisconnectedEvent)
        self.client.add_node(
            self.config.host,
            self.config.port,
            self.config.password,
            self.config.region,
            self.config.name,
            self.config.secure,
        )
        _log.info(
            "lavalink node configured",
            extra={"host": self.config.host, "port": self.config.port, "secure": self.config.secure},
        )

    async def _on_node_ready(self, event: lavalink.NodeReadyEvent) -> None:
        node = event.node
        self._first_ready.set()
        _log.info(
            "lavalink node ready",
            extra={"node": node.name, "session_id": event.session_id, "resumed": event.resumed},
        )
        try:
            await node.update_session(resuming=True, timeout=self.config.resume_timeout)
        except Exception:
            # A node without session resuming still works; it only means a
            # brief node outage drops the current track.
            _log.exception("could not enable session resuming", extra={"node": node.name})

    async def _on_node_disconnected(self, event: lavalink.NodeDisconnectedEvent) -> None:
        _log.warning(
            "lavalink node disconnected; the client will retry with backoff",
            extra={"node": event.node.name, "code": event.code, "reason": event.reason},
        )

    async def wait_ready(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._first_ready.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    async def get_tracks(self, identifier: str) -> lavalink.LoadResult:
        """Load a track/playlist/search, translating transport failures."""
        if not self.available:
            raise UserError(
                "The audio node is not connected right now.",
                hint="Try again in a moment; the bot reconnects automatically.",
            )
        try:
            return await self.client.get_tracks(identifier)
        except (lavalink.ClientError, lavalink.RequestError, aiohttp.ClientError, TimeoutError) as error:
            _log.warning("lavalink load failed", extra={"identifier": identifier[:200]}, exc_info=error)
            raise UserError(
                "The audio node did not answer the request.",
                hint="Try again in a moment; if it keeps failing, check the Lavalink logs.",
            ) from error

    async def close(self) -> None:
        if not self._started:
            return
        try:
            await self.client.close()
        except Exception:
            _log.exception("error while closing the lavalink client")
        finally:
            self._started = False
