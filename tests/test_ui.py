# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jukebox.models import LoopMode, Track, TrackQueue
from jukebox.ui import format_duration, now_playing_embed, progress_bar, queue_embed


@dataclass
class FakePlayer:
    current: Track | None
    queue: TrackQueue
    volume: int = 70
    loop: LoopMode = LoopMode.OFF
    paused: bool = False
    position_ms: int = 30_000


def test_format_duration() -> None:
    assert format_duration(0) == "0:00"
    assert format_duration(5_000) == "0:05"
    assert format_duration(65_000) == "1:05"
    assert format_duration(3_661_000) == "1:01:01"
    assert format_duration(-5) == "0:00"


def test_progress_bar_edges() -> None:
    assert len(progress_bar(0, 100_000, length=10)) == 10
    assert progress_bar(0, 100_000, length=10).startswith("🔘")
    assert progress_bar(100_000, 100_000, length=10).endswith("🔘")
    assert progress_bar(0, 0) == "🔴 Live"


def test_now_playing_embed(make_track: Callable[..., Track]) -> None:
    player = FakePlayer(current=make_track("Song"), queue=TrackQueue(10))
    embed = now_playing_embed(player, None)  # type: ignore[arg-type]
    assert embed.title == "Now playing"
    assert "Song" in embed.description
    assert len(embed.fields) == 6


def test_now_playing_empty() -> None:
    player = FakePlayer(current=None, queue=TrackQueue(10))
    embed = now_playing_embed(player, None)  # type: ignore[arg-type]
    assert embed.title == "Nothing playing"


def test_queue_embed_paginates(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(100)
    queue.add_many(make_track(f"track {i}") for i in range(25))
    player = FakePlayer(current=make_track("current"), queue=queue)
    first = queue_embed(player, None, 0, per_page=10)  # type: ignore[arg-type]
    second = queue_embed(player, None, 1, per_page=10)  # type: ignore[arg-type]
    assert "`  1.`" in first.description
    assert "track 10" not in first.description
    assert "track 10" in second.description
    assert "Page 2/3" in second.footer.text
