"""Tests for the raw lmux JSON-over-socket client.

We spin up a fake lmux daemon on a temp Unix socket and assert the client
round-trips the JSON command/args protocol exactly as lmux expects.
"""

import json
import os
import socket
import tempfile
import threading
from typing import Any, Dict, List

import pytest


class _FakeLmuxDaemon:
    """Minimal fake lmux daemon: accept one connection, read a JSON line, reply."""

    def __init__(self, socket_path: str, responses: List[Dict[str, Any]]):
        self.socket_path = socket_path
        self.responses = list(responses)
        self.received: List[Dict[str, Any]] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(socket_path)
        self._server.listen(1)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            conn, _ = self._server.accept()
            conn.settimeout(5)
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            cmd = json.loads(data.decode())
            self.received.append(cmd)
            reply = self.responses.pop(0) if self.responses else {"ok": True}
            conn.sendall((json.dumps(reply) + "\n").encode())
            conn.close()
            if not self.responses:
                break


@pytest.fixture
def fake_daemon(tmp_path):
    socket_path = str(tmp_path / "lmux.sock")
    # One response per accept. Each test uses ONE command, so one slot suffices;
    # the list is long so the fake can serve multiple sequential accepts.
    responses = [
        {"id": 7, "title": "workstreams-demo"},
        {"id": 7, "title": "workstreams-demo"},
        {"id": 11},
        {"version": "1.0.0"},
    ]
    daemon = _FakeLmuxDaemon(socket_path, responses)
    daemon.start()
    yield socket_path, daemon
    try:
        daemon._server.close()
    except OSError:
        pass


def test_client_round_trips_json_command(fake_daemon):
    from workstreams.multiplexer.lmux_client import LmuxClient

    socket_path, daemon = fake_daemon
    client = LmuxClient(socket_path)
    # First accept serves the first queued response.
    reply = client.cmd("ping", {})
    assert reply == {"id": 7, "title": "workstreams-demo"}
    assert daemon.received[0] == {"cmd": "ping", "args": {}}


def test_client_sends_args_payload(fake_daemon):
    from workstreams.multiplexer.lmux_client import LmuxClient

    socket_path, daemon = fake_daemon
    client = LmuxClient(socket_path)
    reply = client.cmd("workspace.create", {"title": "workstreams-demo"})
    assert reply == {"id": 7, "title": "workstreams-demo"}
    assert daemon.received[0] == {"cmd": "workspace.create", "args": {"title": "workstreams-demo"}}


def test_client_surfaces_missing_socket():
    from workstreams.multiplexer.lmux_client import LmuxClient

    class _NoSocketClient(LmuxClient):
        def __init__(self):
            super().__init__("/nonexistent/lmux.sock")

    client = _NoSocketClient()
    # Missing socket must not hang; it should raise a clear error.
    with pytest.raises(RuntimeError):
        client.cmd("ping", {})
