"""TDD tests for the native wmux multiplexer (issue #4, protocol-corrected).

wmux is an Electron GUI terminal multiplexer controlled ONLY via newline-
delimited JSON-RPC on ``~/.wmux{suffix}/daemon.sock`` plus a per-session
input pipe. The old tmux-compat shim hung forever; the first native
implementation spoke a fabricated dialect (``mcp.*`` / ``pane.*``) that does
not exist in wmux 3.66.0. These tests pin the REAL protocol: per-frame
token auth with no handshake, session-per-workstream mapping via
``daemon.createSession``, dispatch through ``session-<id>.sock`` (auth line
-> flush marker -> raw pty input), capture via ``daemon.readSessionText``,
and fail-fast when the control pipe is absent.
"""

from __future__ import annotations

import os
import socket
import threading
from typing import Any, Dict, List

import pytest


def _mk_config(tmp_path, project="demo", ws_names=("alpha", "beta")):
    from workstreams.models import WorkstreamsConfig, WorkstreamConfig

    ws1 = WorkstreamConfig(id=1, name=ws_names[0], path="a", branch="b", command="")
    ws2 = WorkstreamConfig(id=2, name=ws_names[1], path="b", branch="b", command="")
    return WorkstreamsConfig(
        project=project,
        multiplexer="wmux",
        base_path=str(tmp_path),
        workstreams=[ws1, ws2],
    )


@pytest.fixture
def config(tmp_path, monkeypatch):
    # Point the client at a guaranteed-missing socket by default.
    monkeypatch.setenv("WMUX_SOCKET_PATH", str(tmp_path / "missing.wmux.sock"))
    monkeypatch.delenv("WMUX_AUTH_TOKEN", raising=False)
    # Persist pane maps under tmp, not the repo working dir.
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path / "data"))
    return _mk_config(tmp_path)


class FakeWmuxClient:
    """Scriptable stand-in for WmuxClient (records calls, canned replies)."""

    def __init__(self, replies: Dict[str, Any] | None = None):
        self.calls: List[Dict[str, Any]] = []
        self.replies = replies or {}
        self.token = "fake-token"

    def call(self, method: str, params: Dict[str, Any] | None = None) -> Any:
        self.calls.append({"method": method, "params": params or {}})
        if method in self.replies:
            r = self.replies[method]
            return r(self.calls) if callable(r) else r
        return {"ok": True}

    @property
    def methods(self) -> List[str]:
        return [c["method"] for c in self.calls]


def _record_sender(mux):
    """Replace the session-pipe sender with a recorder (no real sockets)."""
    sent: List[Any] = []
    mux._send_to_session = lambda sid, line: sent.append((sid, line))  # type: ignore[method-assign]
    return sent


# --------------------------------------------------------------------- #
# Registration / no-hang guarantees
# --------------------------------------------------------------------- #


def test_wmux_registered_as_native_multiplexer():
    """wmux must NOT go through the tmux-compat shim (that hung forever)."""
    from workstreams import multiplexer as mp

    assert "wmux" not in mp._TMUX_COMPATIBLE
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    assert mp.get_multiplexer.__module__  # sanity
    import workstreams.models as models

    cfg = models.WorkstreamsConfig(project="demo", multiplexer="wmux", base_path="/tmp")
    mux = mp.get_multiplexer("wmux", cfg)
    assert isinstance(mux, WmuxMultiplexer)


def test_wmux_removed_from_tmux_compat_map():
    from workstreams import multiplexer as mp

    assert set(mp._TMUX_COMPATIBLE) == {"nami", "herdr"}


def test_start_fails_fast_when_socket_absent(config, capsys):
    """No hang: a missing control pipe must raise immediately with a clear error."""
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    with pytest.raises(RuntimeError, match="wmux is not running"):
        mux.start([{"id": 1, "name": "alpha"}])


# --------------------------------------------------------------------- #
# Socket / token resolution (matches getDaemonSocketPath / getDaemonAuthTokenPath)
# --------------------------------------------------------------------- #


def test_default_socket_path_env_override(monkeypatch, tmp_path):
    from workstreams.multiplexer.wmux import default_socket_path

    monkeypatch.setenv("WMUX_SOCKET_PATH", str(tmp_path / "custom.sock"))
    assert default_socket_path() == str(tmp_path / "custom.sock")


def test_default_socket_path_prefers_daemon_socket(monkeypatch, tmp_path):
    from workstreams.multiplexer.wmux import default_socket_path

    monkeypatch.delenv("WMUX_SOCKET_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WMUX_DATA_SUFFIX", "-test")
    # No sockets exist yet -> primary candidate ~/.wmux-test/daemon.sock.
    assert default_socket_path() == str(tmp_path / ".wmux-test" / "daemon.sock")
    # With the live daemon socket present, it wins over legacy names.
    (tmp_path / ".wmux-test").mkdir()
    (tmp_path / ".wmux-test" / "daemon.sock").touch()
    (tmp_path / ".wmux-test.sock").touch()
    assert default_socket_path() == str(tmp_path / ".wmux-test" / "daemon.sock")


def test_session_socket_path_uses_wmux_home(monkeypatch, tmp_path):
    from workstreams.multiplexer.wmux import session_socket_path

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WMUX_DATA_SUFFIX", "-x")
    assert session_socket_path("ws-demo-1") == str(
        tmp_path / ".wmux-x" / "session-ws-demo-1.sock"
    )


def test_token_read_env_then_home_file(monkeypatch, tmp_path):
    from workstreams.multiplexer.wmux import WmuxClient

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WMUX_AUTH_TOKEN", raising=False)

    # 1) env wins
    monkeypatch.setenv("WMUX_AUTH_TOKEN", "from-env")
    assert WmuxClient(socket_path="/no/such.sock").token == "from-env"
    monkeypatch.delenv("WMUX_AUTH_TOKEN")

    # 2) current-path token file
    tokdir = tmp_path / ".wmux"
    tokdir.mkdir()
    (tokdir / "daemon-auth-token").write_text("from-home\n")
    assert WmuxClient(socket_path="/no/such.sock").token == "from-home"

    # 3) legacy file fallback
    (tokdir / "daemon-auth-token").unlink()
    (tmp_path / ".wmux-auth-token").write_text("legacy-tok\n")
    assert WmuxClient(socket_path="/no/such.sock").token == "legacy-tok"

    # 4) nothing -> None
    (tmp_path / ".wmux-auth-token").unlink()
    assert WmuxClient(socket_path="/no/such.sock").token is None


# --------------------------------------------------------------------- #
# Client wire format + error mapping
# --------------------------------------------------------------------- #


def test_request_frame_shape_and_timeout_on_socket(config, monkeypatch):
    """Every socket call must set a timeout; frame is {id, method, params, token}."""
    from workstreams.multiplexer import wmux as wmux_mod
    import json as _json

    set_timeouts: List[Any] = []
    sent: List[bytes] = []

    class FakeSock:
        def settimeout(self, t):
            set_timeouts.append(t)

        def connect(self, path):
            self.path = path

        def sendall(self, data):
            sent.append(data)

        def recv(self, n):
            return b'{"id":"x","ok":true,"result":{}}\n'

        def close(self):
            pass

    monkeypatch.setattr(wmux_mod.socket, "socket", lambda *a, **k: FakeSock())

    client = wmux_mod.WmuxClient(socket_path="/tmp/fake.wmux.sock", timeout=3.5)
    client.call("daemon.listSessions", {})

    assert set_timeouts and all(t == 3.5 for t in set_timeouts)
    frame = _json.loads(sent[0].decode().strip())
    assert set(frame.keys()) == {"id", "method", "params", "token"}
    assert frame["method"] == "daemon.listSessions"
    assert frame["params"] == {}
    assert frame["id"]
    assert frame["token"] is None or isinstance(frame["token"], str)


def test_socket_absent_raises_not_running(config):
    from workstreams.multiplexer.wmux import WmuxClient

    client = WmuxClient(socket_path="/no/such/wmux.sock")
    with pytest.raises(RuntimeError, match="wmux is not running"):
        client.call("daemon.listSessions", {})


def test_unauthorized_reply_maps_to_token_error(config):
    from workstreams.multiplexer.wmux import WmuxClient

    client = WmuxClient(socket_path="/no/such.sock")
    client.token = "stale"
    client._exchange = lambda frame: {"ok": False, "error": "unauthorized"}  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="unauthorized"):
        client.call("daemon.listSessions", {})


def test_unauthorized_without_token_names_checked_paths(config, monkeypatch):
    from workstreams.multiplexer.wmux import WmuxClient

    monkeypatch.delenv("WMUX_AUTH_TOKEN", raising=False)
    client = WmuxClient(socket_path="/no/such.sock")
    client.token = None
    client._exchange = lambda frame: {"ok": False, "error": "unauthorized"}  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="no auth token found"):
        client.call("daemon.listSessions", {})


def test_failed_reply_raises_with_method_and_error(config):
    from workstreams.multiplexer.wmux import WmuxClient

    client = WmuxClient(socket_path="/no/such.sock")
    client._exchange = lambda frame: {  # type: ignore[method-assign]
        "ok": False,
        "error": "Session 'ws-demo-1' already exists",
    }
    with pytest.raises(RuntimeError, match="already exists"):
        client.call("daemon.createSession", {"id": "ws-demo-1"})


# --------------------------------------------------------------------- #
# Session ids
# --------------------------------------------------------------------- #


def test_session_ids_are_daemon_valid_and_stable(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer, SESSION_ID_RE

    mux = WmuxMultiplexer(config)
    assert mux._session_id(1) == "ws-demo-1"
    assert mux._session_id(2) == "ws-demo-2"
    assert SESSION_ID_RE.match(mux._session_id(1))


def test_session_id_sanitizes_project_and_fits_64_chars(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer, SESSION_ID_RE

    config.project = "my weird/project!name"
    mux = WmuxMultiplexer(config)
    one, two = mux._session_id(1), mux._session_id(99)
    assert SESSION_ID_RE.match(one) and SESSION_ID_RE.match(two)
    assert one != two

    config.project = "x" * 200
    mux = WmuxMultiplexer(config)
    one, two = mux._session_id(1), mux._session_id(2)
    assert len(one) <= 64 and len(two) <= 64
    assert one != two
    assert one.endswith("-1") and two.endswith("-2")


# --------------------------------------------------------------------- #
# Start: one session per workstream
# --------------------------------------------------------------------- #


def test_start_creates_one_session_per_workstream(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient({"daemon.listSessions": []})
    mux._client = fake
    sent = _record_sender(mux)

    mux.start(
        [
            {"id": 1, "name": "alpha", "path": "a", "command": ""},
            {"id": 2, "name": "beta", "path": "b", "command": ""},
        ]
    )

    creates = [c for c in fake.calls if c["method"] == "daemon.createSession"]
    assert len(creates) == 2
    for c in creates:
        assert c["params"]["cwd"] == str(config.base_path)
        assert c["params"]["id"].startswith("ws-demo-")
    assert mux._pane_map == {
        1: {"sessionId": "ws-demo-1"},
        2: {"sessionId": "ws-demo-2"},
    }
    # cd into each workstream path was typed into its session
    assert sent == [
        ("ws-demo-1", f"cd {config.base_path}/a"),
        ("ws-demo-2", f"cd {config.base_path}/b"),
    ]
    # map file exists for cross-process dispatch
    from pathlib import Path

    assert Path(mux._map_path()).exists()

    # fresh instance restores the map
    mux2 = WmuxMultiplexer(config)
    mux2._client = FakeWmuxClient({"daemon.listSessions": []})
    mux2._restore_pane_map()
    assert mux2._pane_map == mux._pane_map


def test_start_reuses_existing_sessions(config):
    """Idempotent start: sessions already known to the daemon are not recreated."""
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient(
        {
            "daemon.listSessions": [{"id": "ws-demo-1", "state": "detached"}],
        }
    )
    mux._client = fake
    _record_sender(mux)

    mux.start(
        [
            {"id": 1, "name": "alpha", "path": "", "command": ""},
            {"id": 2, "name": "beta", "path": "", "command": ""},
        ]
    )

    creates = [c for c in fake.calls if c["method"] == "daemon.createSession"]
    assert [c["params"]["id"] for c in creates] == ["ws-demo-2"]


def test_start_tolerates_create_race_already_exists(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    def duplicate(_calls):
        raise RuntimeError(
            "wmux: daemon.createSession failed: Session 'ws-demo-1' already exists"
        )

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient(
        {"daemon.listSessions": [], "daemon.createSession": duplicate}
    )
    mux._client = fake
    sent = _record_sender(mux)

    mux.start([{"id": 1, "name": "alpha", "path": "", "command": ""}])
    assert mux._pane_map[1] == {"sessionId": "ws-demo-1"}
    assert sent == []  # no path/command -> nothing typed


def test_start_composes_cd_env_command(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient({"daemon.listSessions": []})
    mux._client = fake
    sent = _record_sender(mux)

    mux.start(
        [
            {
                "id": 1,
                "name": "alpha",
                "path": "a",
                "command": "npm test",
                "env": {"K": "v"},
            }
        ],
        command=None,
    )
    assert sent == [("ws-demo-1", f"cd {config.base_path}/a && K=v npm test")]


def test_start_explicit_command_overrides_workstream_command(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient({"daemon.listSessions": []})
    mux._client = fake
    sent = _record_sender(mux)

    mux.start(
        [{"id": 1, "name": "alpha", "path": "", "command": "ignored"}],
        command="run this",
    )
    assert sent == [("ws-demo-1", "run this")]


# --------------------------------------------------------------------- #
# Dispatch / capture / list / kill
# --------------------------------------------------------------------- #


def test_send_command_writes_to_session_pipe(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient()
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}}
    sent = _record_sender(mux)

    assert mux.send_command(1, "echo hello") is True
    assert sent == [("ws-demo-1", "echo hello")]


def test_send_command_unknown_workstream_fails_loudly(config, capsys):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient()
    mux._pane_map = {}

    assert mux.send_command(1, "echo hello") is False
    err = capsys.readouterr().err
    assert "start" in err.lower()


def test_send_command_pipe_error_prints_and_returns_false(config, capsys):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient()
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}}

    def boom(sid, line):
        raise RuntimeError("the pipe for session 'ws-demo-1' dropped the connection")

    mux._send_to_session = boom  # type: ignore[method-assign]
    assert mux.send_command(1, "echo hi") is False
    assert "dropped" in capsys.readouterr().err


def test_capture_reads_session_rows(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient(
        {
            "daemon.readSessionText": {
                "ok": True,
                "mode": "rows",
                "rows": [
                    {"text": "l0 "},
                    {"text": "l1"},
                    {"text": "l2"},
                    {"text": "l3"},
                    {"text": "   "},
                ],
            }
        }
    )
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}}

    assert mux.capture(1, lines=2) == ["l2", "l3"]


def test_capture_unavailable_or_unmapped_returns_empty(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient(
        {"daemon.readSessionText": {"ok": True, "mode": "unavailable"}}
    )
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}}
    assert mux.capture(1) == []

    mux._pane_map = {}
    assert mux.capture(1) == []


def test_list_windows_filters_to_mapped_sessions(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient(
        {
            "daemon.listSessions": [
                {"id": "ws-demo-1", "state": "detached"},
                {"id": "daemon-other", "state": "detached"},
                {"id": "ws-demo-2", "state": "attached"},
            ]
        }
    )
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}, 2: {"sessionId": "ws-demo-2"}}

    assert mux.list_windows() == [
        {"id": "ws-demo-1", "label": "ws-demo-1"},
        {"id": "ws-demo-2", "label": "ws-demo-2"},
    ]


def test_list_windows_empty_map_returns_empty(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient()
    mux._pane_map = {}
    assert mux.list_windows() == []


def test_kill_destroys_mapped_sessions_best_effort(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient()
    mux._client = fake
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}, 2: {"sessionId": "ws-demo-2"}}

    original_call = fake.call

    def call(method, params=None):
        original_call(method, params)
        if (
            method == "daemon.destroySession"
            and params
            and params.get("id") == "ws-demo-1"
        ):
            raise RuntimeError("boom")
        return {"ok": True}

    fake.call = call  # type: ignore[method-assign]

    mux.kill()  # must not raise
    destroyed = [
        c["params"]["id"] for c in fake.calls if c["method"] == "daemon.destroySession"
    ]
    assert destroyed == ["ws-demo-1", "ws-demo-2"]


def test_pane_target_returns_session_id(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._pane_map = {1: {"sessionId": "ws-demo-1"}}
    assert mux.pane_target(1) == "ws-demo-1"
    assert mux.pane_target(9) == ""


# --------------------------------------------------------------------- #
# Session-pipe protocol (real unix socket, in-process daemon stand-in)
# --------------------------------------------------------------------- #


def test_session_pipe_auth_marker_and_input(config, monkeypatch, tmp_path):
    """End-to-end pipe dialect: token line -> flush marker -> raw pty input."""
    from workstreams.multiplexer import wmux as wmux_mod
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    monkeypatch.setenv("WMUX_AUTH_TOKEN", "sekrit")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WMUX_DATA_SUFFIX", raising=False)

    sid = "ws-demo-1"
    path = wmux_mod.session_socket_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    seen: Dict[str, Any] = {}
    error: List[BaseException] = []

    def serve():
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5)
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                seen["auth"] = buf
                conn.sendall(b"\0WMUX_FLUSH_DONE:sekrit\0")
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                seen["input"] = buf
        except BaseException as exc:  # pragma: no cover - surfaced below
            error.append(exc)
        finally:
            server.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    mux = WmuxMultiplexer(config)
    mux._client = wmux_mod.WmuxClient()  # token from WMUX_AUTH_TOKEN
    mux._send_to_session(sid, "echo hi")
    t.join(timeout=5)

    assert not error, error
    assert seen.get("auth") == b"sekrit\n"
    assert seen.get("input") == b"echo hi\n"


def test_session_pipe_wrong_token_raises(config, monkeypatch, tmp_path):
    from workstreams.multiplexer import wmux as wmux_mod
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WMUX_DATA_SUFFIX", raising=False)

    sid = "ws-demo-1"
    path = wmux_mod.session_socket_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    def serve():
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5)
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                conn.sendall(b"AUTH_FAILED\n")
                conn.close()
        except OSError:
            pass
        finally:
            server.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    mux = WmuxMultiplexer(config)
    client = wmux_mod.WmuxClient()  # no token anywhere -> sends empty auth line
    client.token = "wrong"
    mux._client = client

    with pytest.raises(RuntimeError, match="rejected the auth token"):
        mux._send_to_session(sid, "echo hi")
    t.join(timeout=5)


def test_compose_line_pure():
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    compose = WmuxMultiplexer._compose_line
    assert compose({"path": "", "command": ""}, "/base", None) == ""
    assert compose({"path": "", "command": "ls"}, "/base", None) == "ls"
    assert compose({"path": "a", "command": ""}, "/base", None) == "cd /base/a"
    assert compose({"path": "a", "command": "ls"}, "/base", None) == "cd /base/a && ls"
    assert compose({"path": "", "command": "ls"}, "/base", "pwd") == "pwd"
    assert compose({"path": "a", "env": {"K": "v"}}, "/base", "ls") == (
        "cd /base/a && K=v ls"
    )
