"""Zellij multiplexer implementation.

Zellij uses tabs; each workstream gets its own tab. Zellij's scripting
surface is less mature than tmux's, so we use `zellij action` and
`zellij run` where available.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base import MultiplexerBase


class ZellijMultiplexer(MultiplexerBase):
    """Zellij-based workstream management."""

    name = "zellij"

    def __init__(self, config: Any):
        super().__init__(config)
        self.session = f"workstreams-{config.project}"

    def _zj(self, *args: str, check: bool = False, capture: bool = True) -> subprocess.CompletedProcess:
        cmd = ["zellij"] + list(args)
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        return subprocess.run(cmd, check=check, text=True)

    def session_name(self) -> str:
        return self.session

    def pane_target(self, workstream_id: int) -> str:
        ws = self.config.workstream(workstream_id)
        return ws.name if ws else f"ws{workstream_id}"

    def start(self, workstreams: List[Dict[str, Any]], command: Optional[str] = None) -> None:
        base_dir = self.config.base_path

        # Create (or attach to) the session in the background
        result = self._zj(
            "attach", self.session, "--create",
            "--", "sleep", "999999",
            check=False,
        )
        _ = result

        for i, ws in enumerate(workstreams):
            ws_name = ws.get("name", f"ws{ws.get('id', i + 1)}")
            # Create a tab per workstream
            self._zj("action", "new-tab", "--name", ws_name, check=False)
            ws_path = f"{base_dir}/{ws.get('path', '')}"
            ws_command = command or ws.get("command") or ""
            if ws_command:
                pane_env = ws.get("env") or {}
                env_prefix = " ".join(f"{k}={v}" for k, v in pane_env.items())
                full = f"cd {ws_path} && {env_prefix} {ws_command}".strip()
                self._zj("run", "--", "bash", "-lc", full, check=False)

        print(f"Started {len(workstreams)} workstream(s) in zellij session '{self.session}'")
        print(f"  Attach: zellij attach {self.session}")

    def attach(self, session: Optional[str] = None) -> None:
        self._zj("attach", session or self.session, check=False, capture=False)

    def send_command(self, workstream_id: int, command: str) -> bool:
        """Zellij has no simple `send-keys` equivalent; use `zellij run`.

        This runs the command in the *current* tab of the session. For
        per-tab targeting you'd need the Zellij RPC API; for now we log
        a notice and run in the foreground tab.
        """
        import sys
        print(
            f"[workstreams] zellij: send_command targets current tab only; "
            f"run: {command}",
            file=sys.stderr,
        )
        self._zj("run", "--", "bash", "-lc", command, check=False)
        return True

    def capture(self, lines: int = 20) -> List[str]:
        """Read the last N lines from the workstream's log file.

        Zellij has no built-in pane-capture CLI like `tmux capture-pane`,
        so we read from the per-workstream log file instead. This is the
        most reliable cross-platform source and works even when the
        zellij session is not attached.
        """
        import os
        log_file = os.environ.get("WORKSTREAMS_ZELLIJ_LOG")
        if not log_file:
            return []
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return [ln.rstrip("\n") for ln in all_lines[-lines:]]
        except OSError:
            return []

    def is_available(self) -> bool:
        import shutil
        return shutil.which("zellij") is not None

    def is_running(self) -> bool:
        result = self._zj("list-sessions", check=False)
        return self.session in (result.stdout or "")
