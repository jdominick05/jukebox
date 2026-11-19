# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import lavalink
import pytest
from jukebox.config import Config
from jukebox.models import GuildSnapshot, LoopMode, Track
from jukebox.player import GuildPlayer


class FakeLavalinkPlayer:
    def __init__(self) -> None:
        self.channel_id: int | None = None
        self.current: lavalink.AudioTrack | None = None
        self.position = 0
        self.paused = False
        self.volume = 100
        self.played: list[dict[str, Any]] = []
        self.stopped = 0

    async def play(self, track: lavalink.AudioTrack, **kwargs: Any) -> dict[str, Any]:
        self.current = track
        self.position = kwargs.get("start_time", 0)
        self.paused = kwargs.get("pause", False)
        if "volume" in kwargs:
            self.volume = kwargs["volume"]
        self.played.append({"title": track.title, "kwargs": kwargs})
        return {"paused": self.paused, "volume": self.volume}

    async def stop(self) -> None:
        self.stopped += 1
        self.current = None

    async def set_pause(self, pause: bool) -> None:
        self.paused = pause

    async def set_volume(self, volume: int) -> None:
        self.volume = volume

    async def seek(self, position: int) -> None:
        self.position = position


class FakePlayerManager:
    def __init__(self) -> None:
        self.player: FakeLavalinkPlayer | None = None

    def get(self, guild_id: int) -> FakeLavalinkPlayer | None:
        return self.player

    def create(self, guild_id: int, *, cls: Any = None) -> FakeLavalinkPlayer:
        self.player = FakeLavalinkPlayer()
        return self.player

    async def destroy(self, guild_id: int) -> None:
        self.player = None


class FakeClient:
    def __init__(self) -> None:
        self.player_manager = FakePlayerManager()


class FakeLavalink:
    def __init__(self) -> None:
        self.client = FakeClient()


class FakeDatabase:
    def __init__(self) -> None:
        self.snapshots: list[GuildSnapshot] = []

    async def save_snapshot(self, snapshot: GuildSnapshot) -> None:
        self.snapshots.append(snapshot)


@dataclass
class FakeBot:
    config: Config
    db: FakeDatabase = field(default_factory=FakeDatabase)
    lavalink: FakeLavalink = field(default_factory=FakeLavalink)

    def get_guild(self, guild_id: int) -> None:
        return None

    def get_channel(self, channel_id: int) -> None:
        return None


@pytest.fixture
def fake_bot(config: Config) -> FakeBot:
    from dataclasses import replace

    return FakeBot(config=replace(config, idle_timeout=0, empty_timeout=0))


@pytest.fixture
def player(fake_bot: FakeBot) -> GuildPlayer:
    return GuildPlayer(fake_bot, guild_id=1)  # type: ignore[arg-type]


async def test_enqueue_starts_when_idle(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    added, dropped = await player.enqueue([make_track("one"), make_track("two")])
    assert (added, dropped) == (2, 0)
    assert player.current is not None and player.current.title == "one"
    assert [track.title for track in player.queue] == ["two"]


async def test_finished_advances(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    first, second = make_track("one"), make_track("two")
    await player.enqueue([first, second])
    await player.handle_track_end(first.encoded, lavalink.EndReason.FINISHED)
    assert player.current is not None and player.current.title == "two"
    assert len(player.queue) == 0


async def test_finished_track_loop(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    first = make_track("one")
    await player.enqueue([first])
    await player.set_loop(LoopMode.TRACK)
    await player.handle_track_end(first.encoded, lavalink.EndReason.FINISHED)
    assert player.current is not None and player.current.title == "one"
    assert len(player.queue) == 0


async def test_finished_queue_loop(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    first, second = make_track("one"), make_track("two")
    await player.enqueue([first, second])
    await player.set_loop(LoopMode.QUEUE)
    await player.handle_track_end(first.encoded, lavalink.EndReason.FINISHED)
    assert player.current is not None and player.current.title == "two"
    assert [track.title for track in player.queue] == ["one"]


async def test_manual_skip_bypasses_track_loop(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    first, second = make_track("one"), make_track("two")
    await player.enqueue([first, second])
    await player.set_loop(LoopMode.TRACK)
    await player.skip()
    assert player.current is not None and player.current.title == "two"


async def test_stale_end_event_is_ignored(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    first, second = make_track("one"), make_track("two")
    await player.enqueue([first, second])
    await player.handle_track_end("something-else", lavalink.EndReason.FINISHED)
    assert player.current is not None and player.current.title == "one"
    assert len(player.queue) == 1


async def test_failures_stop_after_three(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    tracks = [make_track(f"t{i}") for i in range(4)]
    await player.enqueue(tracks)

    report = await player.handle_failure(tracks[0].encoded, "boom")
    assert report is not None and not report.stopped
    assert player.current is not None and player.current.title == "t1"

    report = await player.handle_failure(tracks[1].encoded, "boom")
    assert report is not None and not report.stopped
    assert player.current is not None and player.current.title == "t2"

    report = await player.handle_failure(tracks[2].encoded, "boom")
    assert report is not None and report.stopped
    assert player.current is None
    assert [track.title for track in player.queue] == ["t3"]


async def test_failure_for_stale_track_is_ignored(
    player: GuildPlayer, make_track: Callable[..., Track]
) -> None:
    await player.enqueue([make_track("one")])
    assert await player.handle_failure("other", "boom") is None


async def test_stop_clears_queue(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    await player.enqueue([make_track("one"), make_track("two")])
    await player.stop()
    assert player.current is None
    assert len(player.queue) == 0


async def test_volume_and_seek_are_forwarded(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    track = make_track("one")
    await player.enqueue([track])
    await player.set_volume(42)
    assert player.volume == 42
    await player.seek(12_000)
    assert player.position_ms == 12_000
    assert player._ll is not None and player._ll.volume == 42


async def test_seek_rejects_streams(player: GuildPlayer, make_track: Callable[..., Track]) -> None:
    from jukebox.errors import UserError

    await player.enqueue([make_track("live", duration_ms=0, is_stream=True)])
    with pytest.raises(UserError, match="streams"):
        await player.seek(1000)


async def test_snapshot_position_is_saved(
    player: GuildPlayer, make_track: Callable[..., Track], fake_bot: FakeBot
) -> None:
    await player.enqueue([make_track("one")])
    assert fake_bot.db.snapshots
    assert fake_bot.db.snapshots[-1].current is not None
    assert fake_bot.db.snapshots[-1].current.title == "one"
