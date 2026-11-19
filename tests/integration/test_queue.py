# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest

from .harness import World
from .utils import dispatch_end

pytestmark = pytest.mark.integration


async def _add(world: World, audio, *names: str) -> None:
    for name in names:
        interaction = await world.play(1, audio(name))
        assert interaction.error is None


async def test_several_tracks_and_queue_pagination(world: World, audio) -> None:
    await _add(world, audio, "tone-a.wav")
    player = world.player(1)
    filler = await world.load_track(audio("tone-b.wav"))
    player.queue.add_many([filler] * 11)
    await player.persist()
    assert player.current is not None
    assert len(player.queue) == 11

    first = await world.invoke("queue", world.interaction(1))
    assert first.error is None
    assert first.final_embed is not None
    assert "Page 1/2" in (first.final_embed.footer.text or "")
    assert "tone-b.wav" in (first.final_embed.description or "")

    view = first.response.sent[0].view
    assert view is not None
    pager_interaction = world.interaction(1)
    await view.next.callback(pager_interaction)
    edited = pager_interaction.response.edits[-1]["embed"]
    assert "Page 2/2" in (edited.footer.text or "")
    view.stop()


async def test_remove_move_shuffle_clear(world: World, audio) -> None:
    await _add(world, audio, "tone-a.wav", "tone-b.wav", "tone-c.wav")
    player = world.player(1)
    assert [track.uri for track in player.queue] == [
        audio("tone-b.wav"),
        audio("tone-c.wav"),
    ]

    removed = await world.invoke("remove", world.interaction(1), 2)
    assert removed.error is None
    assert [track.uri for track in player.queue] == [audio("tone-b.wav")]

    await world.play(1, audio("tone-c.wav"))
    moved = await world.invoke("move", world.interaction(1), 2, 1)
    assert moved.error is None
    assert [track.uri for track in player.queue] == [
        audio("tone-c.wav"),
        audio("tone-b.wav"),
    ]

    shuffled = await world.invoke("shuffle", world.interaction(1))
    assert shuffled.error is None
    assert {track.uri for track in player.queue} == {
        audio("tone-b.wav"),
        audio("tone-c.wav"),
    }

    cleared = await world.invoke("clear", world.interaction(1))
    assert cleared.error is None
    assert len(player.queue) == 0
    assert player.current is not None  # current track is deliberately kept

    bad = await world.invoke("remove", world.interaction(1), 99)
    assert bad.error is not None
    assert bad.final_embed is not None and bad.final_embed.title == "Could not do that"


async def test_skip_and_real_track_end_advance(world: World, audio) -> None:
    await _add(world, audio, "tone-a.wav", "tone-b.wav")
    player = world.player(1)

    skipped = await world.invoke("skip", world.interaction(1))
    assert skipped.error is None
    assert player.current is not None and player.current.uri == audio("tone-b.wav")
    assert len(player.queue) == 0

    await dispatch_end(world)
    assert player.current is None
    assert len(player.queue) == 0


async def test_loop_track(world: World, audio) -> None:
    await _add(world, audio, "tone-a.wav", "tone-b.wav")
    player = world.player(1)
    original = player.current
    assert original is not None

    changed = await world.invoke("loop", world.interaction(1), "track")
    assert changed.error is None
    await dispatch_end(world)
    assert player.current is not None and player.current.uri == original.uri
    assert len(player.queue) == 1  # tone-b is still queued


async def test_loop_queue(world: World, audio) -> None:
    await _add(world, audio, "tone-a.wav", "tone-b.wav")
    player = world.player(1)
    assert player.current is not None

    changed = await world.invoke("loop", world.interaction(1), "queue")
    assert changed.error is None
    await dispatch_end(world)
    assert player.current is not None and player.current.uri == audio("tone-b.wav")
    assert [track.uri for track in player.queue] == [audio("tone-a.wav")]


async def test_loop_off_returns_to_linear_playback(world: World, audio) -> None:
    from jukebox.models import LoopMode

    await _add(world, audio, "tone-a.wav", "tone-b.wav")
    player = world.player(1)
    for mode in ("track", "queue", "off"):
        assert (await world.invoke("loop", world.interaction(1), mode)).error is None
    assert player.loop is LoopMode.OFF
    await dispatch_end(world)
    assert player.current is not None and player.current.uri == audio("tone-b.wav")
    assert len(player.queue) == 0
