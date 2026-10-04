"""Tests for the shared dispatch core and the dashboard.py web console API."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from workstreams.dispatch import build_pane_command, dispatch_workstream
from workstreams.dashboard import WebDashboard, resolve_web_root
from workstreams.models import WorkstreamConfig, WorkstreamsConfig
from workstreams.manager import WorkstreamsManager
from workstreams.cli import build_parser, HANDLERS


# -- build_pane_command precedence -----------------------------------------


def test_prompt_wins_over_issue_template():
    resolved, pane = build_pane_command("claude-code", issue=7, prompt="custom")
    assert resolved == "custom"
    assert pane == "custom"


def test_prompt_used_when_issue_zero():
    resolved, pane = build_pane_command("claude-code", issue=0, prompt="do it")
    assert pane == "do it"


def test_issue_template_without_prompt():
    resolved, pane = build_pane_command("codex", issue=7)
    assert pane == "Work on issue #7 as codex"


def test_subagent_fallback():
    _, pane = build_pane_command("codex")
    assert pane == "as codex"


def test_agent_prefix():
    resolved, pane = build_pane_command("codex", prompt="do it", agent="opencode run")
    assert resolved == "do it"
    assert pane == "opencode run do it"


# -- dispatch_workstream -----------------------------------------------------


class _StubMux:
    def __init__(self):
        self.sent: list = []

    def send_command(self, workstream_id, cmd):
        self.sent.append((workstream_id, cmd))
        return True

    def pane_target(self, ws_id):
        return f"0:{ws_id}"

    def is_running(self):
        return True


def _mk_manager(tmp_path):
    config = WorkstreamsConfig(
        project="webtest",
        multiplexer="tmux",
        base_path=str(tmp_path),
        workstreams=[
            WorkstreamConfig(
                id=1, name="ws1", path="worktrees/ws1", branch="ws/1", command=""
            )
        ],
    )
    return WorkstreamsManager(config)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path / "wsdata"))
    monkeypatch.setattr(
        "workstreams.notifier.Notifier.send", lambda self, *a, **k: True
    )
    mgr = _mk_manager(tmp_path)
    events = []
    monkeypatch.setattr(
        "workstreams.subagent_client.subagent_started",
        lambda *a, **k: events.append(a),
    )
    mgr._started = events
    mgr._mux = _StubMux()
    return mgr


def test_dispatch_unknown_workstream(manager):
    result = dispatch_workstream(manager, 99, "codex")
    assert result.code == 5
    assert "not found" in result.message
    assert manager._mux.sent == []


def test_dispatch_success_records_everything(manager, tmp_path):
    result = dispatch_workstream(manager, 1, "claude-code", prompt="do the thing")
    assert result.code == 0
    assert result.warnings == []
    assert manager._mux.sent == [(1, "do the thing")]
    # subagent_started(project, ws, subagent, issue, prompt)
    assert manager._started == [("webtest", 1, "claude-code", 0, "do the thing")]
    log = tmp_path / "worktrees" / "ws1" / "logs" / "worker.log"
    assert log.exists()
    assert "DISPATCH [claude-code] do the thing" in log.read_text()


def test_dispatch_mux_exception_becomes_warning(manager):
    def boom(workstream_id, cmd):
        raise OSError("mux gone")

    manager._mux.send_command = boom
    result = dispatch_workstream(manager, 1, "codex", prompt="x")
    assert result.code == 0
    assert any("pane send failed" in w for w in result.warnings)


def test_dispatch_wait_returns_wait_code(manager):
    manager._wait_for_done = lambda ws, sub: 1
    result = dispatch_workstream(manager, 1, "codex", prompt="x", wait=True)
    assert result.code == 1


def test_dispatch_without_multiplexer(manager):
    manager._mux = None
    manager._get_multiplexer = lambda: None
    result = dispatch_workstream(manager, 1, "codex", prompt="x")
    assert result.code == 0
    assert result.warnings == []


# -- HTTP server -------------------------------------------------------------


@pytest.fixture
def web_server(manager):
    wd = WebDashboard(manager, host="127.0.0.1", port=0)
    httpd = wd.make_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield wd, port
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def test_api_config(web_server):
    _, port = web_server
    status, data = _request(port, "GET", "/api/config")
    assert status == 200
    cfg = json.loads(data)
    assert cfg["project"] == "webtest"
    assert cfg["workstreams"][0]["name"] == "ws1"


def test_api_status(web_server):
    _, port = web_server
    status, data = _request(port, "GET", "/api/status")
    assert status == 200
    payload = json.loads(data)
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["active"] == 1  # mux stub reports running
    assert payload["statuses"][0]["id"] == 1
    assert payload["statuses"][0]["pane"] == "0:1"
    assert isinstance(payload["events"], list)
    assert payload["generated_at"]


def test_api_events(web_server):
    _, port = web_server
    status, data = _request(port, "GET", "/api/events")
    assert status == 200
    assert json.loads(data) == {"events": []}


def test_api_dispatch_success(web_server, manager):
    _, port = web_server
    status, data = _request(
        port,
        "POST",
        "/api/dispatch",
        {"workstream": 1, "subagent": "claude-code", "prompt": "web prompt"},
    )
    assert status == 200
    payload = json.loads(data)
    assert payload == {
        "ok": True,
        "code": 0,
        "message": "Dispatched claude-code -> workstream ws1",
        "warnings": [],
    }
    # Same precedence rule as the CLI: prompt wins over issue template
    assert manager._mux.sent == [(1, "web prompt")]


def test_api_dispatch_issue_template(web_server, manager):
    _, port = web_server
    status, data = _request(
        port,
        "POST",
        "/api/dispatch",
        {"workstream": 1, "subagent": "codex", "issue": 42},
    )
    assert status == 200
    assert manager._mux.sent[-1] == (1, "Work on issue #42 as codex")


def test_api_dispatch_unknown_workstream(web_server):
    _, port = web_server
    status, data = _request(
        port, "POST", "/api/dispatch", {"workstream": 99, "subagent": "codex"}
    )
    assert status == 404
    payload = json.loads(data)
    assert payload["code"] == 5
    assert "not found" in payload["message"]


def test_api_dispatch_missing_fields(web_server):
    _, port = web_server
    status, data = _request(port, "POST", "/api/dispatch", {})
    assert status == 400
    assert json.loads(data)["code"] == 2

    status, _ = _request(port, "POST", "/api/dispatch", {"workstream": 1})
    assert status == 400


def test_api_dispatch_invalid_json(web_server):
    _, port = web_server
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(
            "POST",
            "/api/dispatch",
            body=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 400
        resp.read()
    finally:
        conn.close()


def test_unknown_api_route(web_server):
    _, port = web_server
    status, _ = _request(port, "GET", "/api/nope")
    assert status == 404
    status, _ = _request(port, "POST", "/api/nope", {})
    assert status == 404


def test_static_index_served(web_server):
    _, port = web_server
    status, data = _request(port, "GET", "/")
    assert status == 200
    assert b"Workstreams Web Console" in data


def test_static_screen_served(web_server):
    _, port = web_server
    status, data = _request(port, "GET", "/screens/monitor.html")
    assert status == 200
    assert b"monitor-screen" in data


def test_static_missing_file_404(web_server):
    _, port = web_server
    status, _ = _request(port, "GET", "/screens/does-not-exist.html")
    assert status == 404


def test_static_traversal_blocked(web_server):
    _, port = web_server
    status, data = _request(port, "GET", "/../pyproject.toml")
    assert status in (403, 404)
    assert b"[project]" not in data


def test_resolve_web_root_finds_repo_console():
    root = resolve_web_root()
    assert root is not None
    assert (root / "index.html").is_file()
    assert (root / "app.js").is_file()


# -- CLI wiring --------------------------------------------------------------


def test_web_command_registered():
    assert "web" in HANDLERS
    parser = build_parser()
    args = parser.parse_args(["web", "--port", "0", "--host", "0.0.0.0"])
    assert args.command == "web"
    assert args.port == 0
    assert args.host == "0.0.0.0"
    assert args.open is False
