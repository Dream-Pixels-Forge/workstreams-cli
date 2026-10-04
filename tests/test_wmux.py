"""TDD tests for the native wmux multiplexer (issue #4).

wmux is an Electron GUI terminal multiplexer controlled ONLY via a
newline-delimited JSON-RPC protocol over a Unix socket. The old
tmux-compat shim hung forever; these tests pin the native behavior:
handshake, pane-per-workstream mapping, input.send dispatch, and
fail-fast when the socket is absent.
"""

from __future__ import annotations

import socket
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
        self.handshaken = False

    def call(self, method: str, params: Dict[str, Any] | None = None) -> Any:
        self.calls.append({"method": method, "params": params or {}})
        if method in self.replies:
            r = self.replies[method]
            return r(self.calls) if callable(r) else r
        return {"ok": True}

    def ensure_handshake(self) -> None:
        self.handshaken = True

    @property
    def methods(self) -> List[str]:
        return [c["method"] for c in self.calls]


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
    """No hang: missing ~/.wmux.sock must raise immediately with a clear error."""
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    with pytest.raises(RuntimeError, match="wmux is not running"):
        mux.start([{"id": 1, "name": "alpha"}])


# --------------------------------------------------------------------- #
# Handshake
# --------------------------------------------------------------------- #

def test_handshake_identify_then_declare_permissions(config):
    from workstreams.multiplexer.wmux import WmuxClient

    client = WmuxClient(socket_path="/definitely/not/here.sock")
    seen: List[str] = []
    frames: List[Dict[str, Any]] = []

    def fake_exchange(frame: Dict[str, Any]) -> Dict[str, Any]:
        frames.append(frame)
        seen.append(frame.get("method", ""))
        return {"id": frame["id"], "ok": True, "result": {}}

    client._exchange = fake_exchange  # type: ignore[attr-defined]
    client.ensure_handshake()

    assert seen == ["mcp.identify", "mcp.declarePermissions"]
    # identify params carry name/version
    assert frames[0]["params"]["name"]
    assert frames[0]["params"]["version"]
    # permissions must be an array and must NOT include the reserved cap
    perms = frames[1]["params"]["permissions"]
    assert isinstance(perms, list)
    assert "wmux.internal" not in perms
    for cap in ("workspace.read", "pane.read", "pane.write", "pane.create",
                "terminal.send", "terminal.read", "meta.write"):
        assert cap in perms


def test_approval_prompt_retries_until_granted(config):
    """First capability use may return 'awaiting user approval' -> retry."""
    from workstreams.multiplexer.wmux import WmuxClient

    client = WmuxClient(socket_path="/definitely/not/here.sock")
    attempts = {"n": 0}

    def fake_exchange(frame: Dict[str, Any]) -> Dict[str, Any]:
        if frame.get("method") == "mcp.declarePermissions":
            attempts["n"] += 1
            if attempts["n"] < 3:
                return {
                    "id": frame["id"], "ok": False,
                    "error": "awaiting user approval (promptId=abc)",
                    "rejection": {"status": "awaiting approval", "method": "mcp.declarePermissions"},
                }
        return {"id": frame["id"], "ok": True, "result": {}}

    client._exchange = fake_exchange  # type: ignore[attr-defined]
    client.ensure_handshake()
    assert attempts["n"] == 3  # 2 rejections + 1 success


# --------------------------------------------------------------------- #
# Start: one labeled pane per workstream
# --------------------------------------------------------------------- #

def _pane_list_reply(panes: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"panes": panes}


def test_start_creates_and_labels_one_pane_per_workstream(config, monkeypatch, tmp_path):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    replies: Dict[str, Any] = {}
    state = {"next_pane": 10, "panes": []}

    def pane_split(params):
        state["next_pane"] += 1
        pid = state["next_pane"]
        state["panes"].append({"id": pid, "metadata": {}, "surfacePtyIds": [f"daemon-pty{pid}"]})
        return {"ok": True, "paneId": pid}

    def pane_list(_params):
        return _pane_list_reply(list(state["panes"]))

    replies["pane.split"] = pane_split
    replies["pane.list"] = pane_list
    replies["pane.setMetadata"] = {"ok": True}

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient(replies)
    mux._client = fake

    mux.start([
        {"id": 1, "name": "alpha", "path": "", "command": ""},
        {"id": 2, "name": "beta", "path": "", "command": ""},
    ])

    assert fake.handshaken is True
    assert fake.methods.count("pane.split") == 2
    labels = [c["params"].get("label") for c in fake.calls if c["method"] == "pane.setMetadata"]
    assert labels == ["alpha", "beta"]
    # workstream -> pty map recorded and persisted
    assert mux._pane_map == {1: {"paneId": 11, "ptyId": "daemon-pty11"},
                             2: {"paneId": 12, "ptyId": "daemon-pty12"}}
    # map file exists for cross-process dispatch
    from pathlib import Path
    assert Path(mux._map_path()).exists()

    # fresh instance restores the map
    mux2 = WmuxMultiplexer(config)
    mux2._client = FakeWmuxClient(replies)
    mux2._restore_pane_map()
    assert mux2._pane_map == mux._pane_map


def test_start_reuses_existing_labeled_pane(config, monkeypatch):
    """Idempotent start: a pane already labeled 'alpha' is reused, not split again."""
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    existing = [{"id": 7, "metadata": {"label": "alpha"}, "surfacePtyIds": ["daemon-x7"]}]
    replies = {
        "pane.list": _pane_list_reply(existing),
        "pane.setMetadata": {"ok": True},
    }

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient(replies)
    mux._client = fake

    mux.start([{"id": 1, "name": "alpha", "path": "", "command": ""}])

    assert "pane.split" not in fake.methods
    assert mux._pane_map[1] == {"paneId": 7, "ptyId": "daemon-x7"}


def test_start_runs_workstream_command_via_input_send(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    state = {"n": 0}

    def pane_split(_p):
        state["n"] += 1
        pid = 20 + state["n"]
        return {"ok": True, "paneId": pid}

    def pane_list(_p):
        return _pane_list_reply([
            {"id": 21, "metadata": {"label": "alpha"}, "surfacePtyIds": ["daemon-a"]},
            {"id": 22, "metadata": {"label": "beta"}, "surfacePtyIds": ["daemon-b"]},
        ])

    replies = {"pane.split": pane_split, "pane.list": pane_list,
               "pane.setMetadata": {"ok": True}}

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient(replies)
    mux._client = fake

    mux.start([{"id": 1, "name": "alpha", "path": "", "command": "npm test"}])

    sends = [c for c in fake.calls if c["method"] == "input.send"]
    assert len(sends) == 1
    assert sends[0]["params"]["text"] == "npm test"
    assert sends[0]["params"]["submit"] is True


def test_label_truncated_to_64_chars(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    long_name = "x" * 100
    replies = {
        "pane.split": {"ok": True, "paneId": 5},
        "pane.setMetadata": {"ok": True},
    }
    # First list: empty (forces the split); second: the new pane with its pty.
    lists = [
        {"panes": []},
        {"panes": [{"id": 5, "metadata": {}, "surfacePtyIds": ["daemon-5"]}]},
    ]
    replies["pane.list"] = lambda _p: lists.pop(0) if lists else {"panes": []}
    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient(replies)
    mux._client = fake
    mux.start([{"id": 1, "name": long_name, "path": "", "command": ""}])

    meta = [c for c in fake.calls if c["method"] == "pane.setMetadata"][0]
    assert len(meta["params"]["label"]) <= 64


# --------------------------------------------------------------------- #
# Dispatch / capture
# --------------------------------------------------------------------- #

def test_send_command_targets_recorded_pty(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    fake = FakeWmuxClient({"input.send": {"ok": True, "submitted": True}})
    mux._client = fake
    mux._pane_map = {1: {"paneId": 11, "ptyId": "daemon-pty11"}}

    ok = mux.send_command(1, "echo hello")
    assert ok is True
    sends = [c for c in fake.calls if c["method"] == "input.send"]
    assert sends[0]["params"] == {"ptyId": "daemon-pty11", "text": "echo hello", "submit": True}


def test_send_command_unknown_workstream_fails_loudly(config, capsys):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient()
    mux._pane_map = {}

    ok = mux.send_command(1, "echo hello")
    assert ok is False
    err = capsys.readouterr().err
    assert "start" in err.lower()


def test_capture_reads_screen(config):
    from workstreams.multiplexer.wmux import WmuxMultiplexer

    mux = WmuxMultiplexer(config)
    mux._client = FakeWmuxClient(
        {"input.readScreen": {"ptyId": "p", "text": "l0\nl1\nl2\nl3\n"}}
    )
    mux._pane_map = {1: {"paneId": 11, "ptyId": "p"}}

    lines = mux.capture(1, lines=2)
    assert lines == ["l2", "l3"]


# --------------------------------------------------------------------- #
# Client wire format + timeouts
# --------------------------------------------------------------------- #

def test_request_frame_shape_and_timeout_on_socket(config, monkeypatch):
    """Every socket call must set a timeout; frame carries id/method/token."""
    from workstreams.multiplexer import wmux as wmux_mod

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
    client.handshaken = True  # skip handshake for this unit
    client.call("workspace.list", {})

    assert set_timeouts and all(t == 3.5 for t in set_timeouts)
    frame = __import__("json").loads(sent[0].decode().strip())
    assert frame["method"] == "workspace.list"
    assert frame["params"] == {}
    assert frame["id"]
    assert frame["token"] is None or isinstance(frame["token"], str)
    assert frame["clientName"] == "workstreams"
    assert frame["clientVersion"]


def test_socket_absent_raises_not_running(config):
    from workstreams.multiplexer.wmux import WmuxClient

    client = WmuxClient(socket_path="/no/such/wmux.sock")
    with pytest.raises(RuntimeError, match="wmux is not running"):
        client.call("workspace.list", {})


def test_default_socket_path_env_override(monkeypatch, tmp_path):
    from workstreams.multiplexer.wmux import default_socket_path

    monkeypatch.setenv("WMUX_SOCKET_PATH", str(tmp_path / "custom.sock"))
    assert default_socket_path() == str(tmp_path / "custom.sock")
    monkeypatch.delenv("WMUX_SOCKET_PATH")
    monkeypatch.setenv("WMUX_DATA_SUFFIX", "-test")
    assert default_socket_path().endswith(".wmux-test.sock")


def test_token_read_from_file(config, tmp_path, monkeypatch):
    from workstreams.multiplexer.wmux import WmuxClient

    tokfile = tmp_path / ".wmux-auth-token"
    tokfile.write_text("s3cret\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WMUX_AUTH_TOKEN", raising=False)

    client = WmuxClient(socket_path="/no/such.sock")
    assert client.token == "s3cret"
