# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from dataclasses import replace

import pytest
from jukebox.config import Config, Source
from jukebox.errors import SourceDisabled, UserError
from jukebox.sources import resolve_query


def test_plain_text_uses_default_source(config: Config) -> None:
    resolved = resolve_query("never gonna give you up", config)
    assert resolved.identifier == "ytsearch:never gonna give you up"
    assert resolved.source is Source.YOUTUBE
    assert resolved.is_url is False


def test_plain_text_uses_configured_source(config: Config) -> None:
    custom = replace(
        config,
        default_source=Source.SOUNDCLOUD,
        enabled_sources=config.enabled_sources | {Source.SOUNDCLOUD},
    )
    resolved = resolve_query("lofi", custom)
    assert resolved.identifier == "scsearch:lofi"


def test_youtube_url(config: Config) -> None:
    resolved = resolve_query("https://www.youtube.com/watch?v=abc", config)
    assert resolved.source is Source.YOUTUBE
    assert resolved.is_url is True


def test_youtu_be_short_link(config: Config) -> None:
    resolved = resolve_query("https://youtu.be/abc", config)
    assert resolved.source is Source.YOUTUBE


def test_direct_audio_url(config: Config) -> None:
    resolved = resolve_query("https://cdn.example.com/song.flac?x=1", config)
    assert resolved.source is Source.HTTP
    assert resolved.is_url is True


def test_disabled_source_is_reported(config: Config) -> None:
    with pytest.raises(SourceDisabled, match="Spotify"):
        resolve_query("https://open.spotify.com/track/abc", config)


def test_disabled_http_is_reported(config: Config) -> None:
    custom = replace(config, enabled_sources=config.enabled_sources - {Source.HTTP})
    with pytest.raises(SourceDisabled, match="HTTP audio"):
        resolve_query("https://cdn.example.com/song.mp3", custom)


def test_unknown_url_is_rejected(config: Config) -> None:
    with pytest.raises(UserError, match="not from a supported source"):
        resolve_query("https://example.com/page", config)


def test_unsupported_scheme_is_rejected(config: Config) -> None:
    with pytest.raises(UserError, match="http"):
        resolve_query("ftp://example.com/song.mp3", config)


def test_empty_query_is_rejected(config: Config) -> None:
    with pytest.raises(UserError, match="track name"):
        resolve_query("   ", config)


def test_bandcamp_url(config: Config) -> None:
    resolved = resolve_query("https://artist.bandcamp.com/track/song", config)
    assert resolved.source is Source.BANDCAMP
