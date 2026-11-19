# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""The Discord client: startup, restore, event routing and shutdown."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import discord
from discord.ext import commands

from . import __version__
from .config import Config
from .db import Database
from .errors import UserError
from .health import HealthServer
from .lavalink_service import LavalinkService
from .models import GuildSnapshot
from .player import GuildPlayer
from .ui import error_embed, format_duration, status_embed

__all__ = ["JukeboxBot"]

_log = logging.getLogger(__name__)

RESTORE_NODE_TIMEOUT = 60.0


class JukeboxBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            enable_debug_events=True,
            allowed_mentions=discord.AllowedMentions.none(),
            activity=discord.Activity(type=discord.ActivityType.listening, name="/play"),
        )
        self.config = config
        self.db = Database(config.database_path)
        self.lavalink: LavalinkService | None = None
        self.health: HealthServer | None = None
        self.players: dict[int, GuildPlayer] = {}
        self.dj_roles: dict[int, int] = {}

        self._restore_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._restore_started = False
        self._closing = False

    # ------------------------------------------------------------- lifecycle

    async def setup_hook(self) -> None:
        await self.db.connect()
        self.dj_roles = await self.db.load_dj_roles()

        assert self.user is not None, "setup_hook runs after login"
        self.lavalink = LavalinkService(self.config.lavalink, self.user.id)
        await self.lavalink.start()

        from .cogs.music import Music
        from .cogs.settings import Settings

        await self.add_cog(Music(self))
        await self.add_cog(Settings(self))

        self.tree.on_error = self._on_app_command_error

        self.health = HealthServer(self.config.health_host, self.config.health_port, self._health_payload)
        await self.health.start()
        _log.info("bot initialised", extra={"version": __version__})

    async def on_ready(self) -> None:
        assert self.user is not None
        _log.info(
            "connected to discord",
            extra={"user": str(self.user), "guilds": len(self.guilds)},
        )
        await self._sync_commands()

        if not self._restore_started:
            self._restore_started = True
            self._restore_task = asyncio.create_task(self._restore_all())
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def _sync_commands(self) -> None:
        try:
            if self.config.guild_id is not None:
                guild = discord.Object(id=self.config.guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                _log.info("synced commands to dev guild", extra={"count": len(synced)})
            else:
                synced = await self.tree.sync()
                _log.info("synced global commands", extra={"count": len(synced)})
        except discord.HTTPException:
            _log.exception("command sync failed")

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        _log.info("shutting down")

        for task in (self._restore_task, self._flush_task):
            if task is not None and not task.done():
                task.cancel()

        try:
            await asyncio.wait_for(self._save_all(), timeout=self.config.shutdown_timeout)
        except TimeoutError:
            _log.error("timed out while saving player state")
        except Exception:
            _log.exception("error while saving player state")

        if self.health is not None:
            await self.health.stop()
        if self.lavalink is not None:
            await self.lavalink.close()
        await self.db.close()
        await super().close()

    async def _save_all(self) -> None:
        await asyncio.gather(
            *(player.close() for player in list(self.players.values())),
            return_exceptions=True,
        )

    async def _flush_loop(self) -> None:
        interval = self.config.state_flush_interval
        try:
            while not self._closing:
                await asyncio.sleep(interval)
                for player in list(self.players.values()):
                    if player.is_connected:
                        await player.persist()
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("state flush loop failed")

    # ---------------------------------------------------------------- players

    def get_player(self, guild_id: int) -> GuildPlayer | None:
        return self.players.get(guild_id)

    def create_player(self, guild_id: int) -> GuildPlayer:
        player = GuildPlayer(self, guild_id)
        self.players[guild_id] = player
        return player

    def dj_role_id(self, guild_id: int) -> int | None:
        return self.dj_roles.get(guild_id)

    # ---------------------------------------------------------------- restore

    async def _restore_all(self) -> None:
        snapshots = await self.db.load_snapshots()
        if not snapshots:
            return
        if not self.config.restore_on_start:
            _log.info("restore disabled; saved states are kept", extra={"guilds": len(snapshots)})
            return

        node_ready = self.lavalink is not None and await self.lavalink.wait_ready(RESTORE_NODE_TIMEOUT)
        if not node_ready:
            _log.warning("lavalink was not ready in time; keeping state for the next start")
            return

        _log.info("restoring players", extra={"guilds": len(snapshots)})
        for snapshot in snapshots:
            try:
                await self._restore_one(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("could not restore guild", extra={"guild_id": snapshot.guild_id})

    async def _restore_one(self, snapshot: GuildSnapshot) -> None:
        if snapshot.current is None and not snapshot.queue:
            return

        guild = self.get_guild(snapshot.guild_id)
        if guild is None:
            _log.warning("guild is unavailable; keeping state", extra={"guild_id": snapshot.guild_id})
            return

        voice = guild.get_channel(snapshot.voice_channel_id) if snapshot.voice_channel_id else None
        if voice is None or not hasattr(voice, "permissions_for"):
            _log.info(
                "saved voice channel is gone; dropping state",
                extra={"guild_id": snapshot.guild_id, "channel_id": snapshot.voice_channel_id},
            )
            await self.db.delete_guild(snapshot.guild_id)
            return

        me = guild.me
        if me is None:
            return
        permissions = voice.permissions_for(me)
        if not (permissions.connect and permissions.speak):
            _log.warning("missing voice permissions; keeping state", extra={"guild_id": snapshot.guild_id})
            return

        player = self.players.get(snapshot.guild_id) or self.create_player(snapshot.guild_id)
        player.volume = snapshot.volume
        player.loop = snapshot.loop_mode
        player.text_channel_id = snapshot.text_channel_id
        player.queue.replace(snapshot.queue)

        await player.connect(voice)

        if snapshot.current is not None:
            try:
                await player.start_track(snapshot.current, snapshot.position_ms, snapshot.paused)
            except UserError as error:
                _log.warning(
                    "could not resume current track",
                    extra={"guild_id": snapshot.guild_id, "error": error.message},
                )
                player.current = None

        if player.current is None and player.queue:
            try:
                await player.advance(manual=True)
            except UserError:
                _log.exception("could not start restored queue", extra={"guild_id": snapshot.guild_id})

        if player.current is None:
            await player.disconnect(clear_queue=True)
            return

        await player.persist()
        position = format_duration(player.position_ms)
        await player.notify(
            embed=status_embed(
                "Resumed after restart",
                f"Playing **{player.current.title}** from {position}.\n"
                f"{len(player.queue)} track(s) still queued.",
            )
        )
        _log.info(
            "resumed guild playback",
            extra={"guild_id": snapshot.guild_id, "track": player.current.title},
        )

    # ---------------------------------------------------------------- events

    async def on_socket_raw_receive(self, payload: Any) -> None:
        """Forward voice gateway payloads to Lavalink.

        ``enable_debug_events=True`` makes discord.py dispatch parsed gateway
        objects here; Lavalink needs both VOICE_STATE_UPDATE (with its session
        id and channel id) and VOICE_SERVER_UPDATE (endpoint and token).
        """
        try:
            if isinstance(payload, str):
                if "VOICE_SERVER_UPDATE" not in payload and "VOICE_STATE_UPDATE" not in payload:
                    return
                data = json.loads(payload)
            else:
                data = payload
            if not isinstance(data, dict):
                return
            event = data.get("t")
            if event not in {"VOICE_STATE_UPDATE", "VOICE_SERVER_UPDATE"}:
                return
            body = data.get("d") or {}
            if self.user is None or self.lavalink is None:
                return
            if event == "VOICE_STATE_UPDATE" and int(body.get("user_id", 0)) != self.user.id:
                return
            await self.lavalink.client.voice_update_handler(data)
        except Exception:
            _log.exception("failed to forward a voice gateway event")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        try:
            player = self.players.get(member.guild.id)
            if player is None:
                return
            if self.user is not None and member.id == self.user.id:
                player.on_bot_voice_state(after.channel)
                await player.persist()
                return
            channel_ids = {state.channel.id for state in (before, after) if state.channel is not None}
            if player.voice_channel_id in channel_ids:
                player.refresh_empty_timer()
        except Exception:
            _log.exception("voice state update handling failed")

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        player = self.players.pop(guild.id, None)
        if player is not None:
            try:
                await player.disconnect(clear_queue=True)
            except Exception:
                _log.exception("could not tear down player for removed guild")
        await self.db.delete_guild(guild.id)
        self.dj_roles.pop(guild.id, None)

    # ----------------------------------------------------------------- errors

    async def _on_app_command_error(self, interaction: discord.Interaction, error: Exception) -> None:
        original = getattr(error, "original", error)
        try:
            if isinstance(original, UserError):
                await self._send_error(interaction, original.message, original.hint)
            elif isinstance(original, discord.app_commands.MissingPermissions):
                await self._send_error(
                    interaction,
                    "You need the **Manage Server** permission to do that.",
                    None,
                )
            elif isinstance(original, discord.app_commands.CheckFailure):
                await self._send_error(interaction, "You are not allowed to use that command.", None)
            else:
                _log.exception(
                    "command failed",
                    exc_info=original,
                    extra={
                        "command": getattr(interaction.command, "qualified_name", "unknown"),
                        "guild_id": interaction.guild_id,
                        "user_id": getattr(interaction.user, "id", None),
                    },
                )
                await self._send_error(
                    interaction,
                    "Something went wrong while running that command.",
                    "The error has been logged. Try again in a moment.",
                )
        except discord.HTTPException:
            _log.debug("could not deliver an error response", extra={"guild_id": interaction.guild_id})

    @staticmethod
    async def _send_error(interaction: discord.Interaction, message: str, hint: str | None) -> None:
        embed = error_embed(message, hint)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----------------------------------------------------------------- health

    def _health_payload(self) -> dict[str, Any]:
        ready = self.is_ready()
        latency = round(self.latency * 1000) if ready else None
        lavalink = self.lavalink
        node_available = bool(lavalink and lavalink.available)
        if not ready:
            status = "starting"
        elif not node_available:
            status = "degraded"
        else:
            status = "ok"
        return {
            "status": status,
            "version": __version__,
            "bot": {
                "ready": ready,
                "user": str(self.user) if self.user else None,
                "guilds": len(self.guilds),
                "latency_ms": latency,
            },
            "players": len(self.players),
            "lavalink": {
                "available": node_available,
                "nodes": lavalink.nodes if lavalink else [],
            },
        }
