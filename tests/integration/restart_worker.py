# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Subprocess helper for the persistence and SIGTERM tests.

Run as ``python -m tests.integration.restart_worker <mode> ...``.  It fakes only
Discord, uses the real SQLite database and the real Lavalink node, and prints a
single JSON object on stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from dataclasses import replace

from jukebox import player as player_module
from jukebox.db import Database
from jukebox.lavalink_service import LavalinkService
from jukebox.models import LoopMode

from .harness import BOT_USER_ID, World, build_world, make_config


def summary(world: World, guild_id: int = 1) -> dict[str, object]:
    player = world.player(guild_id)
    return {
        "voice_channel_id": player.voice_channel_id,
        "volume": player.volume,
        "loop": player.loop.value,
        "position_ms": player.position_ms,
        "current": None
        if player.current is None
        else {"title": player.current.title, "uri": player.current.uri},
        "queue": [{"title": track.title, "uri": track.uri} for track in player.queue.as_list()],
    }


async def build(args: argparse.Namespace) -> tuple[World, LavalinkService, Database]:
    player_module.VOICE_CONNECT_TIMEOUT = 0.05
    config = make_config(args.database)
    config = replace(
        config,
        lavalink=replace(
            config.lavalink,
            host=args.host,
            port=args.port,
            password=args.password,
            secure=False,
        ),
    )
    service = LavalinkService(config.lavalink, BOT_USER_ID)
    await service.start()
    if not await service.wait_ready(25):
        raise RuntimeError("Lavalink did not become ready")
    database = Database(args.database)
    await database.connect()
    world = build_world(config, service, database, guild_ids=(1,))
    return world, service, database


async def run(args: argparse.Namespace) -> None:
    world, service, database = await build(args)

    if args.mode == "restore":
        snapshots = await database.load_snapshots()
        if not snapshots:
            raise RuntimeError("no snapshot to restore")
        await world.bot._restore_one(snapshots[0])
        player = world.player(1)
        result = {
            "restored": True,
            "current": None
            if player.current is None
            else {"title": player.current.title, "uri": player.current.uri},
            "queue": [{"title": track.title, "uri": track.uri} for track in player.queue.as_list()],
            "volume": player.volume,
            "loop": player.loop.value,
            "position_ms": player._position_ms,
            "voice_channel_id": player.voice_channel_id,
            "notifications": len(world.text(1).messages),
        }
        print(json.dumps(result), flush=True)
        await service.close()
        await database.close()
        return

    interaction = await world.play(1, args.audio_url)
    if interaction.error is not None:
        raise RuntimeError(f"play failed: {interaction.error!r}")
    player = world.player(1)
    player.volume = 55
    await player.set_loop(LoopMode.QUEUE)
    second = await world.load_track(args.audio_url, requester_id=1002)
    player.queue.add(second)
    await player.persist()

    if args.mode == "save":
        await asyncio.sleep(0.2)
        ll = player._ll
        if ll is None or ll.current is None:
            raise RuntimeError("Lavalink did not report the track as current")
        ll.channel_id = player.voice_channel_id
        await ll.update_state({"position": 1500, "time": 0})
        await player.persist()
        print(json.dumps({"saved": True, **summary(world)}), flush=True)
        # Simulate a hard process stop: no close(), no WAL checkpoint.
        os._exit(0)

    if args.mode == "sigterm":
        done = asyncio.Event()

        async def close_on_signal() -> None:
            await player.close()
            done.set()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(close_on_signal()))
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(done.wait(), timeout=5)
        snapshots = await database.load_snapshots()
        result = {
            "saved": bool(snapshots),
            "snapshot": None
            if not snapshots
            else {
                "volume": snapshots[0].volume,
                "loop": snapshots[0].loop_mode.value,
                "position_ms": snapshots[0].position_ms,
                "current": None if snapshots[0].current is None else snapshots[0].current.title,
            },
        }
        print(json.dumps(result), flush=True)
        await service.close()
        await database.close()
        return

    raise RuntimeError(f"unknown mode {args.mode}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["save", "restore", "sigterm"])
    parser.add_argument("--database", required=True)
    parser.add_argument("--audio-url", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--password", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
