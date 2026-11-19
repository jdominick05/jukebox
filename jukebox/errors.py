# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jukebox contributors
"""Exceptions that are safe to show to Discord users."""

from __future__ import annotations

__all__ = ["SourceDisabled", "UserError"]


class UserError(Exception):
    """A failure caused by user input or the current state of the player.

    The command error handler turns these into an ephemeral embed; they are
    never logged with a traceback.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class SourceDisabled(UserError):
    """Raised when a query targets a source that the operator turned off."""

    def __init__(self, source_label: str) -> None:
        super().__init__(
            f"**{source_label}** is disabled on this instance.",
            hint="Ask the bot operator to enable it, or try a link from another source.",
        )
        self.source_label = source_label
