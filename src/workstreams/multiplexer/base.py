"""Base multiplexer interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MultiplexerBase(ABC):
    """Base class for terminal multiplexers."""

    #: Multiplexer name (used in logs / status)
    name = "base"

    def __init__(self, config: Any):
        self.config = config

    @abstractmethod
    def start(self, workstreams: List[Dict[str, Any]], command: Optional[str] = None) -> None:
        """Start workstreams in multiplexer."""

    @abstractmethod
    def attach(self, session: str) -> None:
        """Attach to existing session (blocks until user exits)."""

    @abstractmethod
    def send_command(self, workstream_id: int, command: str) -> bool:
        """Send a command to the workstream's pane/tab."""

    @abstractmethod
    def session_name(self) -> str:
        """Return the session name used by start()."""

    @abstractmethod
    def pane_target(self, workstream_id: int) -> str:
        """Return the pane target for a workstream (used for send_command)."""

    def is_available(self) -> bool:
        """Check if the multiplexer binary exists on PATH."""
        import shutil
        return shutil.which(self.binary_name()) is not None

    def binary_name(self) -> str:
        return self.name
