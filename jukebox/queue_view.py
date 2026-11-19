# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Paginated queue view."""

from __future__ import annotations

import contextlib

import discord

from .player import GuildPlayer
from .ui import queue_embed

__all__ = ["QueueView"]

PER_PAGE = 10


class QueueView(discord.ui.View):
    def __init__(self, player: GuildPlayer, author_id: int) -> None:
        super().__init__(timeout=120)
        self.player = player
        self.author_id = author_id
        self.page = 0
        self.message: discord.Message | None = None
        self._sync_buttons()

    def _page_count(self) -> int:
        return max(1, (len(self.player.queue) + PER_PAGE - 1) // PER_PAGE)

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self._page_count() - 1
        self.page_button.label = f"{self.page + 1}/{self._page_count()}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Run `/queue` yourself to page through it.", ephemeral=True
            )
            return False
        return True

    async def _render(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=queue_embed(self.player, interaction.guild, self.page, PER_PAGE),
            view=self,
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        await self._render(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self._page_count() - 1, self.page + 1)
        await self._render(interaction)

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)
