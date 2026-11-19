# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest

from .harness import World

pytestmark = pytest.mark.integration


async def test_two_guilds_are_fully_isolated(world_two: World, audio) -> None:
    world = world_two
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    assert (await world.play(2, audio("tone-b.wav"))).error is None

    one = world.player(1)
    two = world.player(2)
    assert one.current is not None and one.current.uri == audio("tone-a.wav")
    assert two.current is not None and two.current.uri == audio("tone-b.wav")

    assert (await world.play(1, audio("tone-c.wav"))).error is None
    assert [track.uri for track in one.queue] == [audio("tone-c.wav")]
    assert len(two.queue) == 0

    assert (await world.invoke("volume", world.interaction(1), 20)).error is None
    assert (await world.invoke("loop", world.interaction(1), "track")).error is None
    assert one.volume == 20
    assert two.volume == 70
    assert one.loop.value == "track"
    assert two.loop.value == "off"

    # Per-guild text channels receive their own notifications only.
    world.text(1).messages.clear()
    world.text(2).messages.clear()
    await one.notify(content="only guild one")
    assert [message.content for message in world.text(1).messages] == ["only guild one"]
    assert world.text(2).messages == []


async def test_dj_role_denies_then_allows(world_two: World, audio) -> None:
    world = world_two
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    world.bot.dj_roles[1] = 5001

    denied = await world.invoke("pause", world.interaction(1))
    assert denied.error is not None
    assert "DJ" in (denied.final_embed.description or "")
    assert world.player(1).paused is False

    member = world.guild(1).members[1001]
    member.roles.append(world.guild(1).roles[5001])

    allowed = await world.invoke("pause", world.interaction(1))
    assert allowed.error is None
    assert world.player(1).paused is True


async def test_manage_server_bypasses_dj_role(world_two: World, audio) -> None:
    world = world_two
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    world.bot.dj_roles[1] = 5001
    world.guild(1).members[1001].guild_permissions.manage_guild = True

    allowed = await world.invoke("pause", world.interaction(1))
    assert allowed.error is None
    assert world.player(1).paused is True


async def test_dj_role_from_another_guild_does_not_leak(world_two: World, audio) -> None:
    world = world_two
    assert (await world.play(2, audio("tone-b.wav"))).error is None
    world.bot.dj_roles[1] = 5001  # only guild 1 is restricted

    allowed = await world.invoke("pause", world.interaction(2))
    assert allowed.error is None
    assert world.player(2).paused is True
