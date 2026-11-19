# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""SQLite persistence for guild players and settings."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from pathlib import Path

import aiosqlite

from .models import GuildSnapshot, LoopMode, Track

__all__ = ["Database"]

_log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_state (
    guild_id        INTEGER PRIMARY KEY,
    voice_channel_id INTEGER,
    text_channel_id  INTEGER,
    volume          INTEGER NOT NULL,
    loop_mode       TEXT    NOT NULL,
    paused          INTEGER NOT NULL DEFAULT 0,
    position_ms     INTEGER NOT NULL DEFAULT 0,
    current_track   TEXT,
    updated_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS queue_items (
    guild_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    track    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, position)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id    INTEGER PRIMARY KEY,
    dj_role_id  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_queue_items_guild ON queue_items (guild_id, position);
"""


class Database:
    """A tiny async wrapper; writes are serialised by a single connection."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA)
        await self._conn.execute("PRAGMA user_version=1")
        await self._conn.commit()
        _log.info("database ready", extra={"path": str(self._path)})

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() must be awaited first")
        return self._conn

    async def save_snapshot(self, snapshot: GuildSnapshot) -> None:
        """Replace a guild's persisted state atomically."""
        current = snapshot.current.to_json() if snapshot.current is not None else None
        async with self._lock:
            conn = self._connection
            try:
                if conn.in_transaction:
                    await conn.rollback()
                await conn.execute("BEGIN IMMEDIATE")
                await conn.execute(
                    """
                    INSERT INTO guild_state (
                        guild_id, voice_channel_id, text_channel_id, volume,
                        loop_mode, paused, position_ms, current_track, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET
                        voice_channel_id = excluded.voice_channel_id,
                        text_channel_id  = excluded.text_channel_id,
                        volume           = excluded.volume,
                        loop_mode        = excluded.loop_mode,
                        paused           = excluded.paused,
                        position_ms      = excluded.position_ms,
                        current_track    = excluded.current_track,
                        updated_at       = excluded.updated_at
                    """,
                    (
                        snapshot.guild_id,
                        snapshot.voice_channel_id,
                        snapshot.text_channel_id,
                        snapshot.volume,
                        snapshot.loop_mode.value,
                        int(snapshot.paused),
                        max(0, snapshot.position_ms),
                        current,
                        time.time(),
                    ),
                )
                await conn.execute("DELETE FROM queue_items WHERE guild_id = ?", (snapshot.guild_id,))
                if snapshot.queue:
                    await conn.executemany(
                        "INSERT INTO queue_items (guild_id, position, track) VALUES (?, ?, ?)",
                        (
                            (snapshot.guild_id, position, track.to_json())
                            for position, track in enumerate(snapshot.queue)
                        ),
                    )
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    async def load_snapshots(self) -> list[GuildSnapshot]:
        conn = self._connection
        async with conn.execute("SELECT * FROM guild_state ORDER BY guild_id") as cursor:
            state_rows = await cursor.fetchall()
        if not state_rows:
            return []

        queued: dict[int, list[tuple[int, str]]] = {}
        async with conn.execute(
            "SELECT guild_id, position, track FROM queue_items ORDER BY guild_id, position"
        ) as cursor:
            for row in await cursor.fetchall():
                queued.setdefault(int(row["guild_id"]), []).append((int(row["position"]), row["track"]))

        snapshots: list[GuildSnapshot] = []
        for row in state_rows:
            guild_id = int(row["guild_id"])
            try:
                current = Track.from_json(row["current_track"]) if row["current_track"] else None
            except (ValueError, KeyError, TypeError):
                _log.warning("discarding unreadable current track", extra={"guild_id": guild_id})
                current = None

            queue: list[Track] = []
            for _, payload in sorted(queued.get(guild_id, [])):
                try:
                    queue.append(Track.from_json(payload))
                except (ValueError, KeyError, TypeError):
                    _log.warning("discarding unreadable queued track", extra={"guild_id": guild_id})

            snapshots.append(
                GuildSnapshot(
                    guild_id=guild_id,
                    voice_channel_id=row["voice_channel_id"],
                    text_channel_id=row["text_channel_id"],
                    volume=int(row["volume"]),
                    loop_mode=LoopMode.from_db(row["loop_mode"]),
                    paused=bool(row["paused"]),
                    position_ms=int(row["position_ms"]),
                    current=current,
                    queue=queue,
                )
            )
        return snapshots

    async def delete_guild(self, guild_id: int) -> None:
        async with self._lock:
            conn = self._connection
            try:
                if conn.in_transaction:
                    await conn.rollback()
                await conn.execute("BEGIN IMMEDIATE")
                await conn.execute("DELETE FROM guild_state WHERE guild_id = ?", (guild_id,))
                await conn.execute("DELETE FROM queue_items WHERE guild_id = ?", (guild_id,))
                await conn.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild_id,))
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    async def set_dj_role(self, guild_id: int, role_id: int | None) -> None:
        async with self._lock:
            conn = self._connection
            await conn.execute(
                """
                INSERT INTO guild_settings (guild_id, dj_role_id) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET dj_role_id = excluded.dj_role_id
                """,
                (guild_id, role_id),
            )
            await conn.commit()

    async def load_dj_roles(self) -> dict[int, int]:
        conn = self._connection
        async with conn.execute(
            "SELECT guild_id, dj_role_id FROM guild_settings WHERE dj_role_id IS NOT NULL"
        ) as cursor:
            return {int(row["guild_id"]): int(row["dj_role_id"]) for row in await cursor.fetchall()}

    async def queue_payloads(self, guild_id: int) -> Iterable[str]:
        """Diagnostic helper used by tests and future maintenance tasks."""
        conn = self._connection
        async with conn.execute(
            "SELECT track FROM queue_items WHERE guild_id = ? ORDER BY position", (guild_id,)
        ) as cursor:
            return [row["track"] for row in await cursor.fetchall()]
