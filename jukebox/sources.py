# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Turn user input into a Lavalink identifier, enforcing source switches."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .config import SEARCH_PREFIXES, SOURCE_LABELS, Config, Source
from .errors import SourceDisabled, UserError

__all__ = ["ResolvedQuery", "resolve_query"]

_HOST_SOURCES: dict[str, Source] = {
    "youtube.com": Source.YOUTUBE,
    "youtu.be": Source.YOUTUBE,
    "music.youtube.com": Source.YOUTUBE_MUSIC,
    "soundcloud.com": Source.SOUNDCLOUD,
    "bandcamp.com": Source.BANDCAMP,
    "open.spotify.com": Source.SPOTIFY,
    "music.apple.com": Source.APPLE_MUSIC,
    "deezer.com": Source.DEEZER,
}

_AUDIO_EXTENSIONS = (
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
)


@dataclass(frozen=True, slots=True)
class ResolvedQuery:
    """A Lavalink identifier plus the source it belongs to."""

    identifier: str
    source: Source
    is_url: bool


def _host_matches(host: str, domain: str) -> bool:
    host = host.lower()
    return host == domain or host.endswith("." + domain)


def _find_url_source(host: str) -> Source | None:
    matches = [domain for domain in _HOST_SOURCES if _host_matches(host, domain)]
    if not matches:
        return None
    return _HOST_SOURCES[max(matches, key=len)]


def resolve_query(raw: str, config: Config) -> ResolvedQuery:
    """Map a slash-command argument to something Lavalink understands.

    URLs are routed by host, direct audio links by extension, and plain text is
    prefixed with the configured default source's search prefix.

    Raises:
        UserError: if the input is empty or unsupported.
        SourceDisabled: if the URL belongs to a disabled source.
    """
    query = raw.strip()
    if not query:
        raise UserError("Give me a track name, playlist or URL.")

    parts = urlsplit(query)
    if parts.scheme in {"http", "https"} and parts.netloc:
        source = _find_url_source(parts.hostname or "")
        if source is not None:
            if source not in config.enabled_sources:
                raise SourceDisabled(SOURCE_LABELS[source])
            return ResolvedQuery(identifier=query, source=source, is_url=True)

        if parts.path.lower().endswith(_AUDIO_EXTENSIONS):
            if Source.HTTP not in config.enabled_sources:
                raise SourceDisabled(SOURCE_LABELS[Source.HTTP])
            return ResolvedQuery(identifier=query, source=Source.HTTP, is_url=True)

        raise UserError(
            "That URL is not from a supported source.",
            hint="Use YouTube, SoundCloud, Bandcamp, Spotify, Apple Music, Deezer "
            "or a direct link to an audio file.",
        )

    if parts.scheme and parts.scheme not in {"http", "https"}:
        raise UserError("Only http(s) URLs are supported.")

    default = config.default_source
    if default not in config.enabled_sources:
        # load_config() rejects this, but defense in depth keeps a runtime
        # misconfiguration from becoming a confusing Lavalink error.
        raise SourceDisabled(SOURCE_LABELS[default])

    prefix = SEARCH_PREFIXES.get(default)
    if prefix is None:
        raise UserError(f"{SOURCE_LABELS[default]} cannot be used for text search.")
    return ResolvedQuery(identifier=f"{prefix}{query}", source=default, is_url=False)
