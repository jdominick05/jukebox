# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Turn a text search into a pick list instead of queueing every hit.

A Lavalink ``SEARCH`` result is a set of *candidates*, not a playlist.  Queueing
all of them made ``/play <words>`` start dozens of tracks.  This view lists the
candidates and plays exactly the one the requester picks.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

import discord

from .models import Track
from .ui import format_duration, status_embed

if TYPE_CHECKING:
    from .player import GuildPlayer

__all__ = ["MAX_SUGGESTIONS", "SearchView", "build_suggestion_embed", "build_suggestion_options"]

MAX_SUGGESTIONS = 25  # Discord select menus hold at most 25 options
_TIMEOUT = 120.0


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_suggestion_options(tracks: Sequence[Track]) -> list[discord.SelectOption]:
    """One select option per candidate, capped at Discord's option limit."""
    return [
        discord.SelectOption(
            label=_trim(f"{index + 1}. {track.title}", 100),
            description=_trim(f"{track.author} · {format_duration(track.duration_ms)}", 100),
            value=str(index),
        )
        for index, track in enumerate(tracks[:MAX_SUGGESTIONS])
    ]


def build_suggestion_embed(query: str, tracks: Sequence[Track]) -> discord.Embed:
    """A readable numbered list of the same candidates shown in the select."""
    lines = [
        f"`{index + 1}.` **{discord.utils.escape_markdown(_trim(track.title, 80))}** — "
        f"{discord.utils.escape_markdown(_trim(track.author, 50))} "
        f"({format_duration(track.duration_ms)})"
        for index, track in enumerate(tracks[:MAX_SUGGESTIONS])
    ]
    description = "\n".join(lines) if lines else "No matches found."
    embed = status_embed(
        "Pick a track",
        f"Search for **{discord.utils.escape_markdown(_trim(query, 80))}** — choose one below:\n\n{description}",
    )
    embed.set_footer(text="Nothing plays until you pick. This list expires after 2 minutes.")
    return embed


class _SearchSelect(discord.ui.Select):
    async def callback(self, interaction: discord.Interaction) -> None:
        view: SearchView = self.view  # type: ignore[assignment]
        await view._choose(interaction, int(self.values[0]))


class SearchView(discord.ui.View):
    """A single-use select menu owned by the user who ran the search."""

    def __init__(
        self,
        player: GuildPlayer,
        tracks: Sequence[Track],
        author_id: int,
        query: str,
    ) -> None:
        super().__init__(timeout=_TIMEOUT)
        self.player = player
        self.author_id = author_id
        self.query = query
        self.tracks = list(tracks[:MAX_SUGGESTIONS])
        self.message: discord.Message | None = None
        select = _SearchSelect(
            placeholder="Choose a track to play",
            min_values=1,
            max_values=1,
            options=build_suggestion_options(self.tracks),
        )
        select.disabled = not self.tracks
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Run `/play` yourself to pick a track.", ephemeral=True)
            return False
        return True

    async def _choose(self, interaction: discord.Interaction, index: int) -> None:
        if index >= len(self.tracks):
            return
        track = self.tracks[index]
        added, _dropped = await self.player.enqueue([track])
        embed = (
            status_embed("Picked", f"Added **{discord.utils.escape_markdown(_trim(track.title, 80))}**.")
            if added
            else status_embed("Queue is full", "That track could not be added.")
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)
