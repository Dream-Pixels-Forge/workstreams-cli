"""Native wmux multiplexer.

wmux is an Electron GUI terminal multiplexer whose only control surface is a
JSON-RPC endpoint — it is NOT tmux-compatible, and driving it through the
tmux-compat shim hangs forever (every ``wmux <verb>`` invocation launches the
GUI and blocks). This module speaks the real wmux dialect directly:

Transport
    Unix socket ``~/.wmux.sock`` (``$WMUX_SOCKET_PATH`` / ``$WMUX_DATA_SUFFIX``
    variants), token from ``~/.wmux-auth-token`` (``$WMUX_AUTH_TOKEN``).
    Newline-delimited JSON: request ``{"id", "method", "params", "token",
    "clientName", "clientVersion"}`` -> response ``{"id", "ok", "result" |
    "error", "rejection"?}``. EVERY socket call sets a timeout.

Handshake (required before any method works)
    1. ``mcp.identify {name, version}``
    2. ``mcp.declarePermissions {permissions: [...]}`` — capability-first, no
       reserved ``wmux.internal``. First use of a new capability may return
       "awaiting user approval (promptId=...)": a one-time human approval in
       the wmux window; we retry until granted (bounded).

Workstream mapping
    tmux windows <-> wmux panes, labeled via ``pane.setMetadata``; dispatch =
    ``input.send`` to the pane's ptyId. The workstream->pane map is persisted
    as JSON so later ``dispatch``/``capture`` invocations target the same panes.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from .base import MultiplexerBase

CLIENT_NAME = "workstreams"

#: Capabilities workstreams needs. ``wmux.internal`` is reserved and fails
#: the whole call, so it must never appear here.
PERMISSIONS = [
    "workspace.read",
    "pane.read",
    "pane.write",
    "pane.create",
    "terminal.send",
    "terminal.read",
    "meta.write",
]

_LABEL_MAX = 64
_APPROVAL_POLL_SECONDS = 0.5
_APPROVAL_MAX_ATTEMPTS = 60  # bounded: never hang forever waiting for a human


def _client_version() -> str:
    try:
        from workstreams import __version__
        return __version__
    except Exception:
        return "0"


def default_socket_path() -> str:
    """Return the wmux RPC socket path for the current user."""
    env = os.environ.get("WMUX_SOCKET_PATH")
    if env:
        return env
    suffix = os.environ.get("WMUX_DATA_SUFFIX", "")
    return os.path.join(os.path.expanduser("~"), f".wmux{suffix}.sock")


def _read_token() -> Optional[str]:
    env = os.environ.get("WMUX_AUTH_TOKEN")
    if env:
        return env
    try:
        with open(os.path.join(os.path.expanduser("~"), ".wmux-auth-token"), "r", encoding="utf-8") as f:
            token = f.read().strip()
            return token or None
    except OSError:
        return None


class WmuxClient:
    """Minimal newline-delimited JSON-RPC client for the wmux daemon."""

    name = "wmux"

    def __init__(self, socket_path: Optional[str] = None, timeout: float = 10.0):
        self.socket_path = socket_path or default_socket_path()
        self.timeout = timeout
        self.token = _read_token()
        self.handshaken = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def ensure_handshake(self) -> None:
        """``mcp.identify`` + ``mcp.declarePermissions`` (idempotent)."""
        if self.handshaken:
            return
        self._request("mcp.identify", {"name": CLIENT_NAME, "version": _client_version()})
        self._request("mcp.declarePermissions", {"permissions": list(PERMISSIONS)})
        self.handshaken = True

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Invoke ``method`` and return its ``result``. Raises on failure."""
        if not method.startswith("mcp."):
            self.ensure_handshake()
        return self._request(method, params or {})

    # ------------------------------------------------------------------ #
    # Wire protocol
    # ------------------------------------------------------------------ #
    def _build_frame(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
            "token": self.token,
            "clientName": CLIENT_NAME,
            "clientVersion": _client_version(),
        }

    def _request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send one request, handling capability-approval retries."""
        frame = self._build_frame(method, params)
        last_error = ""
        for _ in range(_APPROVAL_MAX_ATTEMPTS):
            reply = self._exchange(frame)
            if reply.get("ok"):
                return reply.get("result")
            error = str(reply.get("error") or "")
            rejection = reply.get("rejection") or {}
            status = str(rejection.get("status") or "")
            if "awaiting" in error.lower() or "await" in status.lower():
                # One-time human approval in the wmux window -> poll again.
                last_error = error or status
                time.sleep(_APPROVAL_POLL_SECONDS)
                continue
            raise RuntimeError(
                f"wmux: {method} failed: {error or rejection or reply}"
            )
        raise RuntimeError(
            f"wmux: {method} still awaiting user approval after "
            f"{_APPROVAL_MAX_ATTEMPTS} attempts ({last_error}). "
            "Approve the prompt in the wmux window and retry."
        )

    def _exchange(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """One socket round-trip. ALWAYS sets a timeout — no hangs."""
        payload = (json.dumps(frame) + "\n").encode("utf-8")
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(payload)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            finally:
                sock.close()
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise RuntimeError(
                f"wmux is not running: cannot connect to {self.socket_path} "
                f"({exc}). Start wmux first (e.g. launch the wmux app / "
                "`wmux daemon`) and retry."
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"wmux socket I/O error on {self.socket_path}: {exc}") from exc

        text = data.decode("utf-8", "replace").strip()
        if not text:
            raise RuntimeError(f"wmux: empty reply for {frame.get('method')}")
        try:
            reply = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"wmux: non-JSON reply for {frame.get('method')}: {text[:200]}") from exc
        if not isinstance(reply, dict):
            raise RuntimeError(f"wmux: unexpected reply shape: {reply!r}")
        return reply


class WmuxMultiplexer(MultiplexerBase):
    """Native wmux workstream management (JSON-RPC over Unix socket)."""

    name = "wmux"

    def __init__(self, config: Any):
        super().__init__(config)
        self.session = f"workstreams-{config.project}"
        self._client: Optional[WmuxClient] = None
        self._pane_map: Dict[int, Dict[str, str]] = {}  # ws_id -> {paneId, ptyId}

    # ------------------------------------------------------------------ #
    # Client
    # ------------------------------------------------------------------ #
    @property
    def _cli(self) -> WmuxClient:
        if self._client is None:
            self._client = WmuxClient()
        return self._client

    # ------------------------------------------------------------------ #
    # Base interface
    # ------------------------------------------------------------------ #
    def session_name(self) -> str:
        return self.session

    def pane_target(self, workstream_id: int) -> str:
        """wmux targets panes by id; return the recorded paneId (or "")."""
        self._restore_pane_map()
        entry = self._pane_map.get(workstream_id)
        return str(entry["paneId"]) if entry else ""

    def binary_name(self) -> str:
        return "wmux"

    def is_available(self) -> bool:
        return shutil.which("wmux") is not None

    def start(self, workstreams: List[Dict[str, Any]], command: Optional[str] = None) -> None:
        client = self._cli
        client.ensure_handshake()  # fails fast when the socket is absent

        listed = client.call("pane.list") or {}
        panes = listed.get("panes") if isinstance(listed, dict) else None
        panes = panes if isinstance(panes, list) else []
        by_label = {
            str((p.get("metadata") or {}).get("label", "")): p
            for p in panes
            if isinstance(p, dict)
        }

        # Pass 1: reuse labeled panes, split+label the rest. Track ids locally
        # so we don't depend on pane.list reflecting setMetadata immediately.
        pane_id_by_ws: Dict[int, Any] = {}
        for i, ws in enumerate(workstreams):
            ws_id = int(ws.get("id", i + 1))
            label = str(ws.get("name") or f"ws{ws_id}")[:_LABEL_MAX]
            pane = by_label.get(label)
            if pane is not None:
                pane_id_by_ws[ws_id] = pane
                continue
            reply = client.call("pane.split", {"direction": "horizontal"}) or {}
            pane_id = reply.get("paneId") if isinstance(reply, dict) else None
            if pane_id is None:
                raise RuntimeError(f"wmux: pane.split returned no paneId: {reply!r}")
            client.call("pane.setMetadata", {"paneId": pane_id, "label": label})
            pane_id_by_ws[ws_id] = pane_id

        # Pass 2: re-list so freshly split panes carry their ptyIds.
        listed = client.call("pane.list") or {}
        panes = listed.get("panes") if isinstance(listed, dict) else []
        pty_by_pane = {}
        for p in panes or []:
            if not isinstance(p, dict):
                continue
            ptys = p.get("surfacePtyIds") or []
            if ptys:
                pty_by_pane[p.get("id")] = ptys[0]

        for i, ws in enumerate(workstreams):
            ws_id = int(ws.get("id", i + 1))
            pane = pane_id_by_ws[ws_id]
            pane_id = pane.get("id") if isinstance(pane, dict) else pane
            pty_id = pty_by_pane.get(pane_id)
            if not pty_id:
                label = str(ws.get("name") or f"ws{ws_id}")[:_LABEL_MAX]
                raise RuntimeError(
                    f"wmux: pane {pane_id!r} ({label}) has no surfacePtyIds"
                )
            self._pane_map[ws_id] = {"paneId": pane_id, "ptyId": pty_id}

            ws_cmd = command or ws.get("command") or ""
            if ws_cmd:
                client.call(
                    "input.send",
                    {"ptyId": pty_id, "text": ws_cmd, "submit": True},
                )

        self._persist_pane_map()
        print(f"Started {len(workstreams)} workstream(s) in wmux (session '{self.session}')")
        print("  Observe: wmux GUI — panes are labeled per workstream.")

    def attach(self, session: Optional[str] = None) -> None:
        # wmux is a GUI: there is no blocking CLI attach to run here.
        target = session or self.session
        print(f"wmux session '{target}': open the wmux window; panes are labeled per workstream.")

    def send_command(self, workstream_id: int, command: str) -> bool:
        self._restore_pane_map()
        entry = self._pane_map.get(workstream_id)
        if entry is None:
            print(
                f"[workstreams] wmux: no pane recorded for workstream "
                f"{workstream_id}; run `workstreams start` first.",
                file=sys.stderr,
            )
            return False
        reply = self._cli.call(
            "input.send",
            {"ptyId": entry["ptyId"], "text": command, "submit": True},
        )
        if isinstance(reply, dict):
            return bool(reply.get("ok"))
        return False

    def capture(self, workstream_id: int, lines: int = 20) -> List[str]:
        self._restore_pane_map()
        entry = self._pane_map.get(workstream_id)
        if entry is None:
            return []
        reply = self._cli.call("input.readScreen", {"ptyId": entry["ptyId"]})
        text = reply.get("text", "") if isinstance(reply, dict) else str(reply or "")
        return [ln.rstrip() for ln in text.splitlines()][-lines:]

    def list_windows(self) -> List[Dict[str, Any]]:
        reply = self._cli.call("pane.list") or {}
        panes = reply.get("panes") if isinstance(reply, dict) else []
        out: List[Dict[str, Any]] = []
        for p in panes or []:
            if isinstance(p, dict):
                out.append({"id": p.get("id"),
                            "label": (p.get("metadata") or {}).get("label", "")})
        return out

    def kill(self) -> None:
        self._restore_pane_map()
        for entry in self._pane_map.values():
            try:
                self._cli.call("pane.close", {"id": entry["paneId"]})
            except RuntimeError:
                pass  # best-effort teardown

    # ------------------------------------------------------------------ #
    # Pane map persistence (same pattern as lmux)
    # ------------------------------------------------------------------ #
    def _map_path(self) -> str:
        data_dir = os.environ.get("WORKSTREAMS_DATA_DIR", ".workstreams")
        return os.path.join(data_dir, f"{self.session}.panes.json")

    def _persist_pane_map(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._map_path()), exist_ok=True)
            with open(self._map_path(), "w", encoding="utf-8") as f:
                json.dump({"panes": self._pane_map}, f)
        except OSError:
            pass

    def _restore_pane_map(self) -> None:
        if self._pane_map:
            return
        try:
            with open(self._map_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self._pane_map = {
                int(k): dict(v) for k, v in data.get("panes", {}).items()
            }
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            self._pane_map = {}
