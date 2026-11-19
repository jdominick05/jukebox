# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import random
from collections.abc import Callable

import pytest
from jukebox.models import QueueFullError, Track, TrackQueue


def test_queue_is_fifo(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(10)
    queue.add(make_track("one"))
    queue.add(make_track("two"))
    assert len(queue) == 2
    assert queue.pop_next().title == "one"  # type: ignore[union-attr]
    assert queue.pop_next().title == "two"  # type: ignore[union-attr]
    assert queue.pop_next() is None


def test_queue_limit(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(2)
    queue.add(make_track("one"))
    queue.add(make_track("two"))
    with pytest.raises(QueueFullError):
        queue.add(make_track("three"))
    assert len(queue) == 2


def test_add_many_reports_dropped(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(3)
    added, dropped = queue.add_many(make_track(f"t{i}") for i in range(5))
    assert (added, dropped) == (3, 2)
    assert [track.title for track in queue] == ["t0", "t1", "t2"]


def test_remove_and_move(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(10)
    queue.add_many(make_track(f"t{i}") for i in range(4))
    removed = queue.remove(1)
    assert removed.title == "t1"
    queue.move(2, 0)
    assert [track.title for track in queue] == ["t3", "t0", "t2"]


def test_remove_out_of_range(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(10)
    queue.add(make_track("one"))
    with pytest.raises(IndexError):
        queue.remove(1)
    with pytest.raises(IndexError):
        queue.move(0, 5)


def test_shuffle_keeps_members(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(10)
    queue.add_many(make_track(f"t{i}") for i in range(6))
    before = {track.title for track in queue}
    queue.shuffle(random.Random(1234))
    assert {track.title for track in queue} == before
    assert len(queue) == 6


def test_replace_truncates(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(2)
    queue.replace(make_track(f"t{i}") for i in range(4))
    assert [track.title for track in queue] == ["t0", "t1"]


def test_clear(make_track: Callable[..., Track]) -> None:
    queue = TrackQueue(10)
    queue.add(make_track("one"))
    queue.clear()
    assert not queue
    assert queue.as_list() == []
