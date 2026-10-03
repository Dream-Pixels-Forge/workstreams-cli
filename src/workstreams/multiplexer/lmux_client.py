"""Raw JSON-over-Unix-socket client for the lmux daemon.

lmux (Linux terminal multiplexer built for AI coding agents) is NOT
tmux-compatible: its CLI speaks its own verb-dialect
(``workspace.create``, ``surface.send_text``, ``read-screen`` ...). Under the
hood every one-shot subcommand is a JSON request over a Unix socket. This
client reproduces that wire protocol so workstreams can drive lmux natively.

Wire format (verified from ``lmux help`` + strace of the real binary):

    connect -> /run/user/<uid>/lmux.sock   (env LMUX_SOCKET / XDG_RUNTIME_DIR)
    write   -> {"cmd": "<name>", "args": {...}}\\n
    read    -> <json reply>\\n
    close

The daemon lazy-warms a PTY on the first command, so the first call after a
fresh daemon start can take a few seconds. We use a generous default timeout.
"""

from __future__ import annotations

import json
import os
import socket
import shutil
from typing import Any, Dict, Optional


def default_socket_path() -> str:
    """Return the lmux daemon socket path for the current user."""
    env = os.environ.get("LMUX_SOCKET")
    if env:
        return env
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "lmux.sock")


class LmuxClient:
    """Minimal lmux daemon client."""

    name = "lmux"

    def __init__(self, socket_path: Optional[str] = None, timeout: float = 10.0):
        self.socket_path = socket_path or default_socket_path()
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Protocol
    # ------------------------------------------------------------------ #
    def cmd(self, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a single JSON command and return the parsed JSON reply.

        Raises ``RuntimeError`` if the socket is missing or the reply can't
        be parsed.
        """
        args = args or {}
        payload = (json.dumps({"cmd": name, "args": args}) + "\n").encode("utf-8")
        if not os.path.exists(self.socket_path):
            raise RuntimeError(
                f"lmux daemon socket not found at {self.socket_path}. "
                "Start it with: lmux daemon"
            )
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            sock.sendall(payload)
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.close()
        except OSError as exc:
            raise RuntimeError(f"lmux socket I/O error: {exc}") from exc

        text = data.decode("utf-8", "replace").strip()
        if not text:
            # Some lmux verbs (tree, *.list) return human-readable text, not
            # JSON. Return it as a text payload so callers can still use it.
            return {"text": text}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    def ping(self) -> Dict[str, Any]:
        return self.cmd("ping")

    @staticmethod
    def binary_available() -> bool:
        """True if the lmux binary is on PATH."""
        return shutil.which("lmux") is not None

    @classmethod
    def ensure_daemon(cls, socket_path: Optional[str] = None) -> "LmuxClient":
        """Return a client, starting the daemon if the socket is missing.

        No-op start (idempotent) when a live socket already exists. Guarded
        by ``WORKSTREAMS_LMUX_NO_DAEMON`` to skip the auto-start.
        """
        client = cls(socket_path)
        if os.path.exists(client.socket_path):
            return client
        if os.environ.get("WORKSTREAMS_LMUX_NO_DAEMON"):
            return client  # caller will get a clean RuntimeError on .cmd()
        if not cls.binary_available():
            raise RuntimeError("lmux binary not found on PATH")
        import subprocess
        # Detached daemon; the socket appears within a couple seconds.
        proc = subprocess.Popen(
            ["lmux", "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        proc.wait(timeout=15)  # lmux daemon backgrounds itself; wait is short.
        return client
