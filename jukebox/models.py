# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Domain models shared by the player, the database and the Discord UI."""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "GuildSnapshot",
    "LoopMode",
    "QueueFullError",
    "Track",
    "TrackQueue",
]


class LoopMode(StrEnum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"

    @classmethod
    def from_db(cls, value: str) -> LoopMode:
        try:
            return cls(value)
        except ValueError:
            return cls.OFF


class QueueFullError(RuntimeError):
    """Raised when a queue cannot accept more tracks."""


@dataclass(frozen=True, slots=True)
class Track:
    """A Lavalink track with enough metadata to be stored and displayed.

    ``raw`` is the exact track object returned by Lavalink.  Keeping it means a
    queued track can be replayed after a restart without another search.
    """

    encoded: str
    identifier: str
    title: str
    author: str
    duration_ms: int
    uri: str | None
    artwork_url: str | None
    is_stream: bool
    source_name: str
    requester_id: int | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_lavalink(cls, track: Any, requester_id: int | None) -> Track:
        encoded = getattr(track, "track", None)
        if not encoded:
            raise ValueError("Lavalink returned a track without an encoded payload")
        raw = dict(getattr(track, "raw", {}) or {})
        if "encoded" not in raw:
            raw["encoded"] = encoded
        if "info" not in raw:
            raw["info"] = {
                "identifier": track.identifier,
                "isSeekable": track.is_seekable,
                "author": track.author,
                "length": track.duration,
                "isStream": track.is_stream,
                "title": track.title,
                "uri": track.uri,
                "artworkUrl": track.artwork_url,
                "sourceName": track.source_name,
            }
        return cls(
            encoded=encoded,
            identifier=str(getattr(track, "identifier", "")),
            title=str(getattr(track, "title", "Unknown title")),
            author=str(getattr(track, "author", "Unknown artist")),
            duration_ms=int(getattr(track, "duration", 0) or 0),
            uri=getattr(track, "uri", None),
            artwork_url=getattr(track, "artwork_url", None),
            is_stream=bool(getattr(track, "is_stream", False)),
            source_name=str(getattr(track, "source_name", "unknown")),
            requester_id=requester_id,
            raw=raw,
        )

    def to_json(self) -> str:
        return json.dumps(
            {"requester_id": self.requester_id, "raw": self.raw},
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> Track:
        data = json.loads(payload)
        raw = data["raw"]
        info = raw.get("info", raw)
        return cls(
            encoded=raw["encoded"],
            identifier=str(info.get("identifier", "")),
            title=str(info.get("title", "Unknown title")),
            author=str(info.get("author", "Unknown artist")),
            duration_ms=int(info.get("length", 0) or 0),
            uri=info.get("uri"),
            artwork_url=info.get("artworkUrl"),
            is_stream=bool(info.get("isStream", False)),
            source_name=str(info.get("sourceName", "unknown")),
            requester_id=data.get("requester_id"),
            raw=raw,
        )


@dataclass(slots=True)
class GuildSnapshot:
    """The durable state of one guild's player."""

    guild_id: int
    voice_channel_id: int | None
    text_channel_id: int | None
    volume: int
    loop_mode: LoopMode
    paused: bool
    position_ms: int
    current: Track | None
    queue: list[Track]


class TrackQueue:
    """A bounded FIFO queue with the editing operations exposed as commands."""

    __slots__ = ("_items", "_max_size")

    def __init__(self, max_size: int, items: Sequence[Track] = ()) -> None:
        self._max_size = max_size
        self._items: list[Track] = list(items)[:max_size]

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __iter__(self) -> Iterator[Track]:
        return iter(self._items)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def free_slots(self) -> int:
        return max(0, self._max_size - len(self._items))

    def add(self, track: Track) -> int:
        """Append one track and return its 1-based position."""
        if len(self._items) >= self._max_size:
            raise QueueFullError(f"Queue is limited to {self._max_size} tracks")
        self._items.append(track)
        return len(self._items)

    def add_many(self, tracks: Iterable[Track]) -> tuple[int, int]:
        """Append tracks up to the limit, returning ``(added, dropped)``."""
        added = 0
        dropped = 0
        for track in tracks:
            if len(self._items) >= self._max_size:
                dropped += 1
                continue
            self._items.append(track)
            added += 1
        return added, dropped

    def pop_next(self) -> Track | None:
        return self._items.pop(0) if self._items else None

    def remove(self, index: int) -> Track:
        """Remove and return the track at a zero-based index."""
        if not 0 <= index < len(self._items):
            raise IndexError(index)
        return self._items.pop(index)

    def move(self, source: int, destination: int) -> None:
        if not 0 <= source < len(self._items):
            raise IndexError(source)
        if not 0 <= destination < len(self._items):
            raise IndexError(destination)
        track = self._items.pop(source)
        self._items.insert(destination, track)

    def clear(self) -> None:
        self._items.clear()

    def shuffle(self, rng: random.Random | None = None) -> None:
        (rng or random).shuffle(self._items)

    def as_list(self) -> list[Track]:
        return list(self._items)

    def replace(self, tracks: Iterable[Track]) -> None:
        self._items = list(tracks)[: self._max_size]
