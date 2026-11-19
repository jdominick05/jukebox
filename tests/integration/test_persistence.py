# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
WORKER = "tests.integration.restart_worker"


def run_worker(mode: str, database: Path, audio_url: str, stack) -> dict[str, object]:
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            WORKER,
            mode,
            "--database",
            str(database),
            "--audio-url",
            audio_url,
            "--port",
            str(stack.port),
            "--password",
            "test-password",
        ],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, f"worker failed:\n{result.stdout}\n{result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert lines, f"worker produced no JSON:\n{result.stdout}\n{result.stderr}"
    return json.loads(lines[-1])


async def test_queue_volume_loop_and_position_survive_process_restart(tmp_path: Path, stack, audio) -> None:
    database = tmp_path / "persist.db"
    saved = run_worker("save", database, audio("tone-long.wav"), stack)
    assert saved["saved"] is True
    assert saved["volume"] == 55
    assert saved["loop"] == "queue"
    assert saved["position_ms"] >= 1000
    assert saved["current"] is not None

    restored = run_worker("restore", database, audio("tone-long.wav"), stack)
    assert restored["restored"] is True
    assert restored["volume"] == 55
    assert restored["loop"] == "queue"
    assert restored["position_ms"] >= 1000
    assert restored["current"] is not None
    assert restored["current"]["uri"] == audio("tone-long.wav")
    assert len(restored["queue"]) == 1
    assert restored["voice_channel_id"] is not None
    assert restored["notifications"] >= 1


async def test_sigterm_saves_state_before_exit(tmp_path: Path, stack, audio) -> None:
    result = run_worker("sigterm", tmp_path / "sigterm.db", audio("tone-long.wav"), stack)
    assert result["saved"] is True
    snapshot = result["snapshot"]
    assert snapshot is not None
    assert snapshot["volume"] == 55
    assert snapshot["loop"] == "queue"
    assert snapshot["current"] is not None
