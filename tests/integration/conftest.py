# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Session fixtures for the Tier 1 integration suite."""

from __future__ import annotations

import contextlib
import math
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request
import wave
from dataclasses import replace
from pathlib import Path

import pytest
from jukebox import player as player_module
from jukebox.db import Database
from jukebox.lavalink_service import LavalinkService

from .harness import (
    BOT_USER_ID,
    PASSWORD,
    World,
    build_world,
    make_config,
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = Path(__file__).resolve().parent / "docker-compose.test.yml"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
AUDIO_FILES = {
    "tone-a.wav": (4, 220.0),
    "tone-b.wav": (5, 330.0),
    "tone-c.wav": (6, 440.0),
    "tone-long.wav": (12, 550.0),
}


def generate_audio(directory: Path) -> None:
    """Write short, deterministic, copyright-free tones at test time."""
    directory.mkdir(parents=True, exist_ok=True)
    rate = 48_000
    for name, (seconds, frequency) in AUDIO_FILES.items():
        path = directory / name
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            frames = bytearray()
            for index in range(rate * seconds):
                value = int(0.25 * 32767 * math.sin(2 * math.pi * frequency * index / rate))
                frames += struct.pack("<hh", value, value)
            handle.writeframes(bytes(frames))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker CLI not found"
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"docker info failed: {error}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:300]
    return True, ""


class Stack:
    def __init__(self, project: str, port: int, audio_dir: Path) -> None:
        self.project = project
        self.port = port
        self.audio_dir = audio_dir
        self.compose_file = COMPOSE_FILE
        self.env = {
            **os.environ,
            "TEST_LAVALINK_PORT": str(port),
            "TEST_AUDIO_DIR": str(audio_dir),
        }

    def compose(self, *args: str, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["docker", "compose", "-f", str(self.compose_file), "-p", self.project, *args],
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"docker compose {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return result

    def start(self) -> None:
        self.compose("up", "-d", "--wait")
        self.wait_http()

    def wait_http(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/version"
        last_error = "no attempt"
        while time.monotonic() < deadline:
            try:
                request = urllib.request.Request(url, headers={"Authorization": PASSWORD})
                with urllib.request.urlopen(request, timeout=2) as response:
                    if response.status == 200:
                        return
                    last_error = f"HTTP {response.status}"
            except Exception as error:
                last_error = str(error)
            time.sleep(0.25)
        raise RuntimeError(f"Lavalink did not become ready: {last_error}")

    def stop_node(self) -> None:
        self.compose("stop", "lavalink")

    def start_node(self) -> None:
        self.compose("start", "lavalink")
        self.wait_http()

    def restart_node(self) -> None:
        self.compose("restart", "lavalink")
        self.wait_http()

    def audio_url(self, name: str = "tone-a.wav") -> str:
        return f"http://audio:8000/{name}"

    def capture_logs(self) -> Path:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        path = ARTIFACTS / "lavalink.log"
        result = self.compose("logs", "--no-color", check=False, timeout=60)
        path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        return path

    def cleanup(self) -> None:
        with contextlib.suppress(Exception):
            self.capture_logs()
        self.compose("down", "-v", "--remove-orphans", check=False, timeout=120)


@pytest.fixture(scope="session")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Stack:
    available, reason = docker_available()
    if not available:
        if os.environ.get("CI"):
            pytest.fail(f"Tier 1 requires Docker in CI: {reason}")
        pytest.skip(f"Tier 1 needs Docker: {reason}")

    audio_dir = tmp_path_factory.mktemp("audio")
    generate_audio(audio_dir)
    project = os.environ.get("TEST_COMPOSE_PROJECT") or f"jukebox-test-{os.getpid()}"
    instance = Stack(project, free_port(), audio_dir)
    try:
        instance.start()
    except Exception:
        instance.capture_logs()
        instance.compose("down", "-v", "--remove-orphans", check=False)
        raise
    yield instance
    instance.cleanup()


@pytest.fixture
def config(tmp_path: Path) -> object:
    return make_config(str(tmp_path / "jukebox.db"))


@pytest.fixture
async def service(stack: Stack, config: object) -> LavalinkService:
    node = replace(
        config.lavalink,
        host="127.0.0.1",
        port=stack.port,
        password=PASSWORD,
        secure=False,
    )
    instance = LavalinkService(node, BOT_USER_ID)
    await instance.start()
    if not await instance.wait_ready(25):
        await instance.close()
        pytest.fail("Lavalink node did not become ready for the bot client")
    yield instance
    await instance.close()


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "state.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture(autouse=True)
def fast_voice_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    # Discord is faked, so no real VOICE_STATE_UPDATE arrives.  Shorten the
    # wait instead of sleeping 12 seconds in every test.
    monkeypatch.setattr(player_module, "VOICE_CONNECT_TIMEOUT", 0.05)


@pytest.fixture
async def world(
    config: object,
    service: LavalinkService,
    db: Database,
    stack: Stack,
) -> World:
    instance = build_world(config, service, db, guild_ids=(1,))
    yield instance
    instance.cog.cog_unload()
    for player in list(instance.bot.players.values()):
        await player.close()


@pytest.fixture
async def world_two(
    config: object,
    service: LavalinkService,
    db: Database,
    stack: Stack,
) -> World:
    instance = build_world(config, service, db, guild_ids=(1, 2), dj_role=True)
    yield instance
    instance.cog.cog_unload()
    for player in list(instance.bot.players.values()):
        await player.close()


@pytest.fixture
def audio(stack: Stack):
    return stack.audio_url
