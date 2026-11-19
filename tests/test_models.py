# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from collections.abc import Callable

import lavalink
import pytest
from jukebox.models import LoopMode, Track


def test_track_json_round_trip(make_track: Callable[..., Track]) -> None:
    track = make_track("Song", requester_id=42)
    restored = Track.from_json(track.to_json())
    assert restored == track
    assert restored.raw["encoded"] == track.encoded
    assert restored.requester_id == 42


def test_track_from_lavalink() -> None:
    audio = lavalink.AudioTrack(
        {
            "encoded": "abc",
            "info": {
                "identifier": "abc",
                "isSeekable": True,
                "author": "Artist",
                "length": 123_000,
                "isStream": False,
                "title": "Title",
                "uri": "https://example.com/v",
                "artworkUrl": "https://example.com/a.jpg",
                "sourceName": "youtube",
            },
        },
        requester=7,
    )
    track = Track.from_lavalink(audio, 7)
    assert track.encoded == "abc"
    assert track.title == "Title"
    assert track.duration_ms == 123_000
    assert track.requester_id == 7
    assert track.raw["encoded"] == "abc"


def test_track_without_encoded_payload_is_rejected() -> None:
    with pytest.raises(ValueError, match="encoded payload"):
        Track.from_lavalink(object(), None)


def test_loop_mode_falls_back_to_off() -> None:
    assert LoopMode.from_db("queue") is LoopMode.QUEUE
    assert LoopMode.from_db("nonsense") is LoopMode.OFF
