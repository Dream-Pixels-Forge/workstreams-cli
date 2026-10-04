"""Regression tests for the tmux multiplexer dispatch path.

Issue #2: send_command used to no-op (exit 0, command never delivered) when
the window NAME target failed to resolve. It must fall back to the numeric
window index so dispatches always land.
"""

from __future__ import annotations

import subprocess
from typing import Any, List, Tuple

import pytest


def _mk_config(tmp_path, project="demo", ws_names=("alpha", "beta")):
    from workstreams.models import WorkstreamsConfig, WorkstreamConfig

    ws1 = WorkstreamConfig(id=1, name=ws_names[0], path="a", branch="b", command="")
    ws2 = WorkstreamConfig(id=2, name=ws_names[1], path="b", branch="b", command="")
    return WorkstreamsConfig(
        project=project,
        multiplexer="tmux",
        base_path=str(tmp_path),
        workstreams=[ws1, ws2],
    )


@pytest.fixture
def config(tmp_path):
    return _mk_config(tmp_path)


def _result(rc: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["tmux"], returncode=rc, stdout="", stderr="")


def test_send_command_falls_back_to_numeric_index(config, monkeypatch):
    """Named target fails -> retry `<session>:<id-1>` and still succeed."""
    from workstreams.multiplexer.tmux import TmuxMultiplexer

    mux = TmuxMultiplexer(config)
    calls: List[Tuple[str, ...]] = []

    def fake_tmux(*args, check: bool = False, capture: bool = True):
        calls.append(args)
        if args[0] == "send-keys":
            # Named-window target fails; numeric index target succeeds.
            return _result(0 if args[2] == "workstreams-demo:0" else 1)
        return _result(0)

    monkeypatch.setattr(mux, "_tmux", fake_tmux)
    monkeypatch.setattr(mux, "_session_alive", lambda: True)

    ok = mux.send_command(1, "echo hello")
    assert ok is True

    send_calls = [c for c in calls if c[0] == "send-keys"]
    assert len(send_calls) == 2, "must retry after the named target fails"
    assert send_calls[0][2] == "workstreams-demo:alpha"  # named first
    assert send_calls[1][2] == "workstreams-demo:0"       # numeric fallback


def test_send_command_no_fallback_when_named_target_works(config, monkeypatch):
    from workstreams.multiplexer.tmux import TmuxMultiplexer

    mux = TmuxMultiplexer(config)
    calls: List[Tuple[str, ...]] = []

    def fake_tmux(*args, check: bool = False, capture: bool = True):
        calls.append(args)
        return _result(0)

    monkeypatch.setattr(mux, "_tmux", fake_tmux)
    monkeypatch.setattr(mux, "_session_alive", lambda: True)

    ok = mux.send_command(2, "echo hello")
    assert ok is True
    send_calls = [c for c in calls if c[0] == "send-keys"]
    assert len(send_calls) == 1
    assert send_calls[0][2] == "workstreams-demo:beta"


def test_send_command_fails_when_session_dead(config, monkeypatch, capsys):
    from workstreams.multiplexer.tmux import TmuxMultiplexer

    mux = TmuxMultiplexer(config)
    monkeypatch.setattr(mux, "_session_alive", lambda: False)

    ok = mux.send_command(1, "echo hello")
    assert ok is False
    captured = capsys.readouterr()
    assert "not running" in captured.out


def test_send_command_returns_false_when_both_targets_fail(config, monkeypatch):
    from workstreams.multiplexer.tmux import TmuxMultiplexer

    mux = TmuxMultiplexer(config)

    def fake_tmux(*args, check: bool = False, capture: bool = True):
        if args[0] == "send-keys":
            return _result(1)
        return _result(0)

    monkeypatch.setattr(mux, "_tmux", fake_tmux)
    monkeypatch.setattr(mux, "_session_alive", lambda: True)

    assert mux.send_command(1, "echo hello") is False
