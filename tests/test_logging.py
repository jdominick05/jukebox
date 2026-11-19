# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import json
import logging

from jukebox.logging_setup import JsonFormatter


def test_json_formatter_includes_extras() -> None:
    record = logging.LogRecord(
        name="jukebox.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="played %s",
        args=("song",),
        exc_info=None,
    )
    record.guild_id = 42
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["message"] == "played song"
    assert payload["guild_id"] == 42
    assert payload["logger"] == "jukebox.test"


def test_json_formatter_serialises_unusual_values() -> None:
    record = logging.LogRecord(
        name="jukebox.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="value",
        args=(),
        exc_info=None,
    )
    record.value = object()
    payload = json.loads(JsonFormatter().format(record))
    assert "object at 0x" in payload["value"]
