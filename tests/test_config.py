# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest
from jukebox.config import ConfigError, Source, load_config


def test_defaults_are_stable(base_env: dict[str, str]) -> None:
    config = load_config(base_env)
    assert config.default_source is Source.YOUTUBE
    assert config.lavalink.port == 2333
    assert config.lavalink.resume_timeout == 300
    assert config.default_volume == 70
    assert config.max_queue_size == 1000
    assert config.health_port == 8080
    assert Source.SPOTIFY not in config.enabled_sources
    assert Source.YOUTUBE in config.enabled_sources
    assert config.restore_on_start is True


def test_missing_token_is_rejected(base_env: dict[str, str]) -> None:
    base_env.pop("DISCORD_TOKEN")
    with pytest.raises(ConfigError, match="DISCORD_TOKEN is required"):
        load_config(base_env)


def test_missing_repo_url_is_rejected(base_env: dict[str, str]) -> None:
    base_env.pop("REPO_URL")
    with pytest.raises(ConfigError, match="REPO_URL is required"):
        load_config(base_env)


def test_example_password_is_rejected(base_env: dict[str, str]) -> None:
    base_env["LAVALINK_PASSWORD"] = "youshallnotpass"
    with pytest.raises(ConfigError, match="example password"):
        load_config(base_env)


def test_bad_integer_is_rejected(base_env: dict[str, str]) -> None:
    base_env["MAX_QUEUE_SIZE"] = "many"
    with pytest.raises(ConfigError, match="MAX_QUEUE_SIZE must be an integer"):
        load_config(base_env)


def test_bad_boolean_is_rejected(base_env: dict[str, str]) -> None:
    base_env["SOURCE_SPOTIFY"] = "maybe"
    with pytest.raises(ConfigError, match="SOURCE_SPOTIFY must be a boolean"):
        load_config(base_env)


def test_disabled_default_source_is_rejected(base_env: dict[str, str]) -> None:
    base_env["DEFAULT_SOURCE"] = "soundcloud"
    base_env["SOURCE_SOUNDCLOUD"] = "false"
    with pytest.raises(ConfigError, match="DEFAULT_SOURCE 'soundcloud' is disabled"):
        load_config(base_env)


def test_default_source_without_search_is_rejected(base_env: dict[str, str]) -> None:
    base_env["DEFAULT_SOURCE"] = "bandcamp"
    with pytest.raises(ConfigError, match="does not support text search"):
        load_config(base_env)


def test_spotify_requires_credentials(base_env: dict[str, str]) -> None:
    base_env["SOURCE_SPOTIFY"] = "true"
    with pytest.raises(ConfigError, match="SPOTIFY_CLIENT_ID"):
        load_config(base_env)


def test_spotify_requires_youtube_for_mirroring(base_env: dict[str, str]) -> None:
    base_env.update(
        {
            "SOURCE_SPOTIFY": "true",
            "SPOTIFY_CLIENT_ID": "id",
            "SPOTIFY_CLIENT_SECRET": "secret",
            "SOURCE_YOUTUBE": "false",
        }
    )
    with pytest.raises(ConfigError, match="resolve to YouTube"):
        load_config(base_env)


def test_deezer_requires_arl(base_env: dict[str, str]) -> None:
    base_env["SOURCE_DEEZER"] = "true"
    with pytest.raises(ConfigError, match="DEEZER_ARL"):
        load_config(base_env)


def test_deezer_with_arl_is_enabled(base_env: dict[str, str]) -> None:
    base_env.update(
        {
            "SOURCE_DEEZER": "true",
            "DEEZER_ARL": "arl-cookie",
            "DEEZER_MASTER_DECRYPTION_KEY": "master-key",
        }
    )
    config = load_config(base_env)
    assert Source.DEEZER in config.enabled_sources


def test_volume_range_is_enforced(base_env: dict[str, str]) -> None:
    base_env["DEFAULT_VOLUME"] = "101"
    with pytest.raises(ConfigError, match="DEFAULT_VOLUME"):
        load_config(base_env)


def test_durations_are_parsed(base_env: dict[str, str]) -> None:
    base_env.update(
        {
            "IDLE_TIMEOUT": "600",
            "EMPTY_TIMEOUT": "0",
            "STATE_FLUSH_INTERVAL": "30",
            "SHUTDOWN_TIMEOUT": "9.5",
        }
    )
    config = load_config(base_env)
    assert config.idle_timeout == 600
    assert config.empty_timeout == 0
    assert config.state_flush_interval == 30
    assert config.shutdown_timeout == 9.5


def test_log_level_validation(base_env: dict[str, str]) -> None:
    base_env["LOG_LEVEL"] = "LOUD"
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_config(base_env)
