"""Tmux-compatible multiplexer wrappers (nami, lmux, wmux, herdr)."""

from __future__ import annotations
from typing import Any
from .tmux import TmuxMultiplexer

class TmuxCompatibleMultiplexer(TmuxMultiplexer):
    """Wrapper for tmux-compatible multiplexers that use the same CLI semantics."""

    def __init__(self, config: Any, binary: str):
        super().__init__(config)
        self._binary = binary

    def binary_name(self) -> str:
        return self._binary

    def _tmux(self, *args: str, check: bool = False, capture: bool = True):
        import subprocess
        cmd = [self._binary] + list(args)
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        return subprocess.run(cmd, check=check, text=True)
