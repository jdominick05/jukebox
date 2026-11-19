# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest

from .harness import World
from .utils import dispatch_exception

pytestmark = pytest.mark.integration


def _assert_user_error(interaction, text: str) -> None:
    assert interaction.error is not None, "expected a user-facing error"
    assert interaction.final_embed is not None
    assert interaction.final_embed.title == "Could not do that"
    assert text in (interaction.final_embed.description or "")


async def test_dead_url_is_reported_and_player_survives(world: World, audio) -> None:
    dead = await world.play(1, audio("missing-file.wav"))
    _assert_user_error(dead, "No matches found")

    good = await world.play(1, audio("tone-a.wav"))
    assert good.error is None
    assert world.player(1).current is not None


async def test_unsupported_url_is_rejected_before_lavalink(world: World) -> None:
    result = await world.play(1, "https://example.com/not-an-audio-file")
    _assert_user_error(result, "not from a supported source")


async def test_disabled_source_is_reported(world: World) -> None:
    result = await world.play(1, "https://soundcloud.com/artist/track")
    _assert_user_error(result, "SoundCloud")
    assert "disabled" in (result.final_embed.description or "")


async def test_empty_search_is_rejected(world: World) -> None:
    result = await world.play(1, "   ")
    _assert_user_error(result, "track name")


async def test_track_exception_skips_and_notifies(world: World, audio) -> None:
    assert (await world.play(1, audio("tone-a.wav"))).error is None
    assert (await world.play(1, audio("tone-b.wav"))).error is None
    player = world.player(1)
    first = player.current
    assert first is not None

    await dispatch_exception(world, message="decoder exploded")
    assert player.current is not None and player.current.uri == audio("tone-b.wav")

    await world.wait_for(
        lambda: any(
            message.embed is not None and "Skipping" in (message.embed.description or "")
            for message in world.text(1).messages
        ),
        timeout=4,
    )
    notice = [
        message.embed
        for message in world.text(1).messages
        if message.embed is not None and "Skipping" in (message.embed.description or "")
    ][-1]
    assert "decoder exploded" in (notice.description or "")
    assert len(player.queue) == 0
