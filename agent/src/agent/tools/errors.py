"""Typed execution failures for the local/ssh exec helpers (todo 3020 phase 3)."""

from __future__ import annotations


class CommandError(RuntimeError):
    """A command exited non-zero (or timed out) when the caller asked to treat
    failures as errors (`check=True`). Carries the exit code for callers that
    want to surface or retry on it."""

    def __init__(self, exit_code: int, command_description: str):
        self.exit_code = exit_code
        super().__init__(
            f"command failed with exit code {exit_code}: {command_description}"
        )
