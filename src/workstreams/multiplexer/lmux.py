"""Native lmux multiplexer.

lmux is a Linux terminal multiplexer built specifically for AI coding
agents. It is NOT tmux-compatible: its CLI speaks its own verb-dialect
(``workspace.create``, ``surface.send_text``, ``read-screen`` ...), backed
by a JSON-over-Unix-socket protocol. This class drives that protocol
directly via :class:`LmuxClient` — no tmux-dialect faking.

Model mapping
-------------
- workspace  ≈ session (one per workstreams project)
- surface    ≈ tab/window (one per workstream)
- pane       ≈ split (lmux splits within a surface)

The workstream->surface ID map is persisted to the shared JSONL event log
so that re-invocations of ``dispatch``/``capture`` target the same surface
deterministically.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from .base import MultiplexerBase
from .lmux_client import LmuxClient, default_socket_path


class LmuxMultiplexer(MultiplexerBase):
    """Native lmux workstream management (JSON socket protocol)."""

    name = "lmux"

    def __init__(self, config: Any):
        super().__init__(config)
        self.session = f"workstreams-{config.project}"
        self._client: Optional[LmuxClient] = None
        self._workspace_id: Optional[int] = None
        self._surface_map: Dict[int, int] = {}  # workstream_id -> surface_id

    # ------------------------------------------------------------------ #
    # Client
    # ------------------------------------------------------------------ #
    @property
    def _cli(self) -> LmuxClient:
        if self._client is None:
            self._client = LmuxClient.ensure_daemon()
        return self._client

    # ------------------------------------------------------------------ #
    # Base interface
    # ------------------------------------------------------------------ #
    def session_name(self) -> str:
        return self.session

    def pane_target(self, workstream_id: int) -> str:
        """lmux targets surfaces by numeric id, not `session:win.pane` strings.

        Return the recorded surface id as a string, or ``""`` if unknown.
        """
        self._restore_surface_map()
        sid = self._surface_map.get(workstream_id)
        return str(sid) if sid is not None else ""

    def binary_name(self) -> str:
        return "lmux"

    def is_available(self) -> bool:
        return LmuxClient.binary_available()

    def start(self, workstreams: List[Dict[str, Any]], command: Optional[str] = None) -> None:
        client = self._cli
        # Idempotent: reuse an existing workspace with the same name.
        existing = client.cmd("workspace.list", {})
        workspace_id = self._find_workspace(existing)
        if workspace_id is None:
            reply = client.cmd("workspace.create", {"title": self.session})
            workspace_id = self._as_int(reply, "id")
        self._workspace_id = workspace_id

        for i, ws in enumerate(workstreams):
            ws_id = int(ws.get("id", i + 1))
            ws_name = ws.get("name", f"ws{ws_id}")
            reply = client.cmd(
                "surface.create", {"workspace": workspace_id, "title": ws_name}
            )
            surface_id = self._as_int(reply, "id")
            self._surface_map[ws_id] = surface_id

            # Run the workstream's command (or a global default) in this surface.
            ws_cmd = command or ws.get("command") or ""
            if ws_cmd:
                path = ws.get("path", "")
                if path:
                    ws_cmd = f"cd {path} && {ws_cmd}"
                client.cmd(
                    "surface.send_text",
                    {"surface": surface_id, "workspace": workspace_id, "text": ws_cmd},
                )

        self._persist_surface_map()
        print(f"Started {len(workstreams)} workstream(s) in lmux workspace '{self.session}'")
        print(f"  Observe: lmux tree  ·  Attach a TUI: lmux (workspace '{self.session}')")

    def attach(self, session: Optional[str] = None) -> None:
        # lmux is spawn-and-observe oriented; interactive attach is best-effort.
        target = session or self.session
        print(f"Attach to lmux workspace '{target}': run `lmux` and select it, or `lmux tree`.")
        print("  (lmux has no blocking attach; surfaces are spawned for agents to observe.)")

    def send_command(self, workstream_id: int, command: str) -> bool:
        """Send `command` to the recorded surface for `workstream_id`."""
        self._restore_surface_map()
        surface_id = self._surface_map.get(workstream_id)
        if surface_id is None:
            print(
                f"[workstreams] lmux: no surface recorded for workstream "
                f"{workstream_id}; run `workstreams start` first.",
                file=sys.stderr,
            )
            return False
        client = self._cli
        reply = client.cmd(
            "surface.send_text",
            {"surface": surface_id, "workspace": self._workspace_id, "text": command},
        )
        return self._ok(reply)

    def capture(self, workstream_id: int, lines: int = 20) -> List[str]:
        """Read the recorded surface's terminal screen via ``read-screen``."""
        self._restore_surface_map()
        surface_id = self._surface_map.get(workstream_id)
        if surface_id is None:
            return []
        return self._capture_surface(surface_id, lines=lines)

    def _capture_surface(self, surface_id: int, lines: int = 20) -> List[str]:
        client = self._cli
        reply = client.cmd(
            "read-screen", {"surface": surface_id, "workspace": self._workspace_id}
        )
        result = self._result(reply)
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        raw_lines = [ln.rstrip() for ln in text.splitlines()]
        return raw_lines[-lines:]

    def list_windows(self) -> List[Dict[str, Any]]:
        client = self._cli
        reply = client.cmd("surface.list", {})
        result = self._result(reply)
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        out: List[Dict[str, Any]] = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            out.append({"raw": ln})
        return out

    def kill(self) -> None:
        if self._workspace_id is not None:
            # workspace.close extracts the id as a string from the JSON args.
            self._cli.cmd("workspace.close", {"id": str(self._workspace_id)})

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _result(reply: Any) -> Any:
        """Unwrap the lmux daemon envelope.

        Every JSON reply is ``{"ok": bool, "result": {...}}`` (or
        ``{"ok": false, "error": ...}``). Some text-only verbs return a
        bare ``{"text": ...}`` payload with no envelope. Return the inner
        result, or the payload itself when there is no envelope.
        """
        if isinstance(reply, dict):
            if "result" in reply:
                return reply["result"]
            return reply
        return reply

    def _find_workspace(self, list_reply: Dict[str, Any]) -> Optional[int]:
        """Find an existing workspace with our session name (idempotent start)."""
        result = self._result(list_reply)
        if not isinstance(result, dict):
            return None
        # workspace.list replies carry the list under "workspaces".
        workspaces = result.get("workspaces")
        if isinstance(workspaces, list):
            for w in workspaces:
                if isinstance(w, dict) and w.get("title") == self.session:
                    wid = w.get("id")
                    if isinstance(wid, int):
                        return wid
                    if isinstance(wid, str) and wid.isdigit():
                        return int(wid)
            return None
        # Fall back to text form: parse "title (id=N)" lines.
        import re
        text = result.get("text", "") if "text" in result else json.dumps(result)
        m = re.search(rf"{re.escape(self.session)}[^0-9]*\(?id=(\d+)\)?", text)
        return int(m.group(1)) if m else None

    @classmethod
    def _as_int(cls, reply: Any, key: str = "id") -> int:
        result = cls._result(reply)
        if isinstance(result, dict):
            v = result.get(key)
            if isinstance(v, int):
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
        raise RuntimeError(f"lmux: expected int id in reply: {reply!r}")

    @staticmethod
    def _ok(reply: Any) -> bool:
        """Check if an lmux reply indicates success.

        Returns True only if the reply explicitly indicates success
        (has "ok" key with truthy value). Returns False for any
        unknown or error status, including non-dict replies.
        """
        if not isinstance(reply, dict):
            # Non-dict reply - unknown format, assume failure
            return False
        if "ok" in reply:
            return bool(reply["ok"])
        # Dict reply without "ok" key - cannot confirm success
        return False

    def _map_path(self) -> str:
        data_dir = os.environ.get("WORKSTREAMS_DATA_DIR", ".workstreams")
        return os.path.join(data_dir, f"{self.session}.surfaces.json")

    def _persist_surface_map(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._map_path()), exist_ok=True)
            with open(self._map_path(), "w", encoding="utf-8") as f:
                json.dump(
                    {"workspace": self._workspace_id, "surfaces": self._surface_map},
                    f,
                )
        except OSError:
            pass

    def _restore_surface_map(self) -> None:
        if self._surface_map:
            return
        try:
            with open(self._map_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self._workspace_id = data.get("workspace") or self._workspace_id
            self._surface_map = {int(k): int(v) for k, v in data.get("surfaces", {}).items()}
        except (OSError, ValueError, json.JSONDecodeError):
            self._surface_map = {}
