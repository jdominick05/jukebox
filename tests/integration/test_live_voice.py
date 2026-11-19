# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Opt-in live voice smoke test.

This is the only test that proves the real Discord gateway, voice connection and
DAVE negotiation work.  It is skipped unless all three TEST_* variables are set.
Run it with:

    TEST_BOT_TOKEN=... TEST_GUILD_ID=... TEST_VOICE_CHANNEL_ID=... \\
        pytest tests/integration/test_live_voice.py -q -s
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import replace

import pytest
from jukebox.bot import JukeboxBot
from jukebox.models import Track

from .harness import PASSWORD, make_config

pytestmark = [pytest.mark.integration, pytest.mark.live]

TOKEN = os.environ.get("TEST_BOT_TOKEN", "")
GUILD_ID = int(os.environ.get("TEST_GUILD_ID", "0") or 0)
VOICE_CHANNEL_ID = int(os.environ.get("TEST_VOICE_CHANNEL_ID", "0") or 0)

if not TOKEN or not GUILD_ID or not VOICE_CHANNEL_ID:
    pytest.skip(
        "live voice test is opt-in: set TEST_BOT_TOKEN, TEST_GUILD_ID and TEST_VOICE_CHANNEL_ID",
        allow_module_level=True,
    )


async def _wait(
    predicate,
    timeout: float,  # noqa: ASYNC109 - polling deadline
    description: str,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"timed out waiting for {description}")


async def test_live_voice_playback(stack, tmp_path) -> None:
    if not TOKEN or not GUILD_ID or not VOICE_CHANNEL_ID:
        pytest.skip("set TEST_BOT_TOKEN, TEST_GUILD_ID and TEST_VOICE_CHANNEL_ID")

    config = make_config(str(tmp_path / "live.db"))
    config = replace(
        config,
        token=TOKEN,
        guild_id=GUILD_ID,
        lavalink=replace(
            config.lavalink,
            host="127.0.0.1",
            port=stack.port,
            password=PASSWORD,
            secure=False,
        ),
        restore_on_start=False,
    )
    bot = JukeboxBot(config)
    start_task = asyncio.create_task(bot.start(TOKEN))
    try:
        await asyncio.wait_for(bot.wait_until_ready(), timeout=90)
        guild = bot.get_guild(GUILD_ID)
        assert guild is not None, "the test bot is not a member of TEST_GUILD_ID"
        channel = guild.get_channel(VOICE_CHANNEL_ID)
        assert channel is not None, "TEST_VOICE_CHANNEL_ID is not visible to the bot"

        player = bot.create_player(GUILD_ID)
        player.text_channel_id = getattr(channel, "id", None)
        await player.connect(channel)  # type: ignore[arg-type]
        await _wait(
            lambda: player._ll is not None and player._ll.channel_id == VOICE_CHANNEL_ID,
            20,
            "the Lavalink voice connection",
        )

        result = await bot.lavalink.get_tracks(stack.audio_url("tone-long.wav"))
        assert result.tracks, f"fixture track failed to load: {result.load_type}"
        track = Track.from_lavalink(result.tracks[0], 1)
        await player.start_track(track)

        await _wait(lambda: player.position_ms > 500, 25, "audible playback progress")
        assert player._ll is not None
        assert player._ll.current is not None
        assert player.position_ms > 500
    finally:
        try:
            if GUILD_ID in bot.players:
                await bot.players[GUILD_ID].disconnect(clear_queue=True)
        finally:
            await bot.close()
            start_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await start_task
