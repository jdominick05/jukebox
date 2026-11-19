# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest

from .harness import World

pytestmark = pytest.mark.integration


async def test_node_restart_recovers_without_fake_playback_state(world: World, stack, service, audio) -> None:
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    assert (await world.play(1, audio("tone-b.wav"))).error is None
    player = world.player(1)
    assert player.current is not None
    assert len(player.queue) == 1

    stack.stop_node()
    await world.wait_for(lambda: not service.available, timeout=15)
    assert player.current is not None  # bot state is still the old track until NodeReady

    stack.start_node()
    await world.wait_for(lambda: service.available, timeout=30)
    # NodeReadyEvent(resumed=False) must reset the stale current track but keep
    # the queue, otherwise /play would silently queue behind a dead track.
    await world.wait_for(lambda: player.current is None, timeout=10)
    assert [track.uri for track in player.queue] == [audio("tone-b.wav")]

    resumed = await world.play(1, audio("tone-c.wav"))
    assert resumed.error is None
    assert player.current is not None and player.current.uri == audio("tone-b.wav")
    assert [track.uri for track in player.queue] == [audio("tone-c.wav")]
