# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import asyncio

import lavalink
import pytest

from .harness import World

pytestmark = pytest.mark.integration


async def test_play_direct_url_then_nowplaying(world: World, audio) -> None:
    url = audio("tone-a.wav")
    interaction = await world.play(1, url)
    assert interaction.error is None
    assert interaction.final_embed is not None
    assert interaction.final_embed.title == "Now playing"

    player = world.player(1)
    assert player.current is not None
    assert player.current.uri == url
    await world.wait_for(lambda: player._ll is not None and player._ll.current is not None)

    now = await world.invoke("nowplaying", world.interaction(1))
    assert now.error is None
    assert now.final_embed is not None
    assert "tone-a.wav" in (now.final_embed.description or "")


async def test_lavalink_starts_a_track_but_cannot_advance_without_voice(
    world: World, audio, service: lavalink.Client
) -> None:
    """Documents the boundary the rest of the suite is designed around.

    A Lavalink player without a Discord voice connection emits TrackStart, then
    never moves the position and never emits TrackEnd.  If a future Lavalink
    changes that, this test fails and the suite can start relying on real end
    events instead of dispatching them.
    """
    ends: list[lavalink.TrackEndEvent] = []

    async def on_end(event: lavalink.TrackEndEvent) -> None:
        ends.append(event)

    service.client.add_event_hook(on_end, event=lavalink.TrackEndEvent)
    try:
        interaction = await world.play(1, audio("tone-a.wav"))
        assert interaction.error is None
        player = world.player(1)
        await world.wait_for(lambda: player._ll is not None and player._ll.current is not None)
        await asyncio.sleep(0.9)
        assert ends == []
        assert player.current is not None
        assert player._ll is not None and player._ll.current is not None
    finally:
        service.client.remove_event_hooks(hooks=[on_end])
