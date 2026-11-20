# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Slash commands and Lavalink event handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import discord
import lavalink
from discord import app_commands
from discord.ext import commands

from ..errors import UserError
from ..models import LoopMode, Track
from ..player import MAX_CONSECUTIVE_FAILURES
from ..queue_view import QueueView
from ..search_view import SearchView, build_suggestion_embed
from ..sources import resolve_query
from ..ui import (
    error_embed,
    format_duration,
    now_playing_embed,
    queue_embed,
    status_embed,
)

if TYPE_CHECKING:
    from ..bot import JukeboxBot
    from ..player import GuildPlayer

__all__ = ["Music"]

_log = logging.getLogger(__name__)


class Music(commands.Cog):
    def __init__(self, bot: JukeboxBot) -> None:
        self.bot = bot
        assert bot.lavalink is not None
        client = bot.lavalink.client
        self._hooks = (
            (self._on_track_start, lavalink.TrackStartEvent),
            (self._on_track_end, lavalink.TrackEndEvent),
            (self._on_track_exception, lavalink.TrackExceptionEvent),
            (self._on_track_stuck, lavalink.TrackStuckEvent),
            (self._on_websocket_closed, lavalink.WebSocketClosedEvent),
            (self._on_node_ready, lavalink.NodeReadyEvent),
        )
        for hook, event_type in self._hooks:
            client.add_event_hook(hook, event=event_type)

    def cog_unload(self) -> None:
        if self.bot.lavalink is not None:
            self.bot.lavalink.client.remove_event_hooks(hooks=[hook for hook, _ in self._hooks])

    # ------------------------------------------------------------- lavalink

    async def _on_track_start(self, event: lavalink.TrackStartEvent) -> None:
        try:
            player = self.bot.players.get(event.player.guild_id)
            if player is not None:
                await player.handle_track_start(event.track.track or "")
        except Exception:
            _log.exception("track start handling failed")

    async def _on_track_end(self, event: lavalink.TrackEndEvent) -> None:
        try:
            player = self.bot.players.get(event.player.guild_id)
            if player is None:
                return
            encoded = event.track.track if event.track is not None else ""
            if event.reason is lavalink.EndReason.FINISHED:
                await player.handle_track_end(encoded, event.reason)
            elif event.reason is lavalink.EndReason.LOAD_FAILED:
                await self._report_failure(player, encoded, "Lavalink could not load it")
        except Exception:
            _log.exception("track end handling failed")

    async def _on_track_exception(self, event: lavalink.TrackExceptionEvent) -> None:
        try:
            player = self.bot.players.get(event.player.guild_id)
            if player is None:
                return
            reason = (event.message or event.cause or "unknown error").strip()
            await self._report_failure(player, event.track.track or "", reason[:300])
        except Exception:
            _log.exception("track exception handling failed")

    async def _on_track_stuck(self, event: lavalink.TrackStuckEvent) -> None:
        try:
            player = self.bot.players.get(event.player.guild_id)
            if player is None:
                return
            await self._report_failure(
                player,
                event.track.track or "",
                f"stalled for {event.threshold / 1000:.0f}s",
            )
        except Exception:
            _log.exception("track stuck handling failed")

    async def _on_websocket_closed(self, event: lavalink.WebSocketClosedEvent) -> None:
        try:
            player = self.bot.players.get(event.player.guild_id)
            if player is not None:
                await player.handle_ws_closed(event.code, event.reason, event.by_remote)
        except Exception:
            _log.exception("voice websocket close handling failed")

    async def _on_node_ready(self, event: lavalink.NodeReadyEvent) -> None:
        """A fresh node session has no players; stop stale local state.

        Session-resumed reconnects keep their players and are left alone.  A
        non-resumed session means the node lost every queued/current player, so
        pretending the old track is still playing would make /play silently
        queue instead of starting.  Reset the current track, keep the queue, and
        tell the channel what happened.
        """
        if event.resumed:
            return
        try:
            for player in list(self.bot.players.values()):
                if player.current is None:
                    continue
                player.reset_after_node_loss()
                await player.persist()
                await player.notify(
                    embed=error_embed(
                        "The audio node restarted.",
                        "Playback stopped and the queue was kept. Use `/play` to start again.",
                    )
                )
        except Exception:
            _log.exception("node recovery handling failed")

    async def _report_failure(self, player: GuildPlayer, encoded: str, reason: str) -> None:
        report = await player.handle_failure(encoded, reason)
        if report is None:
            return
        description = f"Skipping **{report.title}** — {reason}"
        if report.stopped:
            description += f"\nStopped playback after {MAX_CONSECUTIVE_FAILURES} consecutive failures."
        await player.notify(embed=error_embed(description))

    # --------------------------------------------------------------- helpers

    def _voice_channel(self, interaction: discord.Interaction) -> discord.VoiceChannel:
        if interaction.guild is None:
            raise UserError("Use this in a server.")
        state = getattr(interaction.user, "voice", None)
        channel = getattr(state, "channel", None)
        if channel is None:
            raise UserError("Join a voice channel first.")
        return channel

    def _player(self, interaction: discord.Interaction, *, create: bool = False) -> GuildPlayer:
        assert interaction.guild is not None
        player = self.bot.get_player(interaction.guild.id)
        if player is None:
            if not create:
                raise UserError("Nothing is playing.")
            player = self.bot.create_player(interaction.guild.id)
        return player

    def _check_control(
        self,
        interaction: discord.Interaction,
        player: GuildPlayer,
        voice: discord.VoiceChannel,
        *,
        allow_disconnected: bool = False,
    ) -> None:
        assert interaction.guild is not None
        member = interaction.user

        dj_role_id = self.bot.dj_role_id(interaction.guild.id)
        if dj_role_id is not None:
            role = interaction.guild.get_role(dj_role_id)
            permissions = getattr(member, "guild_permissions", None)
            is_admin = bool(getattr(permissions, "manage_guild", False))
            roles = getattr(member, "roles", ())
            if role is not None and not is_admin and role not in roles:
                raise UserError(
                    f"Only members with the **{role.name}** role (or Manage Server) can control playback."
                )

        if player.voice_channel_id is None:
            if allow_disconnected:
                return
            raise UserError("I am not in a voice channel.")
        if player.voice_channel_id != voice.id:
            raise UserError("You must be in my voice channel to control playback.")

    async def _control_target(
        self, interaction: discord.Interaction
    ) -> tuple[GuildPlayer, discord.VoiceChannel]:
        voice = self._voice_channel(interaction)
        player = self._player(interaction)
        self._check_control(interaction, player, voice)
        return player, voice

    # -------------------------------------------------------------- commands

    @app_commands.command(name="play", description="Play a track, playlist or URL")
    @app_commands.describe(query="Track name, search terms, or a link to a supported source")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        voice = self._voice_channel(interaction)
        player = self._player(interaction, create=True)
        self._check_control(interaction, player, voice, allow_disconnected=True)

        if player.voice_channel_id is None:
            await player.connect(voice)
        elif player.voice_channel_id != voice.id:
            raise UserError("I am already playing in another voice channel.")

        player.text_channel_id = interaction.channel_id
        resolved = resolve_query(query, self.bot.config)
        assert self.bot.lavalink is not None
        result = await self.bot.lavalink.get_tracks(resolved.identifier)

        if result.load_type is lavalink.LoadType.ERROR:
            detail = str(result.error) if result.error is not None else "unknown error"
            raise UserError(
                f"I could not load that from **{resolved.source.value}**.",
                hint=f"{detail[:200]} — check the Lavalink logs for the full error.",
            )
        if result.load_type is lavalink.LoadType.EMPTY or not result.tracks:
            raise UserError(
                "No matches found.",
                hint="Try a more specific query, or a direct link to the track.",
            )

        tracks: list[Track] = []
        for audio in result.tracks:
            try:
                tracks.append(Track.from_lavalink(audio, interaction.user.id))
            except (ValueError, lavalink.InvalidTrack):
                continue

        if not tracks:
            raise UserError("Lavalink returned tracks that cannot be queued.")

        if result.load_type is lavalink.LoadType.SEARCH:
            # A SEARCH result is a list of candidates, not a playlist.  List
            # them and wait for the requester to pick one; queueing all of them
            # made /play <words> start dozens of tracks at once.
            view = SearchView(player, tracks, interaction.user.id, query)
            message = await interaction.followup.send(
                embed=build_suggestion_embed(query, view.tracks), view=view
            )
            view.message = message
            return

        was_idle = player.current is None
        added, dropped = await player.enqueue(tracks)
        if added == 0:
            raise UserError(f"The queue is full ({self.bot.config.max_queue_size} tracks).")

        if was_idle and player.current is not None:
            embed = now_playing_embed(player, interaction.guild)
        else:
            playlist = result.playlist_info.name if result.playlist_info else None
            description = (
                f"Added **{added}** track(s) from **{discord.utils.escape_markdown(playlist)}**."
                if playlist
                else f"Added **{discord.utils.escape_markdown(tracks[0].title)}** to the queue."
            )
            embed = status_embed("Added to queue", description)
            if dropped:
                embed.add_field(
                    name="Queue limit",
                    value=f"{dropped} track(s) were not added because the queue is full.",
                    inline=False,
                )

        if player.paused:
            embed.add_field(name="Paused", value="Use `/resume` to continue.", inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pause", description="Pause playback")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        await player.set_paused(True)
        await interaction.response.send_message("Paused.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        await player.set_paused(False)
        await interaction.response.send_message("Resumed.", ephemeral=True)

    @app_commands.command(name="skip", description="Skip the current track")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        await player.skip()
        if player.current is not None:
            message = f"Skipped. Now playing **{discord.utils.escape_markdown(player.current.title)}**."
        else:
            message = "Skipped. The queue is now empty."
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and clear the queue")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        await player.stop()
        await interaction.response.send_message("Stopped and cleared the queue.", ephemeral=True)

    @app_commands.command(name="queue", description="Show the queue")
    @app_commands.describe(page="Page number")
    @app_commands.guild_only()
    async def queue_command(
        self,
        interaction: discord.Interaction,
        page: app_commands.Range[int, 1, 1000] = 1,
    ) -> None:
        if interaction.guild is None:
            raise UserError("Use this in a server.")
        player = self.bot.get_player(interaction.guild.id)
        if player is None or (player.current is None and not player.queue):
            await interaction.response.send_message(
                embed=status_embed("Queue", "Nothing is playing and the queue is empty."),
                ephemeral=True,
            )
            return

        view = QueueView(player, interaction.user.id)
        view.page = min(max(0, page - 1), view._page_count() - 1)
        view._sync_buttons()
        await interaction.response.send_message(
            embed=queue_embed(player, interaction.guild, view.page),
            view=view,
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="nowplaying", description="Show the current track")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            raise UserError("Use this in a server.")
        player = self.bot.get_player(interaction.guild.id)
        if player is None or player.current is None:
            raise UserError("Nothing is playing.")
        await interaction.response.send_message(embed=now_playing_embed(player, interaction.guild))

    @app_commands.command(name="seek", description="Seek within the current track")
    @app_commands.describe(seconds="Position in seconds")
    @app_commands.guild_only()
    async def seek(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 86_400],
    ) -> None:
        player, _ = await self._control_target(interaction)
        await player.seek(seconds * 1000)
        await interaction.response.send_message(
            f"Seeked to {format_duration(seconds * 1000)}.", ephemeral=True
        )

    @app_commands.command(name="volume", description="Set the playback volume")
    @app_commands.describe(level="Volume from 0 to 100")
    @app_commands.guild_only()
    async def volume(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 0, 100],
    ) -> None:
        if not 0 <= int(level) <= 100:
            raise UserError("Volume must be between 0 and 100.")
        player, _ = await self._control_target(interaction)
        await player.set_volume(int(level))
        await interaction.response.send_message(f"Volume set to {level}%.", ephemeral=True)

    @app_commands.command(name="loop", description="Set the loop mode")
    @app_commands.describe(mode="off, track or queue")
    @app_commands.guild_only()
    async def loop(
        self,
        interaction: discord.Interaction,
        mode: Literal["off", "track", "queue"],
    ) -> None:
        player, _ = await self._control_target(interaction)
        await player.set_loop(LoopMode(mode))
        await interaction.response.send_message(f"Loop mode: **{mode}**.", ephemeral=True)

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        if not player.queue:
            raise UserError("The queue is empty.")
        player.shuffle()
        await player.persist()
        await interaction.response.send_message("Shuffled the queue.", ephemeral=True)

    @app_commands.command(name="remove", description="Remove one track from the queue")
    @app_commands.describe(position="Queue position (1 is next)")
    @app_commands.guild_only()
    async def remove(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[int, 1, 10_000],
    ) -> None:
        player, _ = await self._control_target(interaction)
        try:
            track = player.remove(position - 1)
        except IndexError as error:
            raise UserError(f"There is no track at position {position}.") from error
        await player.persist()
        await interaction.response.send_message(
            f"Removed **{discord.utils.escape_markdown(track.title)}**.", ephemeral=True
        )

    @app_commands.command(name="move", description="Move a track within the queue")
    @app_commands.describe(index="Current position (1 is next)", to="New position")
    @app_commands.guild_only()
    async def move(
        self,
        interaction: discord.Interaction,
        index: app_commands.Range[int, 1, 10_000],
        to: app_commands.Range[int, 1, 10_000],
    ) -> None:
        player, _ = await self._control_target(interaction)
        try:
            player.move(index - 1, to - 1)
        except IndexError as error:
            raise UserError("One of those positions is outside the queue.") from error
        await player.persist()
        await interaction.response.send_message(f"Moved position {index} to {to}.", ephemeral=True)

    @app_commands.command(name="clear", description="Clear the queue, keeping the current track")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        count = len(player.queue)
        player.clear_queue()
        await player.persist()
        await interaction.response.send_message(f"Cleared {count} track(s).", ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnect from voice and clear the queue")
    @app_commands.guild_only()
    async def disconnect(self, interaction: discord.Interaction) -> None:
        player, _ = await self._control_target(interaction)
        await player.disconnect(clear_queue=True)
        await interaction.response.send_message("Disconnected.", ephemeral=True)
