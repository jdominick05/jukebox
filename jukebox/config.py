# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Environment-driven configuration with strict validation.

Every setting is read from the process environment.  Secrets never live in a
file that is committed to the repository (see ``.env.example``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "SEARCH_PREFIXES",
    "SOURCE_LABELS",
    "Config",
    "ConfigError",
    "LavalinkConfig",
    "Source",
    "load_config",
]


class ConfigError(RuntimeError):
    """Raised when the environment does not describe a usable configuration."""


class Source(StrEnum):
    """Audio sources the bot can route a query or URL to."""

    YOUTUBE = "youtube"
    YOUTUBE_MUSIC = "youtube_music"
    SOUNDCLOUD = "soundcloud"
    BANDCAMP = "bandcamp"
    HTTP = "http"
    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    DEEZER = "deezer"


SEARCH_PREFIXES: dict[Source, str] = {
    Source.YOUTUBE: "ytsearch:",
    Source.YOUTUBE_MUSIC: "ytmsearch:",
    Source.SOUNDCLOUD: "scsearch:",
    Source.SPOTIFY: "spsearch:",
    Source.APPLE_MUSIC: "amsearch:",
    Source.DEEZER: "dzsearch:",
}

SOURCE_LABELS: dict[Source, str] = {
    Source.YOUTUBE: "YouTube",
    Source.YOUTUBE_MUSIC: "YouTube Music",
    Source.SOUNDCLOUD: "SoundCloud",
    Source.BANDCAMP: "Bandcamp",
    Source.HTTP: "HTTP audio",
    Source.SPOTIFY: "Spotify",
    Source.APPLE_MUSIC: "Apple Music",
    Source.DEEZER: "Deezer",
}

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}


@dataclass(frozen=True, slots=True)
class LavalinkConfig:
    host: str
    port: int
    password: str
    secure: bool
    region: str
    name: str
    resume_timeout: int


@dataclass(frozen=True, slots=True)
class Config:
    token: str
    repo_url: str
    guild_id: int | None
    database_path: str
    default_source: Source
    enabled_sources: frozenset[Source]
    idle_timeout: int
    empty_timeout: int
    default_volume: int
    max_queue_size: int
    state_flush_interval: int
    restore_on_start: bool
    log_level: str
    log_json: bool
    health_host: str
    health_port: int
    shutdown_timeout: float
    lavalink: LavalinkConfig


def _env(env: Mapping[str, str], key: str, default: str = "") -> str:
    return env.get(key, default).strip()


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = _env(env, key)
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    raise ConfigError(f"{key} must be a boolean (true/false), got {raw!r}")


def _int(env: Mapping[str, str], key: str, default: int, *, minimum: int = 0) -> int:
    raw = _env(env, key)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from error
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _float(env: Mapping[str, str], key: str, default: float, *, minimum: float = 0.0) -> float:
    raw = _env(env, key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from error
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _optional_id(env: Mapping[str, str], key: str) -> int | None:
    raw = _env(env, key)
    if not raw or raw == "0":
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be a Discord ID (integer), got {raw!r}") from error


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Parse and validate configuration.

    Raises:
        ConfigError: if a required value is missing or a value is malformed.
    """
    env = os.environ if env is None else env
    errors: list[str] = []

    token = _env(env, "DISCORD_TOKEN")
    if not token:
        errors.append("DISCORD_TOKEN is required")
    elif any(char.isspace() for char in token):
        errors.append("DISCORD_TOKEN must not contain whitespace")

    repo_url = _env(env, "REPO_URL")
    if not repo_url:
        errors.append("REPO_URL is required (AGPL-3.0 section 13 source offer)")
    elif not repo_url.startswith(("https://", "http://")):
        errors.append("REPO_URL must be an http(s) URL")

    lavalink_password = _env(env, "LAVALINK_PASSWORD")
    if not lavalink_password:
        errors.append("LAVALINK_PASSWORD is required")
    if lavalink_password == "youshallnotpass":
        errors.append("LAVALINK_PASSWORD must not use the Lavalink example password")

    try:
        enabled_sources = frozenset(
            source
            for source, key in (
                (Source.YOUTUBE, "SOURCE_YOUTUBE"),
                (Source.SOUNDCLOUD, "SOURCE_SOUNDCLOUD"),
                (Source.BANDCAMP, "SOURCE_BANDCAMP"),
                (Source.HTTP, "SOURCE_HTTP"),
                (Source.SPOTIFY, "SOURCE_SPOTIFY"),
                (Source.APPLE_MUSIC, "SOURCE_APPLE_MUSIC"),
                (Source.DEEZER, "SOURCE_DEEZER"),
            )
            if _bool(env, key, source in {Source.YOUTUBE, Source.SOUNDCLOUD, Source.BANDCAMP, Source.HTTP})
        )
    except ConfigError as error:
        errors.append(str(error))
        enabled_sources = frozenset()

    default_raw = _env(env, "DEFAULT_SOURCE", "youtube").lower()
    try:
        default_source = Source(default_raw)
    except ValueError:
        errors.append(f"DEFAULT_SOURCE must be one of {', '.join(sorted(s.value for s in SEARCH_PREFIXES))}")
        default_source = Source.YOUTUBE
    else:
        if default_source not in SEARCH_PREFIXES:
            errors.append(f"DEFAULT_SOURCE {default_source.value!r} does not support text search")
        elif default_source not in enabled_sources:
            errors.append(
                f"DEFAULT_SOURCE {default_source.value!r} is disabled; enable it or pick another source"
            )

    if Source.SPOTIFY in enabled_sources and (
        not _env(env, "SPOTIFY_CLIENT_ID") or not _env(env, "SPOTIFY_CLIENT_SECRET")
    ):
        errors.append("SOURCE_SPOTIFY requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET")
    if Source.APPLE_MUSIC in enabled_sources and not _env(env, "APPLE_MUSIC_TOKEN"):
        errors.append("SOURCE_APPLE_MUSIC requires APPLE_MUSIC_TOKEN")
    if Source.DEEZER in enabled_sources and not _env(env, "DEEZER_ARL"):
        errors.append("SOURCE_DEEZER requires DEEZER_ARL")
    if Source.DEEZER in enabled_sources and not _env(env, "DEEZER_MASTER_DECRYPTION_KEY"):
        errors.append("SOURCE_DEEZER requires DEEZER_MASTER_DECRYPTION_KEY")
    if enabled_sources & {Source.SPOTIFY, Source.APPLE_MUSIC} and Source.DEEZER not in enabled_sources:
        errors.append("Spotify and Apple Music mirror to Deezer; enable SOURCE_DEEZER when either is enabled")

    log_level = _env(env, "LOG_LEVEL", "INFO").upper()
    if log_level not in logging.getLevelNamesMapping():
        errors.append(f"LOG_LEVEL {log_level!r} is not a valid Python logging level")

    try:
        idle_timeout = _int(env, "IDLE_TIMEOUT", 300, minimum=0)
        empty_timeout = _int(env, "EMPTY_TIMEOUT", 30, minimum=0)
        default_volume = _int(env, "DEFAULT_VOLUME", 70, minimum=0)
        max_queue_size = _int(env, "MAX_QUEUE_SIZE", 1000, minimum=1)
        state_flush_interval = _int(env, "STATE_FLUSH_INTERVAL", 15, minimum=5)
        health_port = _int(env, "HEALTH_PORT", 8080, minimum=1)
        lavalink_port = _int(env, "LAVALINK_PORT", 2333, minimum=1)
        resume_timeout = _int(env, "LAVALINK_RESUME_TIMEOUT", 300, minimum=30)
        shutdown_timeout = _float(env, "SHUTDOWN_TIMEOUT", 15.0, minimum=1.0)
        guild_id = _optional_id(env, "DISCORD_GUILD_ID")
        log_json = _bool(env, "LOG_JSON", True)
        restore_on_start = _bool(env, "RESTORE_ON_START", True)
        lavalink_secure = _bool(env, "LAVALINK_SECURE", False)
    except ConfigError as error:
        errors.append(str(error))
        idle_timeout = 300
        empty_timeout = 30
        default_volume = 70
        max_queue_size = 1000
        state_flush_interval = 15
        health_port = 8080
        lavalink_port = 2333
        resume_timeout = 300
        shutdown_timeout = 15.0
        guild_id = None
        log_json = True
        restore_on_start = True
        lavalink_secure = False
    else:
        if default_volume > 100:
            errors.append("DEFAULT_VOLUME must be between 0 and 100")
        if 0 < idle_timeout < 10:
            errors.append("IDLE_TIMEOUT must be 0 (disabled) or at least 10 seconds")
        if 0 < empty_timeout < 5:
            errors.append("EMPTY_TIMEOUT must be 0 (disabled) or at least 5 seconds")

    if errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(dict.fromkeys(errors)))

    return Config(
        token=token,
        repo_url=repo_url,
        guild_id=guild_id,
        database_path=_env(env, "DATABASE_PATH", "./data/jukebox.db"),
        default_source=default_source,
        enabled_sources=enabled_sources,
        idle_timeout=idle_timeout,
        empty_timeout=empty_timeout,
        default_volume=default_volume,
        max_queue_size=max_queue_size,
        state_flush_interval=state_flush_interval,
        restore_on_start=restore_on_start,
        log_level=log_level,
        log_json=log_json,
        health_host=_env(env, "HEALTH_HOST", "0.0.0.0"),
        health_port=health_port,
        shutdown_timeout=shutdown_timeout,
        lavalink=LavalinkConfig(
            host=_env(env, "LAVALINK_HOST", "127.0.0.1"),
            port=lavalink_port,
            password=lavalink_password,
            secure=lavalink_secure,
            region=_env(env, "LAVALINK_REGION", "default"),
            name=_env(env, "LAVALINK_NAME", "main"),
            resume_timeout=resume_timeout,
        ),
    )
