# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest

from .harness import World

pytestmark = pytest.mark.integration


async def test_pause_resume_volume(world: World, audio) -> None:
    assert (await world.play(1, audio("tone-long.wav"))).error is None
    player = world.player(1)

    paused = await world.invoke("pause", world.interaction(1))
    assert paused.error is None
    assert player.paused is True
    assert player._ll is not None and player._ll.paused is True

    resumed = await world.invoke("resume", world.interaction(1))
    assert resumed.error is None
    assert player.paused is False
    assert player._ll is not None and player._ll.paused is False

    volume = await world.invoke("volume", world.interaction(1), 42)
    assert volume.error is None
    assert player.volume == 42
    assert player._ll is not None and player._ll.volume == 42


async def test_volume_out_of_range_is_rejected(world: World, audio) -> None:
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    player = world.player(1)

    too_high = await world.invoke("volume", world.interaction(1), 101)
    assert too_high.error is not None
    assert too_high.final_embed is not None and too_high.final_embed.title == "Could not do that"
    assert player.volume == 70

    too_low = await world.invoke("volume", world.interaction(1), -1)
    assert too_low.error is not None
    assert player.volume == 70


async def test_seek_and_out_of_range(world: World, audio) -> None:
    assert (await world.play(1, audio("tone-long.wav"))).error is None
    player = world.player(1)

    seeked = await world.invoke("seek", world.interaction(1), 1)
    assert seeked.error is None
    assert player._position_ms == 1000

    too_far = await world.invoke("seek", world.interaction(1), 999)
    assert too_far.error is not None
    assert too_far.final_embed is not None and "between 0 and" in (too_far.final_embed.description or "")

    negative = await world.invoke("seek", world.interaction(1), -1)
    assert negative.error is not None
    assert player.current is not None  # player remains usable


async def test_controls_require_same_voice_channel(world: World, audio) -> None:
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    outside = world.interaction(1, in_voice=False)
    result = await world.invoke("pause", outside)
    assert result.error is not None
    assert "Join a voice channel" in (result.final_embed.description or "")
