# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Server settings and the AGPL source offer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..errors import UserError
from ..ui import ACCENT, status_embed

if TYPE_CHECKING:
    from ..bot import JukeboxBot

__all__ = ["Settings"]


class Settings(commands.Cog):
    def __init__(self, bot: JukeboxBot) -> None:
        self.bot = bot

    @app_commands.command(name="source", description="Get the source code for this bot")
    @app_commands.guild_only()
    async def source(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Source code",
            description=(
                f"This instance runs **{self.bot.user}**, licensed under "
                "**AGPL-3.0-or-later**.\n\n"
                f"Corresponding source: {self.bot.config.repo_url}"
            ),
            color=ACCENT,
        )
        embed.set_footer(text="AGPL-3.0 section 13: network users may obtain the source.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="djrole", description="Set or clear the DJ role for this server")
    @app_commands.describe(role="Role that may control playback; leave empty to allow everyone")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def djrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
    ) -> None:
        if interaction.guild is None:
            raise UserError("Use this in a server.")

        if role is not None and role.is_default():
            raise UserError("The @everyone role cannot be used as the DJ role.")

        await self.bot.db.set_dj_role(interaction.guild.id, role.id if role else None)
        if role is None:
            self.bot.dj_roles.pop(interaction.guild.id, None)
            message = "Cleared the DJ role. Anyone in my voice channel can control playback."
        else:
            self.bot.dj_roles[interaction.guild.id] = role.id
            message = (
                f"DJ role set to {role.mention}. Members with that role (or Manage Server) "
                "can control playback."
            )
        await interaction.response.send_message(
            embed=status_embed("DJ role updated", message),
            ephemeral=True,
        )
