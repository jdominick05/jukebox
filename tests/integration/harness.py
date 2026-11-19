# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Discord-side test doubles and a small world builder for Tier 1.

Only Discord is faked.  Command callbacks, embeds, queue views, SQLite, the
Lavalink client and the Lavalink node are the real implementations.  Fake
objects expose exactly the attributes the bot touches, which keeps the tests
honest about what Discord data the bot actually needs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import discord
from jukebox.bot import JukeboxBot
from jukebox.cogs.music import Music
from jukebox.cogs.settings import Settings
from jukebox.config import Config, Source, load_config
from jukebox.lavalink_service import LavalinkService
from jukebox.models import Track

BOT_USER_ID = 900_000_000_000_000_001
PASSWORD = "test-password"


# --------------------------------------------------------------------- Discord


@dataclass
class FakePermissions:
    manage_guild: bool = False
    connect: bool = True
    speak: bool = True


@dataclass
class FakeRole:
    id: int
    name: str


class FakeVoiceState:
    def __init__(self, channel: FakeVoiceChannel | None) -> None:
        self.channel = channel


class FakeMember:
    def __init__(
        self,
        member_id: int,
        name: str,
        *,
        bot: bool = False,
        roles: list[FakeRole] | None = None,
        manage_guild: bool = False,
        voice_channel: FakeVoiceChannel | None = None,
    ) -> None:
        self.id = member_id
        self.name = name
        self.bot = bot
        self.roles = roles or []
        self.guild_permissions = FakePermissions(manage_guild=manage_guild)
        self.voice = FakeVoiceState(voice_channel)

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def __str__(self) -> str:
        return self.name


class FakeVoiceChannel:
    def __init__(self, channel_id: int, name: str, guild: FakeGuild) -> None:
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.members: list[FakeMember] = []

    def permissions_for(self, member: FakeMember) -> FakePermissions:
        return FakePermissions()

    def __str__(self) -> str:
        return self.name


class FakeMessage:
    def __init__(
        self,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
    ) -> None:
        self.content = content
        self.embed = embed
        self.view = view
        self.edits: list[dict[str, Any]] = []

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)


class FakeTextChannel:
    def __init__(self, channel_id: int, name: str, guild: FakeGuild) -> None:
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.messages: list[FakeMessage] = []

    async def send(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        **kwargs: Any,
    ) -> FakeMessage:
        message = FakeMessage(content=content, embed=embed)
        self.messages.append(message)
        return message

    def __str__(self) -> str:
        return self.name


class FakeGuild:
    def __init__(self, guild_id: int, name: str) -> None:
        self.id = guild_id
        self.name = name
        self.roles: dict[int, FakeRole] = {}
        self.channels: dict[int, Any] = {}
        self.members: dict[int, FakeMember] = {}
        self.voice_calls: list[FakeVoiceChannel | None] = []
        self.me: FakeMember | None = None
        self.text_channel: FakeTextChannel | None = None
        self.voice_channel: FakeVoiceChannel | None = None

    async def change_voice_state(self, *, channel: FakeVoiceChannel | None, self_deaf: bool = False) -> None:
        self.voice_calls.append(channel)
        if self.me is not None:
            self.me.voice.channel = channel

    def get_role(self, role_id: int) -> FakeRole | None:
        return self.roles.get(role_id)

    def get_channel(self, channel_id: int | None) -> Any:
        return self.channels.get(channel_id) if channel_id is not None else None

    def get_member(self, member_id: int) -> FakeMember | None:
        return self.members.get(member_id)

    def __str__(self) -> str:
        return self.name


# ------------------------------------------------------------------ interaction


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.sent: list[FakeMessage] = []
        self.edits: list[dict[str, Any]] = []

    def is_done(self) -> bool:
        return self.deferred or bool(self.sent)

    async def defer(self, *, thinking: bool = False, ephemeral: bool = False) -> None:
        self.deferred = True

    async def send_message(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> FakeMessage:
        message = FakeMessage(content=content, embed=embed, view=view)
        self.sent.append(message)
        return message

    async def edit_message(
        self,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        **kwargs: Any,
    ) -> None:
        self.edits.append({"content": content, "embed": embed, "view": view})


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[FakeMessage] = []

    async def send(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> FakeMessage:
        message = FakeMessage(content=content, embed=embed)
        self.sent.append(message)
        return message


class FakeCommand:
    qualified_name = "test"


class FakeInteraction:
    def __init__(self, guild: FakeGuild, user: FakeMember, channel: FakeTextChannel) -> None:
        self.guild = guild
        self.user = user
        self.channel = channel
        self.channel_id = channel.id
        self.guild_id = guild.id
        self.command = FakeCommand()
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.error: Exception | None = None

    @property
    def embeds(self) -> list[discord.Embed]:
        return [
            message.embed
            for message in [*self.response.sent, *self.followup.sent]
            if message.embed is not None
        ]

    @property
    def final_embed(self) -> discord.Embed | None:
        return self.embeds[-1] if self.embeds else None

    @property
    def contents(self) -> list[str]:
        return [message.content for message in [*self.response.sent, *self.followup.sent] if message.content]

    async def original_response(self) -> FakeMessage:
        if self.response.sent:
            return self.response.sent[-1]
        return FakeMessage()


# ------------------------------------------------------------------------ world


@dataclass
class World:
    bot: JukeboxBot
    cog: Music
    settings: Settings
    db: Any
    guilds: dict[int, FakeGuild]
    service: LavalinkService
    text_channels: dict[int, FakeTextChannel]
    voice_channels: dict[int, FakeVoiceChannel]

    def guild(self, guild_id: int = 1) -> FakeGuild:
        return self.guilds[guild_id]

    def text(self, guild_id: int = 1) -> FakeTextChannel:
        return self.text_channels[guild_id]

    def voice(self, guild_id: int = 1) -> FakeVoiceChannel:
        return self.voice_channels[guild_id]

    def interaction(
        self,
        guild_id: int = 1,
        *,
        user_id: int | None = None,
        in_voice: bool = True,
    ) -> FakeInteraction:
        guild = self.guild(guild_id)
        user = guild.members[user_id] if user_id is not None else guild.members[1000 + guild_id]
        if in_voice:
            user.voice.channel = self.voice(guild_id)
        else:
            user.voice.channel = None
        return FakeInteraction(guild, user, self.text(guild_id))

    async def invoke(self, command_name: str, interaction: FakeInteraction, *args: Any) -> FakeInteraction:
        name = "queue_command" if command_name == "queue" else command_name
        owner = self.settings if hasattr(type(self.settings), name) else self.cog
        command = getattr(type(owner), name)
        try:
            await command.callback(owner, interaction, *args)
        except Exception as error:
            interaction.error = error
            await self.bot._on_app_command_error(interaction, error)
        return interaction

    async def play(
        self,
        guild_id: int,
        url: str,
        *,
        user_id: int | None = None,
        in_voice: bool = True,
    ) -> FakeInteraction:
        return await self.invoke("play", self.interaction(guild_id, user_id=user_id, in_voice=in_voice), url)

    def player(self, guild_id: int = 1) -> Any:
        return self.bot.players[guild_id]

    async def load_track(self, url: str, requester_id: int = 1001) -> Track:
        result = await self.service.get_tracks(url)
        if not result.tracks:
            raise AssertionError(f"Lavalink could not load {url}: {result.load_type}")
        return Track.from_lavalink(result.tracks[0], requester_id)

    async def wait_for(
        self,
        predicate: Callable[[], bool],
        *,
        timeout: float = 5.0,  # noqa: ASYNC109 - polling deadline, not asyncio timeout
        interval: float = 0.02,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(interval)
        raise AssertionError("condition was not met before the timeout")


def make_config(
    database_path: str,
    *,
    idle_timeout: int = 0,
    empty_timeout: int = 0,
) -> Config:
    config = load_config(
        {
            "DISCORD_TOKEN": "test-token",
            "REPO_URL": "https://example.com/jukebox",
            "LAVALINK_PASSWORD": PASSWORD,
        }
    )
    return replace(
        config,
        database_path=database_path,
        default_source=Source.YOUTUBE,
        enabled_sources=frozenset({Source.HTTP, Source.YOUTUBE}),
        idle_timeout=idle_timeout,
        empty_timeout=empty_timeout,
        max_queue_size=60,
        health_port=0,
        state_flush_interval=5,
    )


def build_world(
    config: Config,
    service: LavalinkService,
    db: Any,
    *,
    guild_ids: tuple[int, ...] = (1,),
    dj_role: bool = False,
) -> World:
    bot = JukeboxBot(config)
    bot_member = FakeMember(BOT_USER_ID, "Jukebox#0001", bot=True)
    bot.ws = SimpleNamespace(latency=0.01)  # type: ignore[assignment]
    bot.lavalink = service
    bot.db = db
    bot.is_ready = lambda: True  # type: ignore[method-assign]
    bot.players.clear()
    bot.dj_roles.clear()

    guilds: dict[int, FakeGuild] = {}
    text_channels: dict[int, FakeTextChannel] = {}
    voice_channels: dict[int, FakeVoiceChannel] = {}

    for guild_id in guild_ids:
        guild = FakeGuild(guild_id, f"Guild {guild_id}")
        default_role = FakeRole(4000 + guild_id, "@everyone")
        guild.roles[default_role.id] = default_role
        if dj_role:
            role = FakeRole(5000 + guild_id, "DJ")
            guild.roles[role.id] = role

        text = FakeTextChannel(2000 + guild_id, "music", guild)
        voice = FakeVoiceChannel(3000 + guild_id, "Voice", guild)
        guild.text_channel = text
        guild.voice_channel = voice
        guild.channels[text.id] = text
        guild.channels[voice.id] = voice

        member = FakeMember(1000 + guild_id, f"User {guild_id}", voice_channel=voice)
        guild.members[member.id] = member
        guild.members[bot_member.id] = bot_member
        guild.me = bot_member
        voice.members = [bot_member, member]

        guilds[guild_id] = guild
        text_channels[guild_id] = text
        voice_channels[guild_id] = voice

    bot._connection = SimpleNamespace(user=bot_member, guilds=list(guilds.values()))
    bot.get_guild = guilds.get  # type: ignore[method-assign]
    bot.get_channel = lambda channel_id: next(  # type: ignore[method-assign]
        (
            channel
            for guild in guilds.values()
            for channel in guild.channels.values()
            if channel.id == channel_id
        ),
        None,
    )

    cog = Music(bot)
    settings = Settings(bot)
    return World(
        bot=bot,
        cog=cog,
        settings=settings,
        db=db,
        guilds=guilds,
        service=service,
        text_channels=text_channels,
        voice_channels=voice_channels,
    )
