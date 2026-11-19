# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Entry point: ``python -m jukebox``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import discord

from .bot import JukeboxBot
from .config import Config, ConfigError, load_config
from .logging_setup import setup_logging

__all__ = ["main"]

_log = logging.getLogger(__name__)


async def _run(config: Config) -> None:
    bot = JukeboxBot(config)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, stop.set)

    start_task = asyncio.create_task(bot.start(config.token), name="discord-gateway")
    stop_task = asyncio.create_task(stop.wait(), name="shutdown-signal")
    try:
        done, _ = await asyncio.wait({start_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if start_task in done:
            # start() returns only when the client is closed; re-raise login or
            # connection failures so the process exits non-zero.
            start_task.result()
        else:
            _log.info("shutdown signal received")
            await bot.close()
            try:
                await asyncio.wait_for(start_task, timeout=config.shutdown_timeout)
            except TimeoutError:
                _log.warning("gateway task did not stop in time")
    finally:
        stop_task.cancel()
        if not bot.is_closed():
            await bot.close()


def main() -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"Configuration error:\n{error}")
        return 2

    setup_logging(config.log_level, config.log_json)
    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        return 130
    except discord.LoginFailure:
        _log.critical("Discord rejected the token; check DISCORD_TOKEN")
        return 1
    except discord.PrivilegedIntentsRequired as error:
        _log.critical(
            "a privileged gateway intent is not enabled in the Developer Portal",
            extra={"detail": str(error)},
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
