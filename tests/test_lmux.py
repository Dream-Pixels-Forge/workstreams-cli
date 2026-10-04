"""Tests for the native lmux multiplexer (LmuxMultiplexer).

The client is stubbed so we test the workstream->surface mapping logic and
the wire calls without needing the real daemon. The one end-to-end test
against the real daemon is marked and skipped unless LMUX_E2E=1.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import pytest


def _mk_config(tmp_path, project="demo", ws_names=("alpha", "beta")):
    """Build a minimal config object that LmuxMultiplexer expects."""
    from workstreams.models import WorkstreamsConfig, WorkstreamConfig

    ws1 = WorkstreamConfig(id=1, name="alpha", path="a", branch="b", command="")
    ws2 = WorkstreamConfig(id=2, name="beta", path="b", branch="b", command="")
    return WorkstreamsConfig(
        project=project,
        multiplexer="lmux",
        base_path=str(tmp_path),
        workstreams=[ws1, ws2],
    )


@pytest.fixture
def config(tmp_path):
    return _mk_config(tmp_path)


def test_start_creates_workspace_and_surfaces(config, monkeypatch):
    from workstreams.multiplexer.lmux import LmuxMultiplexer

    calls: List[Dict[str, Any]] = []
    seq: Dict[str, int] = {}

    def fake_cmd(name, args, **_):
        calls.append({"cmd": name, "args": args})
        if name == "workspace.create":
            return {"ok": True, "result": {"id": 100}}
        if name == "surface.create":
            seq["surface"] = seq.get("surface", 0) + 1
            return {"ok": True, "result": {"id": 500 + seq["surface"]}}
        if name == "workspace.list":
            return {"ok": True, "result": {"workspaces": []}}
        return {"ok": True, "result": {}}

    mux = LmuxMultiplexer(config)
    mux._client = type("C", (), {"cmd": staticmethod(fake_cmd)})()

    mux.start([
        {"id": 1, "name": "alpha"},
        {"id": 2, "name": "beta"},
    ])

    # One workspace, two surfaces.
    cmds = [c["cmd"] for c in calls]
    assert cmds.count("workspace.create") == 1
    assert cmds.count("surface.create") == 2
    # Surface ids are recorded for later targeting.
    assert mux._surface_map == {1: 501, 2: 502}
    assert mux._workspace_id == 100


def test_send_command_targets_recorded_surface(config, monkeypatch):
    from workstreams.multiplexer.lmux import LmuxMultiplexer

    sent = []

    mux = LmuxMultiplexer(config)
    mux._workspace_id = 100
    mux._surface_map = {1: 501, 2: 502}
    mux._client = type("C", (), {
        "cmd": staticmethod(lambda name, args, **_: sent.append((name, args)) or {"ok": True, "result": {}})
    })()

    ok = mux.send_command(1, "echo hello")
    assert ok is True
    # The text payload must be prefixed with a cd into the workstream path.
    name, args = sent[0]
    assert name == "surface.send_text"
    assert args["surface"] == 501
    assert "echo hello" in args["text"]


def test_capture_reads_screen_of_surface(config, monkeypatch):
    from workstreams.multiplexer.lmux import LmuxMultiplexer

    pane_text = "line0\nline1\nline2\nline3\n"
    mux = LmuxMultiplexer(config)
    mux._surface_map = {1: 501}
    mux._client = type("C", (), {
        "cmd": staticmethod(lambda name, args, **_: {"ok": True, "result": {"text": pane_text}})
    })()

    lines = mux._capture_surface(1, lines=2)
    assert lines == ["line2", "line3"]


def test_lmux_registers_and_dialect_detect(monkeypatch):
    from workstreams import multiplexer as mp

    # The dialect probe in __init__.py imports `subprocess as _sp` inside the
    # function, so we patch `subprocess.run` at the source module level.
    import subprocess as sp

    orig_run = sp.run

    def fake_run(cmd, *a, **k):
        if "help" in cmd:
            return sp.CompletedProcess(
                cmd, 0,
                stdout="lmux\nworkspace.create <title>\nsurface.send_text <text>\n",
                stderr="",
            )
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr(mp.shutil, "which", lambda b: "/usr/bin/" + b)
    # Clear both dialect caches.
    mp._tmux_dialect_cache.clear()
    if hasattr(mp, "_lmux_dialect_cache"):
        mp._lmux_dialect_cache.clear()
    # lmux native dialect must now be detected.
    assert mp._installed("lmux") is True


def test_lmux_e2e_real_daemon(config):
    """End-to-end against the live lmux daemon (opt-in via LMUX_E2E=1)."""
    if not os.environ.get("LMUX_E2E"):
        pytest.skip("set LMUX_E2E=1 to run real lmux e2e")
    from workstreams.multiplexer.lmux import LmuxMultiplexer

    mux = LmuxMultiplexer(config)
    mux.start([{"id": 1, "name": "alpha", "path": "a"}], command="echo MARKER_12345")
    # read-screen must actually contain the marker — genuine proof.
    captured = mux.capture(1, lines=20)
    joined = "\n".join(captured)
    assert "MARKER_12345" in joined, f"marker not found in pane:\n{joined}"
