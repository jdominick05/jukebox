# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from jukebox.config import Config, load_config
from jukebox.models import Track

BASE_ENV: dict[str, str] = {
    "DISCORD_TOKEN": "test-token",
    "REPO_URL": "https://example.com/jukebox",
    "LAVALINK_PASSWORD": "test-password",
}


@pytest.fixture
def base_env() -> dict[str, str]:
    return dict(BASE_ENV)


@pytest.fixture
def config(base_env: dict[str, str]) -> Config:
    return load_config(base_env)


@pytest.fixture
def make_track() -> Callable[..., Track]:
    def _make(
        title: str = "Track",
        *,
        duration_ms: int = 180_000,
        encoded: str | None = None,
        requester_id: int | None = 1,
        uri: str | None = "https://example.com/track",
        is_stream: bool = False,
        **info_overrides: Any,
    ) -> Track:
        raw_info: dict[str, Any] = {
            "identifier": f"id-{title}",
            "isSeekable": not is_stream,
            "author": "Artist",
            "length": duration_ms,
            "isStream": is_stream,
            "title": title,
            "uri": uri,
            "artworkUrl": None,
            "sourceName": "youtube",
        }
        raw_info.update(info_overrides)
        raw = {"encoded": encoded or f"encoded-{title}", "info": raw_info}
        return Track(
            encoded=raw["encoded"],
            identifier=str(raw_info["identifier"]),
            title=title,
            author=str(raw_info["author"]),
            duration_ms=duration_ms,
            uri=uri,
            artwork_url=None,
            is_stream=is_stream,
            source_name=str(raw_info["sourceName"]),
            requester_id=requester_id,
            raw=raw,
        )

    return _make
