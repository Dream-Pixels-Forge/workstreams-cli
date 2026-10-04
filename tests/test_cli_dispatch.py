"""Regression tests for the dispatch prompt precedence bug (cli.py).

``prompt = args.prompt or X if args.issue else Y`` parsed as
``(args.prompt or X) if args.issue else Y``, so ``--prompt`` was silently
dropped whenever ``--issue`` was 0/omitted and the pane received
``as <subagent>`` instead.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest


class _FakeWorkstream:
    id = 1
    name = "ws1"


class _FakeConfig:
    project = "demo"

    def workstream(self, ws_id):
        return _FakeWorkstream() if ws_id == 1 else None


class _FakeManager:
    def __init__(self):
        self.config = _FakeConfig()
        self.notifier = SimpleNamespace(send=lambda *a, **k: None)
        self.sent: list = []
        self.logs: list = []

    def _get_multiplexer(self):
        return SimpleNamespace(
            send_command=lambda wid, cmd: self.sent.append((wid, cmd))
        )

    def _append_workstream_log(self, ws, msg):
        self.logs.append(msg)


@pytest.fixture
def fake_manager(monkeypatch):
    import workstreams.cli as cli
    import workstreams.subagent_client as sc

    mgr = _FakeManager()
    monkeypatch.setattr(cli, "_load_manager", lambda args: mgr)
    monkeypatch.setattr(sc, "subagent_started", lambda *a, **k: None)
    monkeypatch.setattr(sc, "subagent_report", lambda *a, **k: None)
    return mgr


def _args(**kw):
    base = dict(
        command="dispatch",
        config=None,
        multiplexer=None,
        workstream=1,
        subagent="claude-code",
        issue=0,
        prompt=None,
        agent=None,
        wait=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_prompt_is_sent_when_issue_is_zero(fake_manager):
    import workstreams.cli as cli

    rc = cli._cmd_dispatch(_args(prompt="do the thing"))
    assert rc == 0
    assert fake_manager.sent == [(1, "do the thing")]


def test_prompt_wins_over_issue_template(fake_manager):
    import workstreams.cli as cli

    rc = cli._cmd_dispatch(_args(prompt="custom", issue=7))
    assert rc == 0
    assert fake_manager.sent == [(1, "custom")]


def test_issue_template_used_without_prompt(fake_manager):
    import workstreams.cli as cli

    rc = cli._cmd_dispatch(_args(issue=7))
    assert rc == 0
    assert fake_manager.sent == [(1, "Work on issue #7 as claude-code")]


def test_subagent_fallback_without_prompt_or_issue(fake_manager):
    import workstreams.cli as cli

    rc = cli._cmd_dispatch(_args())
    assert rc == 0
    assert fake_manager.sent == [(1, "as claude-code")]


def test_agent_prefix_keeps_prompt(fake_manager):
    import workstreams.cli as cli

    rc = cli._cmd_dispatch(_args(prompt="do the thing", agent="codex"))
    assert rc == 0
    assert fake_manager.sent == [(1, "codex do the thing")]


def test_unknown_workstream_fails(fake_manager, capsys):
    import workstreams.cli as cli

    rc = cli._cmd_dispatch(_args(workstream=99))
    assert rc == 5
    assert "not found" in capsys.readouterr().err
