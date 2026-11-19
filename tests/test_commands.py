# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from typing import Any, cast

import pytest
from jukebox.bot import JukeboxBot
from jukebox.cogs.music import Music
from jukebox.cogs.settings import Settings
from jukebox.config import Config

REQUIRED_COMMANDS = {
    "play",
    "pause",
    "resume",
    "skip",
    "stop",
    "queue",
    "nowplaying",
    "seek",
    "volume",
    "loop",
    "shuffle",
    "remove",
    "move",
    "clear",
    "disconnect",
    "source",
    "djrole",
}


class FakeClient:
    def add_event_hook(self, *args: Any, **kwargs: Any) -> None:
        return None

    def remove_event_hooks(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeLavalink:
    client = FakeClient()


@pytest.fixture
def bot(config: Config) -> JukeboxBot:
    instance = JukeboxBot(config)
    instance.lavalink = cast(Any, FakeLavalink())
    return instance


async def test_all_commands_are_registered(bot: JukeboxBot) -> None:
    await bot.add_cog(Music(bot))
    await bot.add_cog(Settings(bot))
    names = {command.name for command in bot.tree.get_commands()}
    assert names == REQUIRED_COMMANDS


async def test_no_prefix_commands(bot: JukeboxBot) -> None:
    await bot.add_cog(Music(bot))
    await bot.add_cog(Settings(bot))
    assert bot.commands == set()


async def test_descriptions_fit_discord_limit(bot: JukeboxBot) -> None:
    await bot.add_cog(Music(bot))
    await bot.add_cog(Settings(bot))
    for command in bot.tree.get_commands():
        assert 0 < len(command.description) <= 100, command.name
