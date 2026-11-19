# jukebox

A production-oriented Discord music bot. Slash commands only, per-guild queues,
audio sent by a Lavalink v4 node (no FFmpeg or voice codecs in the bot process),
SQLite persistence, and best-effort resume of every guild after a restart.

Licensed **AGPL-3.0-or-later**. `/source` prints the repository URL so network
users can obtain the corresponding source, as AGPL section 13 requires.

---

## Architecture

`discord.py` owns the gateway and slash commands. Lavalink owns voice and audio:
the bot forwards `VOICE_STATE_UPDATE` / `VOICE_SERVER_UPDATE` payloads to the
node, and the node joins the channel and sends Opus. Each guild has one
`GuildPlayer` holding the authoritative queue, loop mode, volume, pause state and
playback position; Lavalink's own queue is deliberately unused. State is written
to SQLite on every transition and every 15 seconds while playing. On startup the
bot waits for the node, rejoins saved channels, and resumes the saved track at
its saved position. Failures are caught at the command, listener and node
boundaries and reported in the guild's text channel.

---

## Verified versions

These are the exact versions pinned by this repository. They were checked
against PyPI, GitHub releases and the upstream READMEs on 2026-11-19.

| Component | Version | Why this version |
|---|---|---|
| Python | 3.12 | `StrEnum`, `asyncio.timeout`-era API; the Docker image is `python:3.12-slim-bookworm` |
| discord.py | 2.7.1 | Current release; supports `enable_debug_events` and raw gateway access |
| lavalink (Python client) | 5.11.1 | Maintained Lavalink v4 client; sends the `channelId` voice-state field required by Lavalink 4.2+ |
| aiosqlite | 0.22.1 | Current release |
| aiohttp | 3.14.5 | Pinned because discord.py and the health server both use it |
| Lavalink | 4.2.2 | First DAVE-capable line is 4.2.0; 4.2.2 bundles libdave-jvm 0.1.3 and koe 3.0.0-pre6 |
| youtube-source plugin | 1.18.2 | Current release for Lavalink 4 |
| LavaSrc plugin | 4.8.3 | Current release; Spotify/Apple mirroring and Deezer playback |

### DAVE (Discord end-to-end encryption)

Discord's DAVE protocol is implemented by the **Lavalink node**, not by this
Python process. The release notes for Lavalink **4.2.0** state that it is the
first release with DAVE support and that the voice state gained a required
`channelId` field. This repository pins **Lavalink 4.2.2** (release notes list
libdave 0.1.3 and koe 3.0.0-pre6) and **lavalink.py 5.11.1**, whose
`Player._voice_state_update` sends `channelId` alongside `sessionId`, `token` and
`endpoint`.

The bot never touches media encryption, which is why PyNaCl and FFmpeg are not
dependencies. DAVE was not exercised against a live voice channel while building
this repository; see [Things I could not verify](#things-i-could-not-verify).

---

## Requirements

- A Discord application with a bot user.
- A Lavalink 4.2.x node with Java 17+ (Java 18 is used by the official image).
- Outbound HTTPS from the node to YouTube/SoundCloud/etc., and UDP to Discord
  voice.
- Docker + Compose v2, or Python 3.12 + a systemd-managed Lavalink for the
  non-Docker path.

---

## Discord application setup

1. Open <https://discord.com/developers/applications> and create an application.
2. **Bot** → **Reset Token** → copy the token into `DISCORD_TOKEN`. Treat it as a
   password; it is never written to a file in this repository.
3. **Bot** → **Privileged Gateway Intents** → enable **Server Members Intent**.
   The bot needs member objects for DJ-role checks and member lookups. Message
   Content is *not* needed: there are no prefix commands.
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `View Channels`, `Send Messages`, `Embed Links`,
     `Connect`, `Speak`
5. Invite the bot, then run `/play` in a server. Slash commands are global by
   default; set `DISCORD_GUILD_ID` while developing to sync instantly to one
   guild instead.

The exact permission integer for the five permissions above is
`2150714368` (`View Channels` 1024 + `Send Messages` 2048 + `Embed Links` 16384 +
`Connect` 1048576 + `Speak` 2097152 + `Use Application Commands` 2147483648).
Discord adds `Use Application Commands` automatically for installed apps; the
URL Generator is safer than hand-editing integers.

---

## Quick start with Docker

```sh
cp .env.example .env
$EDITOR .env                  # DISCORD_TOKEN, REPO_URL, LAVALINK_PASSWORD at minimum
docker compose up -d --build
docker compose logs -f bot
```

`docker compose` starts three services:

- `lavalink-init` — one-shot `chown` of the plugin volume to UID/GID 322. Without
  it the non-root Lavalink image cannot download plugins into a fresh volume.
- `lavalink` — `ghcr.io/lavalink-devs/lavalink:4.2.2`, configured by
  `application.yml` plus environment overrides.
- `bot` — this repository, non-root UID 10001, healthchecked on `/healthz`.

The bot does not publish a Discord-facing port. Lavalink is only on the internal
`backend` network. The health endpoint is bound to `127.0.0.1:${HEALTH_PORT}` on
the host.

Check it:

```sh
curl -s http://127.0.0.1:8080/healthz | jq
```

A healthy response has `"status": "ok"` and `"lavalink": {"available": true, ...}`.
The endpoint returns HTTP 503 until the Discord gateway is ready, so it is both a
Docker liveness probe and a startup gate.

---

## Configuration reference

Everything is environment-driven. There is no `config.toml`; where the spec was
silent, environment variables were the simpler option (one mechanism for Docker,
systemd and tests).

### Discord and identity

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | — (required) | Bot token. Never commit it. |
| `DISCORD_GUILD_ID` | empty | If set, commands sync to this guild instead of globally. |
| `REPO_URL` | — (required) | Public source URL returned by `/source`. |

### Lavalink client

| Variable | Default | Meaning |
|---|---|---|
| `LAVALINK_HOST` | `127.0.0.1` | Node host. Compose forces `lavalink`. |
| `LAVALINK_PORT` | `2333` | Node REST/WS port. |
| `LAVALINK_PASSWORD` | — (required) | Shared secret; also fed to the node as `LAVALINK_SERVER_PASSWORD`. |
| `LAVALINK_SECURE` | `false` | Use `https`/`wss`. |
| `LAVALINK_REGION` | `default` | Region label used by the client's node selector. |
| `LAVALINK_NAME` | `main` | Node name in logs. |
| `LAVALINK_RESUME_TIMEOUT` | `300` | Seconds the node keeps a resumable session. |
| `LAVALINK_RESUME_TIMEOUT` | `300` | Seconds the node keeps a resumable session. |

### Sources

| Variable | Default | Notes |
|---|---|---|
| `DEFAULT_SOURCE` | `youtube` | Prefix for plain text. One of `youtube`, `youtube_music`, `soundcloud`, `spotify`, `apple_music`, `deezer`. |
| `SOURCE_YOUTUBE` | `true` | Enables youtube-source (also required for Spotify/Apple mirroring). |
| `SOURCE_SOUNDCLOUD` | `true` | Built-in Lavalink SoundCloud source. |
| `SOURCE_BANDCAMP` | `true` | URL loading only; Bandcamp has no search prefix. |
| `SOURCE_HTTP` | `true` | Direct audio URLs with a known audio extension. |
| `SOURCE_SPOTIFY` | `false` | Requires `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`. |
| `SOURCE_APPLE_MUSIC` | `false` | Requires `APPLE_MUSIC_TOKEN` (Apple Media API token). |
| `SOURCE_DEEZER` | `false` | Requires `DEEZER_ARL` and `DEEZER_MASTER_DECRYPTION_KEY`. |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | empty | Spotify developer app credentials. |
| `APPLE_MUSIC_TOKEN` | empty | Apple Music Media API token. |
| `DEEZER_ARL` / `DEEZER_MASTER_DECRYPTION_KEY` | empty | Deezer cookie and decryption key. |
| `YOUTUBE_POT_TOKEN` / `YOUTUBE_VISITOR_DATA` | empty | Optional poToken for WEB/WEBEMBEDDED. |
| `YOUTUBE_OAUTH_ENABLED` / `YOUTUBE_OAUTH_REFRESH_TOKEN` | `false` / empty | Optional; use a burner account. |

Validation happens at startup: a disabled default source, or Spotify/Apple/Deezer
enabled without credentials, aborts with a specific error instead of producing
confusing Lavalink failures. A disabled source always yields a friendly
`SourceDisabled` error in Discord, never a traceback.

### Behaviour

| Variable | Default | Meaning |
|---|---|---|
| `IDLE_TIMEOUT` | `300` | Seconds with nothing playing before leaving voice; `0` disables. Minimum 10 unless 0. |
| `EMPTY_TIMEOUT` | `30` | Seconds alone in a channel before leaving; `0` disables. Minimum 5 unless 0. |
| `DEFAULT_VOLUME` | `70` | 0–100. |
| `MAX_QUEUE_SIZE` | `1000` | Per-guild queue cap; playlists are truncated with a message. |
| `STATE_FLUSH_INTERVAL` | `15` | Seconds between position flushes while playing. |
| `RESTORE_ON_START` | `true` | Rejoin and resume saved guilds at startup. |
| `SHUTDOWN_TIMEOUT` | `15` | Seconds allowed for the final state save on SIGTERM. |

### Runtime

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_PATH` | `./data/jukebox.db` | SQLite file; the parent directory is created. |
| `HEALTH_HOST` / `HEALTH_PORT` | `0.0.0.0` / `8080` | `/healthz` listener. |
| `LOG_LEVEL` | `INFO` | Standard Python level name. |
| `LOG_JSON` | `true` | JSON lines when true, human-readable when false. |
| `JAVA_OPTIONS` | `-Xms256m -Xmx1G` | Compose-only heap setting for Lavalink. |
| `LAVALINK_LOG_LEVEL` | `INFO` | Compose-only root log level for Lavalink. |

Lavalink configuration is in `application.yml`. Lavalink gives environment
variables precedence over that file; `docker-compose.yml` maps the friendly
`SOURCE_*` names to the node's `PLUGINS_LAVASRC_*` / `PLUGINS_YOUTUBE_*` names.

---

## Sources in detail

- **YouTube** — `dev.lavalink.youtube:youtube-plugin:1.18.2`, built-in YouTube
  source disabled. Search uses `ytsearch:`; `ytmsearch:` is available by setting
  `DEFAULT_SOURCE=youtube_music`. If YouTube starts asking for bot verification,
  supply `YOUTUBE_POT_TOKEN` + `YOUTUBE_VISITOR_DATA`, or OAuth with a burner
  account; neither is a guaranteed fix.
- **SoundCloud** — Lavalink's built-in source (`scsearch:`).
- **Bandcamp** — Lavalink's built-in source; URLs only.
- **HTTP** — direct links ending in `.mp3`, `.ogg`, `.opus`, `.flac`, `.m4a`,
  `.wav`, `.aac` or `.webm`. Unknown URLs are rejected rather than handed to
  Lavalink.
- **Spotify** — LavaSrc metadata; playback is mirrored to YouTube (`ytsearch:`
  with ISRC first). Spotify itself is not a playable source.
- **Apple Music** — LavaSrc metadata, mirrored to YouTube. Requires a Media API
  token (the `keyID`/`teamID`/`musicKitKey` alternative is not wired to env vars).
- **Deezer** — LavaSrc direct playback. Requires an ARL cookie and the master
  decryption key. Without them the source is disabled at startup.

`/play` picks the first search result. Playlists are added in order until
`MAX_QUEUE_SIZE`; the reply says how many tracks were dropped.

---

## Commands

All commands are slash commands. Playback control requires the user to be in the
bot's voice channel. If a DJ role is configured, the user must also have that
role or `Manage Server`.

| Command | Description |
|---|---|
| `/play <query>` | Search or load a URL/playlist; joins the caller's voice channel. |
| `/pause`, `/resume` | Pause/resume. |
| `/skip` | Advance, bypassing track loop. |
| `/stop` | Stop and clear the queue; stays connected. |
| `/queue [page]` | Paginated queue with previous/next buttons. |
| `/nowplaying` | Current track, progress, loop, volume, queue size. |
| `/seek <seconds>` | Seek within the current track; rejected for streams. |
| `/volume <0-100>` | Per-guild volume. |
| `/loop <off\|track\|queue>` | Loop mode. |
| `/shuffle` | Shuffle the queued tracks. |
| `/remove <position>` | Remove one queued track. |
| `/move <index> <to>` | Move a queued track. |
| `/clear` | Clear the queue, keep the current track. |
| `/disconnect` | Leave voice and clear the queue. |
| `/source` | Repository URL and license. |
| `/djrole [role]` | Set/clear the DJ role (Manage Server only). Added because the spec requires DJ roles but lists no command to configure one. |

---

## Reliability model

- **Persistence.** `guild_state` stores voice/text channel, volume, loop, pause,
  position and the current track; `queue_items` stores the ordered queue. Each
  track is stored as the full Lavalink track object, so restore does not depend
  on a search still returning the same result.
- **Restore.** On startup the bot waits up to 60 s for the node, then for each
  saved guild: verifies the guild/channel still exist, checks Connect/Speak,
  joins, restores volume/loop/queue, and plays the saved track at the saved
  position (clamped to one second before the end). If the current track cannot be
  restored, the queue advances. Unrecoverable rows (guild or channel deleted,
  failed join) are dropped or kept for the next restart as documented in the
  code, and the text channel is told what happened.
- **Session resuming.** On every `NodeReadyEvent` the bot calls
  `PATCH /v4/sessions/{id}` with `resuming: true` and
  `LAVALINK_RESUME_TIMEOUT`. The client library reconnects the node WebSocket
  with exponential backoff; voice server moves are forwarded as fresh
  `VOICE_SERVER_UPDATE` payloads.
- **Track failures.** `TrackException` and `TrackStuck` are reported in the text
  channel, then skipped. Three consecutive failures stop playback instead of
  burning through a dead playlist. A stale end event from a replaced track is
  ignored by comparing the encoded track.
- **Voice websocket errors.** `4006`/`4009`/`4014` tear down the dead session and
  tell the channel; other close codes trigger up to three rejoin attempts with
  backoff.
- **Shutdown.** SIGTERM/SIGINT cancel timers, save every player, close the health
  server, Lavalink client and SQLite, then close the gateway. Docker Compose uses
  a 30 s stop grace period.
- **Error containment.** All command errors go through `CommandTree.on_error`;
  every Lavalink event hook and Discord listener is wrapped. Unexpected errors
  are logged with context and answered with a generic ephemeral message.

SQLite is a single file. Back it up by copying it while the bot is stopped (or
use `sqlite3 db ".backup backup.db"` while running). Losing it only loses queues,
not configuration.

---

## Running without Docker (systemd)

Layout:

```
/opt/jukebox              code + .venv       (user jukebox)
/opt/lavalink             Lavalink.jar + plugins + logs (user lavalink)
/var/lib/jukebox          jukebox.db         (user jukebox)
/etc/jukebox/jukebox.env  bot environment
/etc/jukebox/lavalink.env Lavalink environment
```

Steps:

```sh
sudo useradd --system --home /opt/jukebox --shell /usr/sbin/nologin jukebox
sudo useradd --system --home /opt/lavalink --shell /usr/sbin/nologin lavalink
sudo install -d -o jukebox -g jukebox /opt/jukebox /var/lib/jukebox
sudo install -d -o lavalink -g lavalink /opt/lavalink/plugins /opt/lavalink/logs
sudo rsync -a --exclude .venv --exclude .env ./ /opt/jukebox/
sudo python3 -m venv /opt/jukebox/.venv
sudo /opt/jukebox/.venv/bin/pip install -r /opt/jukebox/requirements.txt

# Lavalink
sudo curl -L -o /opt/lavalink/Lavalink.jar \
  https://github.com/lavalink-devs/Lavalink/releases/download/4.2.2/Lavalink.jar
sudo install -o lavalink -g lavalink -m 0644 application.yml /opt/lavalink/application.yml

# Environment files
sudo install -d -m 0750 /etc/jukebox
sudo install -m 0640 -o root -g jukebox deploy/jukebox.env.example /etc/jukebox/jukebox.env
sudo install -m 0640 -o root -g lavalink deploy/lavalink.env.example /etc/jukebox/lavalink.env
# edit both, keeping SOURCE_* and PLUGINS_* switches in sync

sudo cp deploy/lavalink.service deploy/jukebox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lavalink jukebox
sudo journalctl -u jukebox -f
```

The bot unit uses `ProtectSystem=strict` with `ReadWritePaths=/var/lib/jukebox`;
point `DATABASE_PATH` there. `deploy/jukebox.env.example` already does.

---

## Updating

Docker:

```sh
git pull                          # pick up code and pin changes
docker compose build --pull bot
docker compose up -d
docker compose logs -f bot
```

The SQLite schema is created with `CREATE TABLE IF NOT EXISTS`; no migration is
needed for the current schema version. Back up `jukebox-data` before major
upgrades.

Non-Docker:

```sh
sudo systemctl stop jukebox
sudo rsync -a --exclude .venv --exclude .env ./ /opt/jukebox/
sudo /opt/jukebox/.venv/bin/pip install -r /opt/jukebox/requirements.txt
sudo systemctl start jukebox
```

Update `application.yml` and the plugin versions together: youtube-source and
LavaSrc are pinned in `application.yml`, while Lavalink itself is pinned in
`docker-compose.yml` / the systemd install instructions.

---

## Licensing and dependencies

This project is **AGPL-3.0-or-later**; see `LICENSE`. If you run a modified
version as a network service, you must offer its corresponding source to users;
`/source` is the in-bot offer and reads `REPO_URL`.

| Dependency | Version | License | AGPL-compatible |
|---|---|---|---|
| Python | 3.12 | PSF-2.0 | Yes (permissive) |
| discord.py | 2.7.1 | MIT | Yes |
| lavalink (Lavalink.py) | 5.11.1 | MIT | Yes |
| aiosqlite | 0.22.1 | MIT | Yes |
| aiohttp | 3.14.5 | Apache-2.0 | Yes (Apache-2.0 is GPLv3/AGPLv3 compatible) |
| Lavalink server | 4.2.2 | MIT | Yes |
| youtube-source | 1.18.2 | MIT | Yes |
| LavaSrc | 4.8.3 | Apache-2.0 | Yes |
| libdave-jvm (bundled by Lavalink) | 0.1.3 | Apache-2.0 | Yes |
| koe (bundled by Lavalink) | 3.0.0-pre6 | MIT | Yes |
| pytest | 9.2.0 | MIT | Dev only |
| pytest-asyncio | 1.5.0 | Apache-2.0 | Dev only |
| ruff | 0.17.6 | MIT | Dev only |

All runtime dependencies are permissive or Apache-2.0; none is copyleft-only in a
way that conflicts with AGPL-3.0-or-later.

---

## Things I could not verify

1. **A live DAVE voice handshake.** Lavalink 4.2.2's release notes and the
   client's `channelId` field are verified, but no Discord token/voice channel
   was available here, so end-to-end encrypted audio was not exercised.
2. **Spotify, Apple Music and Deezer loading.** Their config keys come from the
   upstream LavaSrc README; no credentials were available. The bot-side gating
   and error paths are unit-tested.
3. **Plugin env-var overrides for credentials.** `LAVALINK_SERVER_PASSWORD` and
   the YouTube plugin were verified against a running 4.2.2 node; the
   `PLUGINS_LAVASRC_*` mappings follow Lavalink's documented env-name rule but
   were not exercised with real Spotify/Apple/Deezer credentials.
4. **The Lavalink image's HTTP tooling.** The image has no `curl`/`wget`, so the
   Compose healthcheck uses a bash TCP probe against port 2333 rather than
   `GET /version` (which also requires the password).
5. **A pinned base-image digest.** `python:3.12-slim-bookworm` follows 3.12
   patches; pin a digest if you need byte-for-byte reproducible images.
6. **Real Discord command registration.** Command metadata is unit-tested for
   count/description limits, but `tree.sync()` was not run against Discord.
