# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from jukebox.db import Database
from jukebox.models import GuildSnapshot, LoopMode, Track


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "state" / "jukebox.db"))
    await database.connect()
    yield database
    await database.close()


def snapshot(
    guild_id: int,
    make_track: Callable[..., Track],
    *,
    queue_titles: tuple[str, ...] = ("two", "three"),
    current_title: str = "one",
) -> GuildSnapshot:
    return GuildSnapshot(
        guild_id=guild_id,
        voice_channel_id=111,
        text_channel_id=222,
        volume=55,
        loop_mode=LoopMode.QUEUE,
        paused=True,
        position_ms=12_345,
        current=make_track(current_title),
        queue=[make_track(title) for title in queue_titles],
    )


async def test_round_trip(db: Database, make_track: Callable[..., Track]) -> None:
    await db.save_snapshot(snapshot(1, make_track))
    await db.save_snapshot(snapshot(2, make_track, queue_titles=("only",), current_title="first"))

    loaded = await db.load_snapshots()
    assert [item.guild_id for item in loaded] == [1, 2]

    first = loaded[0]
    assert first.voice_channel_id == 111
    assert first.text_channel_id == 222
    assert first.volume == 55
    assert first.loop_mode is LoopMode.QUEUE
    assert first.paused is True
    assert first.position_ms == 12_345
    assert first.current is not None
    assert first.current.title == "one"
    assert [track.title for track in first.queue] == ["two", "three"]


async def test_save_replaces_queue(db: Database, make_track: Callable[..., Track]) -> None:
    await db.save_snapshot(snapshot(1, make_track))
    await db.save_snapshot(snapshot(1, make_track, queue_titles=("replacement",), current_title="new"))
    loaded = await db.load_snapshots()
    assert len(loaded) == 1
    assert loaded[0].current is not None
    assert loaded[0].current.title == "new"
    assert [track.title for track in loaded[0].queue] == ["replacement"]


async def test_empty_current_is_supported(db: Database, make_track: Callable[..., Track]) -> None:
    item = snapshot(3, make_track, queue_titles=())
    item.current = None
    item.position_ms = 0
    await db.save_snapshot(item)
    loaded = await db.load_snapshots()
    assert loaded[0].current is None
    assert loaded[0].queue == []


async def test_delete_guild(db: Database, make_track: Callable[..., Track]) -> None:
    await db.save_snapshot(snapshot(1, make_track))
    await db.save_snapshot(snapshot(2, make_track))
    await db.delete_guild(1)
    assert [item.guild_id for item in await db.load_snapshots()] == [2]


async def test_dj_roles(db: Database) -> None:
    await db.set_dj_role(1, 999)
    await db.set_dj_role(2, 1000)
    assert await db.load_dj_roles() == {1: 999, 2: 1000}
    await db.set_dj_role(1, None)
    assert await db.load_dj_roles() == {2: 1000}


async def test_state_survives_reconnect(tmp_path: Path, make_track: Callable[..., Track]) -> None:
    path = str(tmp_path / "persist.db")
    first = Database(path)
    await first.connect()
    await first.save_snapshot(snapshot(5, make_track))
    await first.close()

    second = Database(path)
    await second.connect()
    loaded = await second.load_snapshots()
    await second.close()
    assert loaded[0].guild_id == 5
    assert loaded[0].current is not None
