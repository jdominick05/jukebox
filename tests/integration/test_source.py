# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import pytest

from .harness import World

pytestmark = pytest.mark.integration


async def test_source_returns_configured_repository(world: World) -> None:
    result = await world.invoke("source", world.interaction(1))
    assert result.error is None
    assert result.final_embed is not None
    assert "https://example.com/jukebox" in (result.final_embed.description or "")
    assert "AGPL-3.0-or-later" in (result.final_embed.description or "")
