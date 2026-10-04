"""Native wmux multiplexer.

wmux is an Electron GUI terminal multiplexer with NO usable CLI (every
``wmux <verb>`` launches the GUI and blocks), so it must be driven over its
daemon sockets. Protocol verified live against wmux 3.66.0:

Control pipe
    ``$WMUX_SOCKET_PATH`` > ``~/.wmux{suffix}/daemon.sock`` >
    ``~/.wmux{suffix}.sock`` > ``~/.wmux-daemon{suffix}.sock``.
    Newline-delimited JSON: request ``{"id", "method", "params", "token"}``
    -> one line ``{"id", "ok", "result" | "error"}``. The token travels per
    frame (``$WMUX_AUTH_TOKEN`` > ``~/.wmux{suffix}/daemon-auth-token`` >
    ``~/.wmux-auth-token``); a wrong token yields
    ``{"ok": false, "error": "unauthorized"}`` plus a closed socket. There is
    NO handshake and no approval prompt — third-party tokens may call the
    session lifecycle methods directly. EVERY call sets a timeout, and
    connection drops are retried (the daemon rate-limits ~20 conns/s).

Workstream mapping
    tmux windows <-> wmux sessions ``ws-<project>-<n>`` created with
    ``daemon.createSession`` (a persistent shell, like tmux ``exec bash -i``).
    Commands are typed into the session's pty the tmux send-keys way, so the
    session outlives them. Input uses the per-session pipe
    ``~/.wmux{suffix}/session-<id>.sock``: connect, send ``<token>\\n``, read
    until the ``\\0WMUX_FLUSH_DONE:<token>\\0`` marker, then write the command
    (bytes after the auth line go STRAIGHT to the pty — append ``\\n`` to
    submit). The pipe accepts ONE client: if the pane is open in the GUI the
    dispatch fails with a clear error. Capture reads ``daemon.readSessionText``
    (no pipe needed). The workstream->session map is persisted as JSON, the
    same pattern as lmux.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from .base import MultiplexerBase

#: Daemon contract for session ids (spawnSession + assertExternalSessionId).
#: The ``auto-`` prefix is reserved for scheduled runs — our ``ws-`` is safe.
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_FLUSH_TIMEOUT = 5.0
_PIPE_CONNECT_ATTEMPTS = 3
_PIPE_RETRY_SLEEP = 0.35
_ATTACH_POLL_SECONDS = 1.5
_CONTROL_CONNECT_ATTEMPTS = 3


def _wmux_home() -> str:
    suffix = os.environ.get("WMUX_DATA_SUFFIX", "")
    return os.path.join(os.path.expanduser("~"), f".wmux{suffix}")


def default_socket_path() -> str:
    """Return the wmux control-pipe path for the current user.

    Env override wins; otherwise prefer the live daemon socket, falling back
    to the legacy pipe names. When no candidate exists, return the primary
    path so error messages point somewhere sensible.
    """
    env = os.environ.get("WMUX_SOCKET_PATH")
    if env:
        return env
    home = os.path.expanduser("~")
    suffix = os.environ.get("WMUX_DATA_SUFFIX", "")
    candidates = [
        os.path.join(home, f".wmux{suffix}", "daemon.sock"),
        os.path.join(home, f".wmux{suffix}.sock"),
        os.path.join(home, f".wmux-daemon{suffix}.sock"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def session_socket_path(session_id: str) -> str:
    """Return the per-session input pipe path (getSessionSocketPath)."""
    return os.path.join(_wmux_home(), f"session-{session_id}.sock")


def _token_candidates() -> List[str]:
    home = os.path.expanduser("~")
    suffix = os.environ.get("WMUX_DATA_SUFFIX", "")
    return [
        os.path.join(home, f".wmux{suffix}", "daemon-auth-token"),
        os.path.join(home, ".wmux-auth-token"),
    ]


def _read_token() -> Optional[str]:
    env = os.environ.get("WMUX_AUTH_TOKEN")
    if env:
        return env
    for path in _token_candidates():
        try:
            with open(path, "r", encoding="utf-8") as f:
                token = f.read().strip()
                if token:
                    return token
        except OSError:
            continue
    return None


class _PipeBusy(RuntimeError):
    """Session pipe dropped us before the flush marker (occupied / rate-limited)."""


class WmuxClient:
    """Minimal newline-delimited JSON-RPC client for the wmux daemon."""

    name = "wmux"

    def __init__(self, socket_path: Optional[str] = None, timeout: float = 10.0):
        self.socket_path = socket_path or default_socket_path()
        self.timeout = timeout
        self.token = _read_token()

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Invoke ``method`` and return its ``result``. Raises on failure."""
        frame = {
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params if params is not None else {},
            "token": self.token,
        }
        reply = self._exchange(frame)
        if reply.get("ok"):
            return reply.get("result")
        error = str(reply.get("error") or "")
        if "unauthorized" in error.lower():
            if self.token is None:
                checked = ", ".join(["$WMUX_AUTH_TOKEN", *_token_candidates()])
                raise RuntimeError(
                    f"wmux: no auth token found (checked {checked}) — "
                    "is the wmux daemon running?"
                )
            raise RuntimeError(
                "wmux: unauthorized — the daemon rejected the auth token "
                "(stale token file? restart wmux)"
            )
        raise RuntimeError(f"wmux: {method} failed: {error or reply}")

    # ------------------------------------------------------------------ #
    # Wire protocol
    # ------------------------------------------------------------------ #
    def _exchange(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """One socket round-trip. ALWAYS sets a timeout — no hangs.

        Connection drops are retried: the daemon rate-limits incoming
        connections and may accept-then-drop them.
        """
        payload = (json.dumps(frame) + "\n").encode("utf-8")
        data = b""
        for attempt in range(_CONTROL_CONNECT_ATTEMPTS):
            data = b""
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.settimeout(self.timeout)
                    sock.connect(self.socket_path)
                    sock.sendall(payload)
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
            except socket.timeout as exc:
                raise RuntimeError(
                    f"wmux: no reply from the daemon at {self.socket_path} "
                    f"after {self.timeout}s"
                ) from exc
            except (ConnectionResetError, BrokenPipeError) as exc:
                if attempt == _CONTROL_CONNECT_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"wmux: the daemon kept dropping the connection at "
                        f"{self.socket_path} ({exc})"
                    ) from exc
                time.sleep(0.2)
                continue
            except OSError as exc:
                raise RuntimeError(
                    f"wmux socket I/O error on {self.socket_path}: {exc}"
                ) from exc
            if not data:
                # Accepted, then closed without a reply (rate limit / restart).
                if attempt == _CONTROL_CONNECT_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"wmux: the daemon closed the connection without a "
                        f"reply at {self.socket_path} (rate limited?)"
                    )
                time.sleep(0.2)
                continue
            break

        text = data.decode("utf-8", "replace").strip()
        if not text:
            raise RuntimeError(f"wmux: empty reply for {frame.get('method')}")
        try:
            reply = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"wmux: non-JSON reply for {frame.get('method')}: {text[:200]}"
            ) from exc
        if not isinstance(reply, dict):
            raise RuntimeError(f"wmux: unexpected reply shape: {reply!r}")
        return reply


class WmuxMultiplexer(MultiplexerBase):
    """Native wmux workstream management (session RPC + session pipes)."""

    name = "wmux"

    def __init__(self, config: Any):
        super().__init__(config)
        self.session = f"workstreams-{config.project}"
        self._client: Optional[WmuxClient] = None
        self._pane_map: Dict[int, Dict[str, str]] = {}  # ws_id -> {sessionId}

    # ------------------------------------------------------------------ #
    # Client
    # ------------------------------------------------------------------ #
    @property
    def _cli(self) -> WmuxClient:
        if self._client is None:
            self._client = WmuxClient()
        return self._client

    def _session_id(self, workstream_id: int) -> str:
        """Stable, daemon-valid session id: ``ws-<project>-<n>`` (<= 64 chars)."""
        project = re.sub(r"[^a-zA-Z0-9_-]", "-", str(self.config.project))
        suffix = f"-{int(workstream_id)}"
        budget = 64 - len("ws-") - len(suffix)
        if budget < 0:
            raise RuntimeError("wmux: project name too long for a session id")
        sid = f"ws-{project[:budget]}{suffix}"
        if not SESSION_ID_RE.match(sid):
            raise RuntimeError(
                f"wmux: cannot derive a valid session id from project "
                f"{self.config.project!r} (got {sid!r})"
            )
        return sid

    # ------------------------------------------------------------------ #
    # Base interface
    # ------------------------------------------------------------------ #
    def session_name(self) -> str:
        return self.session

    def pane_target(self, workstream_id: int) -> str:
        """wmux targets sessions by id; return the recorded sessionId (or "")."""
        self._restore_pane_map()
        entry = self._pane_map.get(workstream_id)
        return str(entry["sessionId"]) if entry and entry.get("sessionId") else ""

    def binary_name(self) -> str:
        return "wmux"

    def is_available(self) -> bool:
        return shutil.which("wmux") is not None

    def start(
        self, workstreams: List[Dict[str, Any]], command: Optional[str] = None
    ) -> None:
        client = self._cli
        listed = client.call("daemon.listSessions") or []
        existing = {
            str(s.get("id")) for s in listed if isinstance(s, dict) and s.get("id")
        }
        base_dir = self.config.base_path

        for i, ws in enumerate(workstreams):
            ws_id = int(ws.get("id", i + 1))
            sid = self._session_id(ws_id)

            if sid not in existing:
                params: Dict[str, Any] = {
                    "id": sid,
                    "cwd": base_dir,
                    "cols": 80,
                    "rows": 24,
                }
                shell = os.environ.get("SHELL")
                if shell:
                    params["cmd"] = shell
                try:
                    client.call("daemon.createSession", params)
                except RuntimeError as exc:
                    # A concurrent start may have won the race; reuse in that case.
                    if "already exists" not in str(exc):
                        raise
            self._pane_map[ws_id] = {"sessionId": sid}

            line = self._compose_line(ws, base_dir, command)
            if line:
                self._send_to_session(sid, line)

        self._persist_pane_map()
        print(
            f"Started {len(workstreams)} workstream(s) in wmux session '{self.session}'"
        )
        print("  Observe: wmux GUI — sessions are named ws-<project>-<n>.")

    def attach(self, session: Optional[str] = None) -> None:
        # wmux is a GUI: there is no blocking CLI attach to run here.
        target = session or self.session
        print(f"wmux session '{target}': open the wmux window to observe it.")

    def send_command(self, workstream_id: int, command: str) -> bool:
        self._restore_pane_map()
        entry = self._pane_map.get(workstream_id)
        if entry is None or not entry.get("sessionId"):
            print(
                f"[workstreams] wmux: no session recorded for workstream "
                f"{workstream_id}; run `workstreams start` first.",
                file=sys.stderr,
            )
            return False
        try:
            self._send_to_session(entry["sessionId"], command)
            return True
        except RuntimeError as exc:
            print(f"[workstreams] wmux: {exc}", file=sys.stderr)
            return False

    def capture(self, workstream_id: int, lines: int = 20) -> List[str]:
        self._restore_pane_map()
        entry = self._pane_map.get(workstream_id)
        if entry is None or not entry.get("sessionId"):
            return []
        reply = self._cli.call("daemon.readSessionText", {"id": entry["sessionId"]})
        if not isinstance(reply, dict) or reply.get("mode") != "rows":
            return []
        rows = reply.get("rows") or []
        texts = [str(r.get("text", "")).rstrip() for r in rows if isinstance(r, dict)]
        return [t for t in texts if t][-lines:]

    def list_windows(self) -> List[Dict[str, Any]]:
        self._restore_pane_map()
        if not self._pane_map:
            return []
        mapped = {
            str(e["sessionId"]) for e in self._pane_map.values() if e.get("sessionId")
        }
        listed = self._cli.call("daemon.listSessions") or []
        return [
            {"id": str(s.get("id")), "label": str(s.get("id"))}
            for s in listed
            if isinstance(s, dict) and str(s.get("id")) in mapped
        ]

    def kill(self) -> None:
        self._restore_pane_map()
        for entry in list(self._pane_map.values()):
            sid = entry.get("sessionId")
            if not sid:
                continue
            try:
                self._cli.call("daemon.destroySession", {"id": sid})
            except RuntimeError:
                pass  # best-effort teardown

    # ------------------------------------------------------------------ #
    # Session pipe (input path)
    # ------------------------------------------------------------------ #
    def _send_to_session(self, session_id: str, text: str) -> None:
        """Type ``text`` (plus Enter) into the session's pty via its pipe."""
        sock = self._pipe_connect(session_id)
        try:
            payload = text if text.endswith("\n") else text + "\n"
            sock.sendall(payload.encode("utf-8"))
            # Brief drain: swallow the pty echo / reflush tail, then go.
            sock.settimeout(0.3)
            try:
                while sock.recv(65536):
                    pass
            except (socket.timeout, OSError):
                pass
        finally:
            sock.close()

    def _pipe_connect(self, session_id: str) -> socket.socket:
        """Connect + authenticate against ``session-<id>.sock``.

        Creates the pipe (``daemon.attachSession``) when missing and retries
        transient drops (per-pipe rate limit, stale socket file).
        """
        path = session_socket_path(session_id)
        token = (self._cli.token or "").encode("utf-8")
        last_error: Optional[BaseException] = None
        for attempt in range(_PIPE_CONNECT_ATTEMPTS):
            if not os.path.exists(path):
                self._cli.call("daemon.attachSession", {"id": session_id})
                deadline = time.monotonic() + _ATTACH_POLL_SECONDS
                while not os.path.exists(path) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not os.path.exists(path):
                    raise RuntimeError(
                        f"wmux: session '{session_id}' has no live pipe "
                        "(destroyed or never created?) — run `workstreams start`."
                    )
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(_FLUSH_TIMEOUT)
                sock.connect(path)
                sock.sendall(token + b"\n")
                self._read_auth_flush(sock, session_id, token)
                return sock
            except _PipeBusy as exc:
                sock.close()
                last_error = exc
                if attempt < _PIPE_CONNECT_ATTEMPTS - 1:
                    time.sleep(_PIPE_RETRY_SLEEP)
                    continue
                break
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                # Stale socket file: SessionPipe.start() unlinks it itself on
                # re-attach, so drop it and force a fresh attachSession.
                sock.close()
                last_error = exc
                try:
                    if os.path.exists(path):
                        os.unlink(path)
                except OSError:
                    pass
                continue
            except RuntimeError:
                sock.close()
                raise
            except OSError as exc:
                sock.close()
                raise RuntimeError(
                    f"wmux: session pipe I/O error on {path}: {exc}"
                ) from exc
        raise RuntimeError(
            f"wmux: cannot use the pipe for session '{session_id}': {last_error} "
            "— the pane may be open in the wmux GUI (the pipe takes one client); "
            "close/detach it and retry."
        )

    def _read_auth_flush(
        self, sock: socket.socket, session_id: str, token: bytes
    ) -> None:
        """Validate auth and consume output until the flush marker.

        Returns once the marker is seen or the server goes quiet — input
        writes are safe either way (bytes go straight to the pty). Raises
        ``_PipeBusy`` when the server drops us before authenticating.
        """
        marker = b"\0WMUX_FLUSH_DONE:" + token + b"\0"
        tail = b""
        deadline = time.monotonic() + _FLUSH_TIMEOUT
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                return  # quiet server; input path is independent of the flush
            if not chunk:
                if b"AUTH_FAILED" in tail:
                    raise RuntimeError(
                        "wmux: session pipe rejected the auth token "
                        "(stale token file? restart wmux)"
                    )
                raise _PipeBusy(
                    f"the pipe for session '{session_id}' dropped the "
                    "connection before the flush marker"
                )
            tail = (tail + chunk)[-4096:]
            if b"AUTH_FAILED" in tail:
                raise RuntimeError(
                    "wmux: session pipe rejected the auth token "
                    "(stale token file? restart wmux)"
                )
            if marker in tail:
                return

    # ------------------------------------------------------------------ #
    # Command composition (mirrors the tmux multiplexer's send-keys form)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compose_line(ws: Dict[str, Any], base_dir: str, command: Optional[str]) -> str:
        segments: List[str] = []
        ws_path = ws.get("path") or ""
        if ws_path:
            segments.append(f"cd {shlex.quote(os.path.join(base_dir, ws_path))}")
        env = ws.get("env") or {}
        body_parts = [f"{k}={shlex.quote(str(v))}" for k, v in sorted(env.items())]
        ws_cmd = command or ws.get("command") or ""
        if ws_cmd:
            body_parts.append(ws_cmd)
        body = " ".join(body_parts)
        if segments and body:
            return f"{segments[0]} && {body}"
        return segments[0] if segments else body

    # ------------------------------------------------------------------ #
    # Session map persistence (same pattern as lmux)
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
            self._pane_map = {int(k): dict(v) for k, v in data.get("panes", {}).items()}
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            self._pane_map = {}
