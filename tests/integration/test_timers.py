# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from dataclasses import replace

import pytest
from jukebox import player as player_module

from .harness import World

pytestmark = pytest.mark.integration


@pytest.fixture
def frozen_timer(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(player_module, "_sleep", fake_sleep)
    return sleeps


async def test_idle_timer_disconnects_without_real_sleep(
    world: World, audio, frozen_timer: list[float]
) -> None:
    world.bot.config = replace(world.bot.config, idle_timeout=300, empty_timeout=0)
    player = world.bot.create_player(1)
    player.voice_channel_id = world.voice(1).id
    player.text_channel_id = world.text(1).id

    player._start_idle_timer()
    assert player._idle_task is not None
    await player._idle_task

    assert frozen_timer == [300]
    assert player.voice_channel_id is None
    assert any(
        message.embed is not None and "inactivity" in (message.embed.description or "")
        for message in world.text(1).messages
    )


async def test_empty_channel_timer_disconnects_and_clears(
    world: World, audio, frozen_timer: list[float]
) -> None:
    world.bot.config = replace(world.bot.config, idle_timeout=0, empty_timeout=30)
    player = world.bot.create_player(1)
    player.voice_channel_id = world.voice(1).id
    player.text_channel_id = world.text(1).id
    track = await world.load_track(audio("tone-a.wav"))
    player.queue.add(track)

    world.voice(1).members = [world.guild(1).me]
    player.refresh_empty_timer()
    assert player._empty_task is not None
    await player._empty_task

    assert frozen_timer == [30]
    assert player.voice_channel_id is None
    assert len(player.queue) == 0
    assert any(
        message.embed is not None and "empty" in (message.embed.description or "")
        for message in world.text(1).messages
    )


async def test_empty_timer_is_not_scheduled_when_a_human_is_present(
    world: World, audio, frozen_timer: list[float]
) -> None:
    world.bot.config = replace(world.bot.config, idle_timeout=0, empty_timeout=30)
    player = world.bot.create_player(1)
    player.voice_channel_id = world.voice(1).id
    player.text_channel_id = world.text(1).id

    player.refresh_empty_timer()
    assert player._empty_task is None
    assert frozen_timer == []
    assert player.voice_channel_id == world.voice(1).id
