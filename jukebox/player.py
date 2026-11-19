# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Per-guild playback state: queue, loop, timers and persistence.

The Lavalink library's ``DefaultPlayer`` is intentionally reduced to a dumb
transport (see ``JukeboxLavalinkPlayer``).  All transition decisions live here
so that the queue survives restarts, loop modes are deterministic, and failures
are reported to the channel instead of silently cascading.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
import lavalink

from .errors import UserError
from .models import GuildSnapshot, LoopMode, QueueFullError, Track, TrackQueue
from .ui import error_embed, format_duration

if TYPE_CHECKING:
    from .bot import JukeboxBot

__all__ = ["GuildPlayer", "JukeboxLavalinkPlayer"]

_log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3
VOICE_CONNECT_TIMEOUT = 12.0
VOICE_RECONNECT_ATTEMPTS = (1.0, 2.0, 4.0)


class JukeboxLavalinkPlayer(lavalink.DefaultPlayer):
    """No built-in auto-advance; ``GuildPlayer`` owns the queue."""

    async def handle_event(self, event: lavalink.Event) -> None:
        return None


@dataclass(frozen=True, slots=True)
class FailureReport:
    """What the event handler should tell the channel after a failure."""

    title: str
    reason: str
    stopped: bool


class GuildPlayer:
    def __init__(self, bot: JukeboxBot, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue = TrackQueue(bot.config.max_queue_size)
        self.current: Track | None = None
        self.volume = bot.config.default_volume
        self.loop = LoopMode.OFF
        self.paused = False
        self.voice_channel_id: int | None = None
        self.text_channel_id: int | None = None
        self.consecutive_failures = 0

        self._ll: JukeboxLavalinkPlayer | None = None
        self._lock = asyncio.Lock()
        self._position_ms = 0
        self._idle_task: asyncio.Task[None] | None = None
        self._empty_task: asyncio.Task[None] | None = None
        self._reconnecting = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closed = False

    # ------------------------------------------------------------------ state

    @property
    def position_ms(self) -> int:
        ll = self._ll
        if ll is not None and self.current is not None and ll.current is not None:
            try:
                return max(0, int(ll.position))
            except Exception:  # pragma: no cover - library internals
                return self._position_ms
        return self._position_ms

    @property
    def is_connected(self) -> bool:
        return self.voice_channel_id is not None

    def snapshot(self) -> GuildSnapshot:
        return GuildSnapshot(
            guild_id=self.guild_id,
            voice_channel_id=self.voice_channel_id,
            text_channel_id=self.text_channel_id,
            volume=self.volume,
            loop_mode=self.loop,
            paused=self.paused,
            position_ms=self.position_ms,
            current=self.current,
            queue=self.queue.as_list(),
        )

    async def persist(self) -> None:
        try:
            await self.bot.db.save_snapshot(self.snapshot())
        except Exception:
            _log.exception("could not persist guild state", extra={"guild_id": self.guild_id})

    # -------------------------------------------------------------- lifecycle

    def _ensure_ll(self) -> JukeboxLavalinkPlayer:
        if self._ll is not None:
            return self._ll
        manager = self.bot.lavalink.client.player_manager
        existing = manager.get(self.guild_id)
        if isinstance(existing, JukeboxLavalinkPlayer):
            self._ll = existing
            return existing
        try:
            player = manager.create(self.guild_id, cls=JukeboxLavalinkPlayer)
        except lavalink.ClientError as error:
            raise UserError(
                "I cannot reach an audio node right now.",
                hint="Try again once the node is back; the bot reconnects automatically.",
            ) from error
        self._ll = player
        return player

    async def connect(self, channel: discord.VoiceChannel) -> None:
        """Ask Discord to move the bot into ``channel`` and wait for Lavalink."""
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise UserError("I cannot see this server anymore.")

        try:
            await guild.change_voice_state(channel=channel, self_deaf=True)
        except (discord.Forbidden, discord.HTTPException) as error:
            raise UserError(
                f"I cannot join **{channel.name}**.",
                hint="Check that I have Connect and Speak in that channel.",
            ) from error

        self.voice_channel_id = channel.id
        self._cancel_task(self._idle_task)
        self._idle_task = None

        ll = self._ensure_ll()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + VOICE_CONNECT_TIMEOUT
        while ll.channel_id != channel.id and loop.time() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0.1)
        if ll.channel_id != channel.id:
            _log.warning(
                "voice state did not reach lavalink before the timeout",
                extra={"guild_id": self.guild_id, "channel_id": channel.id},
            )
        self.refresh_empty_timer()
        if self.current is None and not self.queue:
            self._start_idle_timer()
        await self.persist()

    async def close(self) -> None:
        """Save state without tearing down the voice connection.

        Called during SIGTERM shutdown: the process is about to disappear, so
        the row on disk is what lets us rejoin and resume on the next start.
        """
        self._closed = True
        self._cancel_task(self._idle_task)
        self._cancel_task(self._empty_task)
        self._cancel_task(self._reconnect_task)
        await self.persist()

    # --------------------------------------------------------------- playback

    async def start_track(self, track: Track, position_ms: int = 0, paused: bool = False) -> None:
        async with self._lock:
            await self._start_locked(track, position_ms, paused)
        await self.persist()

    async def _start_locked(self, track: Track, position_ms: int, paused: bool) -> None:
        ll = self._ensure_ll()
        try:
            audio = lavalink.AudioTrack(track.raw, requester=track.requester_id or 0)
        except lavalink.InvalidTrack as error:
            raise UserError(
                f"I could not decode **{track.title}**.",
                hint="Remove it with `/remove` or try loading it again.",
            ) from error

        options: dict[str, int] = {}
        if not track.is_stream and track.duration_ms > 0 and position_ms > 0:
            options["start_time"] = min(position_ms, max(0, track.duration_ms - 1000))

        try:
            await ll.play(audio, volume=self.volume, pause=paused, **options)
        except (lavalink.ClientError, lavalink.RequestError) as error:
            raise UserError(
                "The audio node refused to start playback.",
                hint="Try again in a moment.",
            ) from error

        self.current = track
        self.paused = paused
        self._position_ms = int(options.get("start_time", 0))
        self._cancel_task(self._idle_task)
        self._idle_task = None
        _log.info(
            "playing track",
            extra={
                "guild_id": self.guild_id,
                "track": track.title,
                "source": track.source_name,
                "position_ms": self._position_ms,
            },
        )

    async def enqueue(self, tracks: list[Track]) -> tuple[int, int]:
        was_idle = self.current is None
        added, dropped = self.queue.add_many(tracks)
        if added and was_idle:
            await self.advance(manual=True)
        else:
            await self.persist()
        return added, dropped

    async def advance(self, *, manual: bool = True) -> None:
        async with self._lock:
            await self._advance_locked(manual=manual)
        await self.persist()

    async def _advance_locked(self, *, manual: bool) -> None:
        current = self.current
        if current is not None and not manual and self.loop is LoopMode.TRACK:
            await self._start_locked(current, 0, False)
            return

        if current is not None and not manual and self.loop is LoopMode.QUEUE:
            try:
                self.queue.add(current)
            except QueueFullError:
                _log.debug(
                    "loop queue is full; dropping oldest loop entry", extra={"guild_id": self.guild_id}
                )

        next_track = self.queue.pop_next()
        if next_track is None:
            self.current = None
            self.paused = False
            self._position_ms = 0
            ll = self._ll
            if ll is not None:
                try:
                    await ll.stop()
                except Exception:
                    _log.exception("error stopping player", extra={"guild_id": self.guild_id})
            self._start_idle_timer()
            return

        await self._start_locked(next_track, 0, False)

    async def skip(self) -> None:
        if self.current is None:
            raise UserError("Nothing is playing.")
        await self.advance(manual=True)

    async def stop(self) -> None:
        async with self._lock:
            self.queue.clear()
            await self._stop_locked()
        await self.persist()

    async def _stop_locked(self) -> None:
        self.current = None
        self.paused = False
        self._position_ms = 0
        ll = self._ll
        if ll is not None:
            try:
                await ll.stop()
            except Exception:
                _log.exception("error stopping player", extra={"guild_id": self.guild_id})
        self._start_idle_timer()

    async def set_paused(self, paused: bool) -> None:
        if self.current is None:
            raise UserError("Nothing is playing.")
        ll = self._ensure_ll()
        await ll.set_pause(paused)
        self.paused = paused
        await self.persist()

    async def seek(self, position_ms: int) -> None:
        track = self.current
        if track is None:
            raise UserError("Nothing is playing.")
        if track.is_stream:
            raise UserError("Live streams cannot be seeked.")
        if not 0 <= position_ms <= track.duration_ms:
            raise UserError(f"Seek target must be between 0 and {format_duration(track.duration_ms)}.")
        ll = self._ensure_ll()
        await ll.seek(position_ms)
        self._position_ms = position_ms
        await self.persist()

    async def set_volume(self, volume: int) -> None:
        ll = self._ensure_ll()
        await ll.set_volume(volume)
        self.volume = volume
        await self.persist()

    async def set_loop(self, mode: LoopMode) -> None:
        self.loop = mode
        await self.persist()

    def shuffle(self) -> None:
        self.queue.shuffle()

    def remove(self, index: int) -> Track:
        return self.queue.remove(index)

    def move(self, source: int, destination: int) -> None:
        self.queue.move(source, destination)

    def clear_queue(self) -> None:
        self.queue.clear()

    # --------------------------------------------------------------- failures

    async def handle_track_start(self, encoded: str) -> None:
        if self.current is None or self.current.encoded != encoded:
            return
        self.consecutive_failures = 0
        self._position_ms = 0
        await self.persist()

    async def handle_track_end(self, encoded: str, reason: lavalink.EndReason) -> None:
        async with self._lock:
            if self.current is None or self.current.encoded != encoded:
                return
            if reason is lavalink.EndReason.FINISHED:
                await self._advance_locked(manual=False)
            elif reason is lavalink.EndReason.LOAD_FAILED:
                await self._register_failure_locked()
            else:
                return
        await self.persist()

    async def handle_failure(self, encoded: str, reason: str) -> FailureReport | None:
        """Handle an exception/stuck event; returns a report for the channel."""
        async with self._lock:
            if self.current is None or self.current.encoded != encoded:
                return None
            title = self.current.title
            stopped = await self._register_failure_locked()
        await self.persist()
        return FailureReport(title=title, reason=reason, stopped=stopped)

    async def _register_failure_locked(self) -> bool:
        self.consecutive_failures += 1
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            _log.warning(
                "stopping after consecutive failures",
                extra={"guild_id": self.guild_id, "failures": self.consecutive_failures},
            )
            await self._stop_locked()
            return True
        await self._advance_locked(manual=True)
        return False

    # ------------------------------------------------------------- auto leave

    def _start_idle_timer(self) -> None:
        timeout = self.bot.config.idle_timeout
        if timeout <= 0 or self._closed:
            return
        self._cancel_task(self._idle_task)
        self._idle_task = asyncio.create_task(self._idle_after(timeout))

    async def _idle_after(self, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            if self._closed or self.current is not None or self.queue:
                return
            await self.disconnect(
                clear_queue=False,
                reason=f"Left voice after {delay}s of inactivity.",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("idle timer failed", extra={"guild_id": self.guild_id})

    def refresh_empty_timer(self) -> None:
        self._cancel_task(self._empty_task)
        self._empty_task = None
        timeout = self.bot.config.empty_timeout
        if timeout <= 0 or self.voice_channel_id is None or self._closed:
            return

        guild = self.bot.get_guild(self.guild_id)
        channel = guild.get_channel(self.voice_channel_id) if guild is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            return
        if any(not member.bot for member in channel.members):
            return
        self._empty_task = asyncio.create_task(self._empty_after(timeout))

    async def _empty_after(self, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            if self._closed or self.voice_channel_id is None:
                return
            guild = self.bot.get_guild(self.guild_id)
            channel = guild.get_channel(self.voice_channel_id) if guild is not None else None
            if isinstance(channel, discord.VoiceChannel) and any(
                not member.bot for member in channel.members
            ):
                return
            await self.disconnect(
                clear_queue=True,
                reason=f"Left voice because the channel was empty for {delay}s.",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("empty-channel timer failed", extra={"guild_id": self.guild_id})

    def on_bot_voice_state(self, channel: discord.abc.Snowflake | None) -> None:
        """React to the bot being moved or disconnected by Discord."""
        if channel is None:
            if self.voice_channel_id is not None:
                _log.warning("bot was disconnected from voice", extra={"guild_id": self.guild_id})
            self.voice_channel_id = None
            self.current = None
            self.paused = False
            self._position_ms = 0
            self._cancel_task(self._empty_task)
            self._cancel_task(self._idle_task)
            return
        if self.voice_channel_id != channel.id:
            self.voice_channel_id = channel.id
            self.refresh_empty_timer()

    async def handle_ws_closed(self, code: int, reason: str, by_remote: bool) -> None:
        """Handle a Lavalink<->Discord voice websocket closing."""
        if self.voice_channel_id is None:
            return
        _log.warning(
            "voice websocket closed",
            extra={"guild_id": self.guild_id, "code": code, "reason": reason, "by_remote": by_remote},
        )
        if code in {4014, 4006, 4009}:
            # 4014: removed from the channel; 4006/4009: the voice session is
            # gone.  Re-sending the voice state is the only way back.
            self.voice_channel_id = None
            self.current = None
            self._position_ms = 0
            self._cancel_task(self._empty_task)
            await self.notify(
                embed=error_embed(
                    "I lost the voice connection.",
                    f"Discord closed the voice session ({code}). Use `/play` to start again; "
                    "the queue is still here.",
                )
            )
            await self.persist()
            return

        if not self._reconnecting:
            self._reconnecting = True
            self._reconnect_task = asyncio.create_task(self._reconnect_voice())

    async def _reconnect_voice(self) -> None:
        try:
            guild = self.bot.get_guild(self.guild_id)
            channel_id = self.voice_channel_id
            if guild is None or channel_id is None:
                return
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                return
            for delay in VOICE_RECONNECT_ATTEMPTS:
                await asyncio.sleep(delay)
                if self.voice_channel_id != channel_id:
                    return
                try:
                    await guild.change_voice_state(channel=channel, self_deaf=True)
                except (discord.Forbidden, discord.HTTPException):
                    _log.exception("voice reconnect attempt failed", extra={"guild_id": self.guild_id})
                    continue
                ll = self._ll
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 5
                while ll is not None and ll.channel_id != channel_id and loop.time() < deadline:  # noqa: ASYNC110
                    await asyncio.sleep(0.1)
                if ll is not None and ll.channel_id == channel_id:
                    await self.notify(embed=error_embed("Reconnected to voice.", "Playback continues."))
                    return
            await self.notify(
                embed=error_embed("I could not rejoin the voice channel.", "Use `/play` to try again.")
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("voice reconnect failed", extra={"guild_id": self.guild_id})
        finally:
            self._reconnecting = False

    # -------------------------------------------------------------- teardown

    async def disconnect(self, *, clear_queue: bool, reason: str | None = None) -> None:
        async with self._lock:
            await self._teardown_locked(clear_queue=clear_queue)
        await self.persist()
        if reason:
            await self.notify(embed=error_embed(reason))

    async def _teardown_locked(self, *, clear_queue: bool) -> None:
        self._cancel_task(self._idle_task)
        self._cancel_task(self._empty_task)
        self._cancel_task(self._reconnect_task)
        self._idle_task = None
        self._empty_task = None

        manager = self.bot.lavalink.client.player_manager
        ll = self._ll
        if ll is not None:
            with contextlib.suppress(Exception):
                await ll.stop()
            try:
                await manager.destroy(self.guild_id)
            except Exception:
                _log.debug("could not destroy lavalink player", extra={"guild_id": self.guild_id})
        self._ll = None

        guild = self.bot.get_guild(self.guild_id)
        if guild is not None and self.voice_channel_id is not None:
            try:
                await guild.change_voice_state(channel=None)
            except (discord.Forbidden, discord.HTTPException):
                _log.exception("could not leave voice", extra={"guild_id": self.guild_id})

        self.voice_channel_id = None
        self.current = None
        self.paused = False
        self._position_ms = 0
        if clear_queue:
            self.queue.clear()

    # ------------------------------------------------------------- messaging

    async def notify(self, *, content: str | None = None, embed: discord.Embed | None = None) -> None:
        if self.text_channel_id is None:
            return
        channel = self.bot.get_channel(self.text_channel_id)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            return
        try:
            await channel.send(content=content, embed=embed)
        except discord.HTTPException:
            _log.debug("could not send notification", extra={"guild_id": self.guild_id})

    @staticmethod
    def _cancel_task(task: asyncio.Task[None] | None) -> None:
        if task is not None and not task.done():
            task.cancel()
