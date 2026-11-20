# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""A text search must list candidates, not start every hit at once."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import lavalink
from jukebox.cogs.music import Music
from jukebox.config import load_config


class _Client:
    def add_event_hook(self, *args: object, **kwargs: object) -> None:
        return None


class _Followup:
    def __init__(self) -> None:
        self.sent: list[SimpleNamespace] = []

    async def send(self, content: str | None = None, **kwargs: object) -> SimpleNamespace:
        message = SimpleNamespace(embed=kwargs.get("embed"), view=kwargs.get("view"))
        self.sent.append(message)
        return message


class _Player:
    def __init__(self, voice_channel_id: int) -> None:
        self.voice_channel_id = voice_channel_id
        self.text_channel_id: int | None = None
        self.current = None
        self.paused = False
        self.enqueue = AsyncMock(side_effect=lambda tracks: (len(tracks), 0))
        self.connect = AsyncMock()


def _audio(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        track=f"encoded-{index}",
        raw={},
        identifier=f"id-{index}",
        is_seekable=True,
        author="Artist",
        duration=180_000,
        is_stream=False,
        title=f"Song {index}",
        uri=None,
        artwork_url=None,
        source_name="deezer",
    )


def _build(
    load_type: lavalink.LoadType, count: int, *, playlist: bool = False
) -> tuple[Music, object, _Player, _Followup]:
    voice = SimpleNamespace(id=7)
    user = SimpleNamespace(
        id=42,
        voice=SimpleNamespace(channel=voice),
        roles=[],
        guild_permissions=SimpleNamespace(manage_guild=False),
    )
    guild = SimpleNamespace(id=1, get_role=lambda role_id: None)
    followup = _Followup()
    interaction = SimpleNamespace(
        guild=guild,
        user=user,
        channel_id=99,
        response=SimpleNamespace(defer=AsyncMock()),
        followup=followup,
    )
    player = _Player(voice.id)
    tracks = [_audio(index) for index in range(count)]
    result = SimpleNamespace(
        load_type=load_type,
        tracks=tracks,
        playlist_info=SimpleNamespace(name="My playlist") if playlist else None,
        error=None,
    )
    config = load_config(
        {
            "DISCORD_TOKEN": "test-token",
            "REPO_URL": "https://example.com/jukebox",
            "LAVALINK_PASSWORD": "test-password",
            "DEFAULT_SOURCE": "deezer",
            "SOURCE_DEEZER": "true",
            "DEEZER_ARL": "arl",
            "DEEZER_MASTER_DECRYPTION_KEY": "key",
            "SOURCE_YOUTUBE": "false",
        }
    )
    service = SimpleNamespace(client=_Client(), get_tracks=AsyncMock(return_value=result))
    bot = SimpleNamespace(
        lavalink=service,
        config=config,
        dj_role_id=lambda guild_id: None,
        get_player=lambda guild_id: player,
        create_player=lambda guild_id: player,
    )
    return Music(bot), interaction, player, followup  # type: ignore[arg-type]


async def test_search_does_not_auto_play_every_hit() -> None:
    cog, interaction, player, followup = _build(lavalink.LoadType.SEARCH, 25)

    await Music.play.callback(cog, interaction, "daft punk")  # type: ignore[arg-type]

    player.enqueue.assert_not_awaited()
    assert len(followup.sent) == 1
    message = followup.sent[0]
    assert message.view is not None
    assert isinstance(message.embed, discord.Embed)
    assert message.embed.title == "Pick a track"
    selects = [child for child in message.view.children if isinstance(child, discord.ui.Select)]
    assert len(selects[0].options) == 25


async def test_playlist_url_still_queues_every_track() -> None:
    cog, interaction, player, followup = _build(lavalink.LoadType.PLAYLIST, 3, playlist=True)

    await Music.play.callback(cog, interaction, "https://www.deezer.com/playlist/1")  # type: ignore[arg-type]

    player.enqueue.assert_awaited_once()
    assert len(player.enqueue.await_args.args[0]) == 3
    assert followup.sent[0].view is None


async def test_single_track_url_plays_immediately() -> None:
    cog, interaction, player, followup = _build(lavalink.LoadType.TRACK, 1)

    await Music.play.callback(cog, interaction, "https://www.deezer.com/track/1")  # type: ignore[arg-type]

    player.enqueue.assert_awaited_once()
    assert len(player.enqueue.await_args.args[0]) == 1
    assert followup.sent[0].view is None
