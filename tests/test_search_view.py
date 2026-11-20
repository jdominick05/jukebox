# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""A text search lists candidates instead of queueing every hit."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from jukebox.models import Track
from jukebox.search_view import (
    MAX_SUGGESTIONS,
    SearchView,
    build_suggestion_embed,
    build_suggestion_options,
)


class _Player:
    """Just enough of GuildPlayer for the view to pick a track."""

    def __init__(self) -> None:
        self.current = None
        self.paused = False
        self.enqueue = AsyncMock(return_value=(1, 0))


def test_options_list_every_candidate_in_order(make_track: Callable[..., Track]) -> None:
    tracks = [make_track(title=f"Song {i}") for i in range(4)]
    options = build_suggestion_options(tracks)
    assert [option.value for option in options] == ["0", "1", "2", "3"]
    assert options[0].label.startswith("1. Song 0")
    assert "Artist" in (options[0].description or "")


def test_options_are_capped_at_discords_limit(make_track: Callable[..., Track]) -> None:
    tracks = [make_track(title=f"Song {i}") for i in range(30)]
    assert MAX_SUGGESTIONS == 25
    assert len(build_suggestion_options(tracks)) == 25


def test_long_metadata_is_trimmed(make_track: Callable[..., Track]) -> None:
    option = build_suggestion_options([make_track(title="T" * 200, author="A" * 200)])[0]
    assert len(option.label) <= 100
    assert len(option.description or "") <= 100


def test_embed_lists_query_and_candidates(make_track: Callable[..., Track]) -> None:
    tracks = [make_track(title=f"Song {i}") for i in range(3)]
    embed = build_suggestion_embed("daft punk", tracks)
    assert "daft punk" in (embed.description or "")
    assert "Song 2" in (embed.description or "")


async def test_view_has_one_select_with_all_options(make_track: Callable[..., Track]) -> None:
    tracks = [make_track(title=f"Song {i}") for i in range(3)]
    view = SearchView(player=_Player(), tracks=tracks, author_id=42, query="q")
    selects = [child for child in view.children if isinstance(child, discord.ui.Select)]
    assert len(selects) == 1
    assert len(selects[0].options) == 3


async def test_only_the_requester_can_pick(make_track: Callable[..., Track]) -> None:
    view = SearchView(player=_Player(), tracks=[make_track("A")], author_id=42, query="q")
    response = SimpleNamespace(send_message=AsyncMock())
    allowed = await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=42), response=response))
    denied = await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=7), response=response))
    assert allowed is True
    assert denied is False
    response.send_message.assert_awaited_once()


@pytest.mark.parametrize("count", [0, 1])
async def test_view_handles_empty_and_single_result(make_track: Callable[..., Track], count: int) -> None:
    tracks = [make_track(title=f"Song {i}") for i in range(count)]
    view = SearchView(player=_Player(), tracks=tracks, author_id=42, query="q")
    selects = [child for child in view.children if isinstance(child, discord.ui.Select)]
    assert len(selects[0].options) == count
