"""Tmux multiplexer implementation.

Addressing model (verified against tmux 3.4):
- Each workstream gets its own tmux WINDOW named after the workstream
  (`new-window -n <name>`). Windows can be targeted by NAME:
  `<session>:<window-name>`.
- Each window hosts a persistent `bash -i` so the detached session never
  dies when its startup command exits.
- In the "tiled" layout all workstreams live in one window as panes and
  are targeted by index: `<session>:1.<pane-index>`.

NOTE: `select-pane -T` only sets a *display title* in tmux; it does NOT
make a pane addressable by that title. Window names (via `new-window -n`
/ `rename-window`) are the reliable target mechanism.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional

from .base import MultiplexerBase

# Start a persistent interactive shell in every window/pane so detached
# sessions stay alive after their first command finishes.
_PERSIST_SHELL = "exec bash -i"


class TmuxMultiplexer(MultiplexerBase):
    """Tmux-based workstream management."""

    name = "tmux"

    def __init__(self, config: Any):
        super().__init__(config)
        self.session = f"workstreams-{config.project}"

    # -- helpers -----------------------------------------------------------

    def _tmux(self, *args: str, check: bool = False, capture: bool = True) -> subprocess.CompletedProcess:
        cmd = ["tmux"] + list(args)
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        return subprocess.run(cmd, check=check, text=True)

    def _run_quiet(self, *args: str) -> None:
        """Run a tmux command, swallowing non-zero exits (best-effort layout)."""
        self._tmux(*args)

    def _ensure_session(self, base_dir: str) -> None:
        """Create the session if it does not exist yet."""
        result = self._tmux("has-session", "-t", self.session)
        if result.returncode != 0:
            create = self._tmux(
                "new-session", "-d", "-s", self.session, "-c", base_dir,
                _PERSIST_SHELL,
            )
            if create.returncode != 0:
                raise RuntimeError(
                    f"failed to create tmux session '{self.session}': "
                    f"{(create.stderr or '').strip() or create.stdout.strip()}"
                )
        # Warm the server / confirm session is up.
        self._tmux("list-windows", "-t", self.session)

    def _session_alive(self) -> bool:
        return self._tmux("has-session", "-t", self.session).returncode == 0

    def _window_target(self, window_name: str) -> str:
        """Target a window by its name."""
        return f"{self.session}:{window_name}"

    def session_name(self) -> str:
        return self.session

    def pane_target(self, workstream_id: int) -> str:
        """Return the target for a workstream.

        Tab/window layout: target by window NAME -> `<session>:<ws-name>`.
        Tiled layout: target by pane index -> `<session>:0.<pane-index>`.
        """
        ws = self.config.workstream(workstream_id)
        name = ws.name if ws else f"ws{workstream_id}"
        if self.config.layout in ("tiled", "grid"):
            idx = workstream_id - 1
            return f"{self.session}:0.{idx}"
        # Window-per-workstream: each workstream is a window named after it.
        return self._window_target(name)

    # -- required interface --------------------------------------------------

    def start(self, workstreams: List[Dict[str, Any]], command: Optional[str] = None) -> None:
        base_dir = self.config.base_path
        self._ensure_session(base_dir)

        layout = self.config.layout
        if layout in ("tiled", "grid"):
            self._layout_single_window_panes(workstreams, base_dir)
        else:
            self._layout_tab_windows(workstreams, base_dir)

        # Send each command to its window/pane.
        for i, ws in enumerate(workstreams):
            target = self._pane_target_for_index(i, layout)
            ws_command = command or ws.get("command") or ""
            if ws_command:
                ws_path = ws.get("path", "")
                pane_env = ws.get("env") or {}
                env_prefix = " ".join(f"{k}={v}" for k, v in pane_env.items())
                cd_part = f"cd {base_dir}/{ws_path} && " if ws_path else ""
                full = f"{cd_part}{env_prefix} {ws_command}".strip()
                self._run_quiet("send-keys", "-t", target, full, "Enter")

        print(f"Started {len(workstreams)} workstream(s) in tmux session '{self.session}'")
        print(f"  Attach: tmux attach -t {self.session}")
        print(f"  Or:     workstreams attach --multiplexer tmux")

    # -- layouts --------------------------------------------------------------

    def _layout_tab_windows(self, workstreams: List[Dict[str, Any]], base_dir: str) -> None:
        """One window per workstream - cleanest for coding agents."""
        first = True
        for i, ws in enumerate(workstreams):
            ws_name = ws.get("name", f"ws{ws.get('id', i + 1)}")
            ws_path = f"{base_dir}/{ws.get('path', '')}"
            if first:
                # Reuse the initial window: rename it to the first workstream.
                # Window indices start at 0. The session was created with a
                # single initial window at index 0, so target ":0".
                self._run_quiet("rename-window", "-t", f"{self.session}:0", ws_name)
                self._run_quiet("send-keys", "-t", f"{self.session}:0", f"cd {ws_path}", "Enter")
                first = False
            else:
                self._run_quiet(
                    "new-window", "-t", self.session,
                    "-n", ws_name, "-c", ws_path, _PERSIST_SHELL,
                )

    def _layout_single_window_panes(self, workstreams: List[Dict[str, Any]], base_dir: str) -> None:
        """All workstreams in one window as tiled panes."""
        for i, ws in enumerate(workstreams):
            ws_name = ws.get("name", f"ws{ws.get('id', i + 1)}")
            ws_path = f"{base_dir}/{ws.get('path', '')}"
            if i == 0:
                # First pane already exists; just cd it.
                self._run_quiet("send-keys", "-t", f"{self.session}:0.0", f"cd {ws_path}", "Enter")
                _ = ws_name
            else:
                split = "-h" if i % 2 == 1 else "-v"
                self._run_quiet(
                    "split-window", "-t", f"{self.session}:0", split,
                    "-c", ws_path, _PERSIST_SHELL,
                )
        self._run_quiet("select-layout", "-t", f"{self.session}:0", "tiled")

    def _pane_target_for_index(self, i: int, layout: str) -> str:
        """Target the i-th workstream given the layout."""
        if layout in ("tiled", "grid"):
            return f"{self.session}:0.{i}"
        # Window-per-workstream: window NAMES equal the workstream name.
        # Resolve the name from the config so we always hit the right window.
        ws = self.config.workstreams[i] if i < len(self.config.workstreams) else None
        name = ws.name if ws else f"ws{i + 1}"
        return self._window_target(name)

    # -- lifecycle -------------------------------------------------------------

    def attach(self, session: Optional[str] = None) -> None:
        target = session or self.session
        result = self._tmux("attach", "-t", target, capture=False, check=False)
        # attach blocks until the user detaches.
        _ = result

    def send_command(self, workstream_id: int, command: str) -> bool:
        target = self.pane_target(workstream_id)
        if not self._session_alive():
            print(
                f"[workstreams] tmux session '{self.session}' is not running. "
                "Run `workstreams start` first.",
                flush=True,
            )
            return False
        # Try the named window first; if tmux can't resolve that target
        # (stale name, or a session created outside workstreams), fall back
        # to the numeric window index so dispatches don't silently no-op.
        result = self._tmux("send-keys", "-t", target, command, "Enter")
        if result.returncode != 0:
            fallback = f"{self.session}:{workstream_id - 1}"
            result = self._tmux("send-keys", "-t", fallback, command, "Enter")
        return result.returncode == 0

    def capture(self, workstream_id: int, lines: int = 20) -> str:
        """Return the last `lines` of a workstream pane's output."""
        target = self.pane_target(workstream_id)
        result = self._tmux("capture-pane", "-t", target, "-p", "-S", f"-{lines}")
        return result.stdout.strip()

    def is_running(self) -> bool:
        return self._session_alive()

    def list_windows(self) -> List[str]:
        result = self._tmux("list-windows", "-t", self.session)
        if result.returncode != 0:
            return []
        return [w for w in result.stdout.strip().split("\n") if w]

    def kill(self) -> None:
        self._run_quiet("kill-session", "-t", self.session)
