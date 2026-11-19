# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Discord embeds and small presentation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from .models import LoopMode, Track

if TYPE_CHECKING:
    from .player import GuildPlayer

__all__ = [
    "ACCENT",
    "error_embed",
    "format_duration",
    "now_playing_embed",
    "progress_bar",
    "queue_embed",
    "status_embed",
]

ACCENT = discord.Color.from_str("#5865F2")
_SUCCESS = discord.Color.from_str("#57F287")
_WARNING = discord.Color.from_str("#FEE75C")
_DANGER = discord.Color.from_str("#ED4245")

_LOOP_LABELS = {
    LoopMode.OFF: "Off",
    LoopMode.TRACK: "Track",
    LoopMode.QUEUE: "Queue",
}


def format_duration(milliseconds: int) -> str:
    """Format milliseconds as ``m:ss`` or ``h:mm:ss``."""
    total_seconds = max(0, int(milliseconds // 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def progress_bar(position_ms: int, duration_ms: int, length: int = 15) -> str:
    if duration_ms <= 0:
        return "🔴 Live"
    ratio = min(1.0, max(0.0, position_ms / duration_ms))
    index = min(length - 1, int(ratio * length))
    return "▬" * index + "🔘" + "▬" * (length - index - 1)


def _requester(guild: discord.Guild | None, track: Track) -> str | None:
    if not track.requester_id:
        return None
    member = guild.get_member(track.requester_id) if guild is not None else None
    if member is not None:
        return member.mention
    return f"<@{track.requester_id}>"


def _track_title(track: Track) -> str:
    if track.uri:
        return f"[{discord.utils.escape_markdown(track.title)}]({track.uri})"
    return discord.utils.escape_markdown(track.title)


def now_playing_embed(player: GuildPlayer, guild: discord.Guild | None) -> discord.Embed:
    track = player.current
    if track is None:
        return status_embed("Nothing playing", "The queue is empty.", color=_WARNING)

    position = player.position_ms
    embed = discord.Embed(
        title="Now playing",
        description=f"### {_track_title(track)}\n{progress_bar(position, track.duration_ms)}",
        color=ACCENT,
        url=track.uri or None,
    )
    embed.add_field(name="Artist", value=track.author or "Unknown", inline=True)
    embed.add_field(
        name="Duration",
        value="Live"
        if track.is_stream
        else f"{format_duration(position)} / {format_duration(track.duration_ms)}",
        inline=True,
    )
    embed.add_field(name="Volume", value=f"{player.volume}%", inline=True)
    embed.add_field(name="Loop", value=_LOOP_LABELS[player.loop], inline=True)
    embed.add_field(name="Queue", value=f"{len(player.queue)} track(s)", inline=True)
    embed.add_field(name="Paused", value="Yes" if player.paused else "No", inline=True)

    requester = _requester(guild, track)
    if requester:
        embed.set_footer(text=f"Requested by {requester}")
    if track.artwork_url:
        embed.set_thumbnail(url=track.artwork_url)
    return embed


def queue_embed(
    player: GuildPlayer,
    guild: discord.Guild | None,
    page: int,
    per_page: int = 10,
) -> discord.Embed:
    tracks = player.queue.as_list()
    total_pages = max(1, (len(tracks) + per_page - 1) // per_page)
    page = min(max(0, page), total_pages - 1)
    start = page * per_page
    chunk = tracks[start : start + per_page]

    lines: list[str] = []
    if player.current is not None:
        lines.append(
            f"**Now playing:** {_track_title(player.current)} `[{format_duration(player.current.duration_ms)}]`"
        )
        lines.append("")

    if not tracks:
        lines.append("The queue is empty. Use `/play` to add something.")
    else:
        for offset, track in enumerate(chunk, start=start + 1):
            suffix = " *(live)*" if track.is_stream else f" `[{format_duration(track.duration_ms)}]`"
            lines.append(
                f"`{offset:>3}.` {_track_title(track)} — {discord.utils.escape_markdown(track.author)}{suffix}"
            )

    embed = discord.Embed(
        title="Queue",
        description="\n".join(lines),
        color=ACCENT,
    )
    total_ms = sum(track.duration_ms for track in tracks)
    embed.set_footer(
        text=(
            f"Page {page + 1}/{total_pages} • {len(tracks)} queued • "
            f"{format_duration(total_ms)} total • Loop: {_LOOP_LABELS[player.loop]}"
        )
    )
    if player.current is not None and player.current.artwork_url:
        embed.set_thumbnail(url=player.current.artwork_url)
    return embed


def status_embed(title: str, description: str, *, color: discord.Color = _SUCCESS) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def error_embed(message: str, hint: str | None = None) -> discord.Embed:
    embed = discord.Embed(title="Could not do that", description=message, color=_DANGER)
    if hint:
        embed.add_field(name="What to try", value=hint, inline=False)
    return embed
