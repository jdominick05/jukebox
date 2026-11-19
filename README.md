# jukebox

Discord music bot: slash commands, isolated per-guild queues, Lavalink playback, and SQLite state that survives restarts.

## Requirements
- Discord application with a bot user.
- Docker Engine with Compose v2, or Python 3.12 and Java 17+ for systemd.
- Outbound HTTPS from Lavalink to each enabled source and UDP to Discord voice.

Lavalink is pinned to 4.2.2. DAVE voice encryption requires 4.2.0 or newer, so keep the node on 4.2.x.

## Setup
Create an application at <https://discord.com/developers/applications>, add a bot, and copy its token from **Bot → Reset Token**. Enable **Server Members Intent** under **Bot → Privileged Gateway Intents**; Message Content is not used.

Invite the bot with scopes `bot` and `applications.commands` and permissions `View Channels`, `Send Messages`, `Embed Links`, `Connect`, `Speak`. Use the URL Generator rather than editing the permission integer by hand.

```sh
cp .env.example .env
$EDITOR .env                  # DISCORD_TOKEN, REPO_URL, LAVALINK_PASSWORD
docker compose up -d --build
docker compose logs -f bot
```

Check readiness:

```sh
curl -s http://127.0.0.1:8080/healthz
```

`status` is `ok` and `lavalink.available` is `true` when playback is ready. The endpoint returns 503 until the gateway and node are available. Commands are global by default; set `DISCORD_GUILD_ID` to sync to one server during development.

## Configuration

| Variable | Required / default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | required | Bot token. |
| `DISCORD_GUILD_ID` | empty | Sync slash commands to this guild instead of globally. |
| `REPO_URL` | required | Source URL returned by `/source`; must be `http(s)`. |
| `LAVALINK_HOST` | `127.0.0.1` | Node host; Compose overrides it to `lavalink`. |
| `LAVALINK_PORT` | `2333` | Node REST/WebSocket port. |
| `LAVALINK_PASSWORD` | required | Shared secret; the example value `youshallnotpass` is rejected. |
| `LAVALINK_SECURE` | `false` | Use HTTPS/WSS. |
| `LAVALINK_REGION` | `default` | Node region label. |
| `LAVALINK_NAME` | `main` | Node name in logs. |
| `LAVALINK_RESUME_TIMEOUT` | `300` | Seconds the node keeps a session for reconnecting. |
| `JAVA_OPTIONS` | `-Xms256m -Xmx1G` | Lavalink JVM heap; Compose only. |
| `LAVALINK_LOG_LEVEL` | `INFO` | Lavalink root log level; Compose only. |
| `DEFAULT_SOURCE` | `youtube` | Text-search source: `youtube`, `youtube_music`, `soundcloud`, `spotify`, `apple_music`, `deezer`; must be enabled. |
| `SOURCE_YOUTUBE` | `true` | youtube-source; required by Spotify and Apple Music. |
| `SOURCE_SOUNDCLOUD` | `true` | SoundCloud search and URLs. |
| `SOURCE_BANDCAMP` | `true` | Bandcamp URLs only. |
| `SOURCE_HTTP` | `true` | Direct audio URLs. |
| `SOURCE_SPOTIFY` | `false` | Spotify metadata; requires credentials below and `SOURCE_YOUTUBE=true`. |
| `SOURCE_APPLE_MUSIC` | `false` | Apple Music metadata; requires a token below and `SOURCE_YOUTUBE=true`. |
| `SOURCE_DEEZER` | `false` | Deezer playback; requires both Deezer values below. |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | empty | Spotify application credentials. |
| `APPLE_MUSIC_TOKEN` | empty | Apple Music Media API token. |
| `DEEZER_ARL`, `DEEZER_MASTER_DECRYPTION_KEY` | empty | Deezer cookie and decryption key. |
| `YOUTUBE_POT_TOKEN`, `YOUTUBE_VISITOR_DATA` | empty | Optional poToken for the WEB clients. |
| `YOUTUBE_OAUTH_ENABLED`, `YOUTUBE_OAUTH_REFRESH_TOKEN` | `false`, empty | Optional YouTube OAuth; use a burner account. |
| `IDLE_TIMEOUT` | `300` | Seconds with nothing playing before leaving; `0` disables; otherwise at least 10. |
| `EMPTY_TIMEOUT` | `30` | Seconds alone in the channel before leaving; `0` disables; otherwise at least 5. |
| `DEFAULT_VOLUME` | `70` | Initial volume, 0–100. |
| `MAX_QUEUE_SIZE` | `1000` | Tracks per guild; excess playlist entries are dropped. |
| `STATE_FLUSH_INTERVAL` | `15` | Seconds between position writes while playing; at least 5. |
| `RESTORE_ON_START` | `true` | Rejoin saved channels and resume queues at startup. |
| `SHUTDOWN_TIMEOUT` | `15` | Seconds allowed to save state on SIGTERM. |
| `DATABASE_PATH` | `./data/jukebox.db` | SQLite file; the parent directory is created. |
| `HEALTH_HOST`, `HEALTH_PORT` | `0.0.0.0`, `8080` | `/healthz` listener; Compose publishes it on `127.0.0.1:${HEALTH_PORT}`. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `LOG_JSON` | `true` | JSON log lines; set `false` for human-readable output. |

## Commands
Control commands require the caller to be in the bot's voice channel; with a DJ role set, the caller also needs that role or `Manage Server`.

| Command | Description |
|---|---|
| `/play <query>` | Load a track, playlist, or supported URL and join the caller's voice channel. |
| `/pause` | Pause playback. |
| `/resume` | Resume playback. |
| `/skip` | Skip the current track. |
| `/stop` | Stop playback and clear the queue. |
| `/queue [page]` | Show the queue with previous/next buttons. |
| `/nowplaying` | Show the current track and playback state. |
| `/seek <seconds>` | Seek within the current track. |
| `/volume <0-100>` | Set the volume for this guild. |
| `/loop <off\|track\|queue>` | Set the loop mode. |
| `/shuffle` | Shuffle queued tracks. |
| `/remove <position>` | Remove one queued track. |
| `/move <index> <to>` | Move a queued track. |
| `/clear` | Clear the queue and keep the current track. |
| `/disconnect` | Leave voice and clear the queue. |
| `/source` | Show the repository URL and license. |
| `/djrole [role]` | Set or clear the DJ role; requires `Manage Server`. |

## Running without Docker (systemd)

```sh
sudo useradd --system --home /opt/jukebox --shell /usr/sbin/nologin jukebox
sudo useradd --system --home /opt/lavalink --shell /usr/sbin/nologin lavalink
sudo install -d -o jukebox -g jukebox /opt/jukebox /var/lib/jukebox
sudo install -d -o lavalink -g lavalink /opt/lavalink/plugins /opt/lavalink/logs
sudo rsync -a --exclude .venv --exclude .env ./ /opt/jukebox/
sudo python3 -m venv /opt/jukebox/.venv
sudo /opt/jukebox/.venv/bin/pip install -r /opt/jukebox/requirements.txt

sudo curl -L -o /opt/lavalink/Lavalink.jar \
  https://github.com/lavalink-devs/Lavalink/releases/download/4.2.2/Lavalink.jar
sudo install -o lavalink -g lavalink -m 0644 application.yml /opt/lavalink/application.yml

sudo install -d -m 0750 /etc/jukebox
sudo install -m 0640 -o root -g jukebox deploy/jukebox.env.example /etc/jukebox/jukebox.env
sudo install -m 0640 -o root -g lavalink deploy/lavalink.env.example /etc/jukebox/lavalink.env

sudo cp deploy/lavalink.service deploy/jukebox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lavalink jukebox
```

Edit `/etc/jukebox/jukebox.env` and `/etc/jukebox/lavalink.env`: the bot's `SOURCE_*` values and the node's `PLUGINS_*` values must match. `deploy/jukebox.env.example` sets `DATABASE_PATH=/var/lib/jukebox/jukebox.db`, which the unit's `ReadWritePaths` allows.

## Updating

```sh
# Docker
git pull
docker compose build --pull bot
docker compose up -d
docker compose logs -f bot

# systemd
sudo systemctl stop jukebox
sudo rsync -a --exclude .venv --exclude .env ./ /opt/jukebox/
sudo install -o lavalink -g lavalink -m 0644 application.yml /opt/lavalink/application.yml
sudo /opt/jukebox/.venv/bin/pip install -r /opt/jukebox/requirements.txt
sudo systemctl restart lavalink
sudo systemctl start jukebox
```
Plugin versions are pinned in `application.yml`; Lavalink is pinned in `docker-compose.yml` and in the systemd download above. Update them together.

## Tests
```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q -m "not integration"
.venv/bin/pytest tests/integration -q -m "not live"
```

The second command is Tier 1: it starts Lavalink 4.2.2 and a local HTTP audio fixture in Docker, fakes Discord, and makes no external source requests. Tier 2 uses a real bot token and voice channel:

```sh
TEST_BOT_TOKEN=... TEST_GUILD_ID=... TEST_VOICE_CHANNEL_ID=... \
  .venv/bin/pytest tests/integration/test_live_voice.py -q -s
```

The bot must already be in that guild and able to join the voice channel. Tier 2 is opt-in and skipped without all three variables; CI runs Tier 1 only.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Configuration error: DISCORD_TOKEN is required` | Fill in `.env`; the process also requires `REPO_URL` and `LAVALINK_PASSWORD`. |
| Process exits with `PrivilegedIntentsRequired` | Enable **Server Members Intent** in the Developer Portal. |
| `/healthz` stays 503 | Check `docker compose logs lavalink`; verify the password and that the node is 4.2.2. |
| Bot joins voice but no audio | Confirm Lavalink is 4.2.x and UDP to Discord voice is allowed. |
| YouTube asks for verification or returns 403 | Set `YOUTUBE_POT_TOKEN` and `YOUTUBE_VISITOR_DATA`, or OAuth with a burner account; neither is guaranteed. |
| `SOURCE_SPOTIFY requires ...` or Apple Music fails at startup | Set the credential variables and keep `SOURCE_YOUTUBE=true`. |
| Slash commands do not appear | Re-invite with both scopes; global sync can take time; set `DISCORD_GUILD_ID` to test immediately. |
| Lavalink cannot write plugins | Keep the `lavalink-init` service; it fixes ownership of the plugin volume. |

## License
This project is **AGPL-3.0-or-later**; see `LICENSE`. A modified version run as a network service must offer its corresponding source. `/source` prints `REPO_URL` for that purpose.

| Dependency | Version | License |
|---|---|---|
| Python | 3.12 | PSF-2.0 |
| discord.py | 2.7.1 | MIT |
| lavalink (Python client) | 5.11.1 | MIT |
| aiosqlite | 0.22.1 | MIT |
| aiohttp | 3.14.5 | Apache-2.0 |
| Lavalink server | 4.2.2 | MIT |
| youtube-source | 1.18.2 | MIT |
| LavaSrc | 4.8.3 | Apache-2.0 |
| libdave-jvm (bundled by Lavalink) | 0.1.3 | Apache-2.0 |
| koe (bundled by Lavalink) | 3.0.0-pre6 | MIT |
| busybox (Compose init only) | 1.37 | GPL-2.0 |
| pytest | 9.2.0 | MIT |
| pytest-asyncio | 1.5.0 | Apache-2.0 |
| ruff | 0.17.6 | MIT |

All runtime dependencies are permissive or Apache-2.0. Busybox runs as a separate container for volume ownership and is not linked into the bot.

## Known gaps
- A live DAVE voice handshake was not run while building this repository; Tier 2 is the check and requires a token, guild, and voice channel.
- Spotify, Apple Music, and Deezer were not exercised with real credentials.
- LavaSrc credential environment overrides follow Lavalink's documented naming rule but were not tested with real accounts.
- Command sync has not been exercised against Discord here.
- The Python base image follows `3.12-slim-bookworm` patches; pin a digest for byte-for-byte reproducible builds.
- The Lavalink image has no `curl` or `wget`, so its healthcheck uses a bash TCP probe instead of `GET /version`.
