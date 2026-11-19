# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Event helpers for the integration tests.

Lavalink cannot emit TrackEnd without a real Discord voice connection (proved
by test_playback.py::test_lavalink_starts_a_track_but_cannot_advance_without_voice).
These helpers dispatch genuine ``lavalink`` event objects through the real
client dispatcher so the bot's real handlers run.
"""

from __future__ import annotations

import lavalink

from .harness import World


async def dispatch_end(
    world: World,
    guild_id: int = 1,
    reason: lavalink.EndReason = lavalink.EndReason.FINISHED,
) -> None:
    player = world.player(guild_id)
    ll = player._ll
    assert ll is not None
    if player.current is not None and (ll.current is None or ll.current.track != player.current.encoded):
        await world.wait_for(
            lambda: ll.current is not None and ll.current.track == player.current.encoded,
            timeout=4,
        )
    assert ll.current is not None, "no live Lavalink track to end"
    old = player.current
    starts: list[lavalink.TrackStartEvent] = []

    async def on_start(event: lavalink.TrackStartEvent) -> None:
        starts.append(event)

    world.service.client.add_event_hook(on_start, event=lavalink.TrackStartEvent)
    try:
        world.service.client._dispatch_event(lavalink.TrackEndEvent(ll, ll.current, reason))
        await world.wait_for(
            lambda: len(starts) > 0 or player.current is None or player.current is not old,
            timeout=4,
        )
    finally:
        world.service.client.remove_event_hooks(hooks=[on_start])


async def dispatch_exception(world: World, guild_id: int = 1, message: str = "boom") -> None:
    player = world.player(guild_id)
    ll = player._ll
    assert ll is not None and ll.current is not None
    old = player.current
    world.service.client._dispatch_event(
        lavalink.TrackExceptionEvent(
            ll,
            ll.current,
            message,
            lavalink.Severity.COMMON,
            "test-cause",
            "",
        )
    )
    await world.wait_for(
        lambda: player.current is None or player.current is not old,
        timeout=4,
    )
