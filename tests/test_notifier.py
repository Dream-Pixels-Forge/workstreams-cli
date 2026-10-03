"""Tests for the notifier and subagent_client modules."""

import sys
sys.path.insert(0, "src")

import json
from datetime import datetime, UTC

import pytest

from workstreams.notifier import Notifier
from workstreams.event_log import EventLog
from workstreams.subagent_client import (
    subagent_started,
    subagent_progress,
    subagent_completed,
    subagent_failed,
    subagent_report,
)


def test_notifier_send_and_get(tmp_path):
    n = Notifier("proj", log_dir=tmp_path)
    assert n.send("title1", "message1") is True
    assert n.send("title2", "message2", "critical") is True

    notifs = n.get_notifications()
    assert len(notifs) == 2
    assert notifs[0]["title"] == "title1"
    assert notifs[0]["message"] == "message1"
    assert notifs[0]["urgency"] == "normal"
    assert notifs[1]["urgency"] == "critical"


def test_notifier_since_filter(tmp_path):
    n = Notifier("proj", log_dir=tmp_path)
    n.send("old", "old-msg")
    import time
    time.sleep(0.02)
    cutoff = datetime.now(UTC)
    time.sleep(0.02)
    n.send("new", "new-msg")

    recent = n.get_notifications(since=cutoff)
    assert all(x["title"] == "new" for x in recent)
    assert len(recent) == 1


def test_notifier_clear(tmp_path):
    n = Notifier("proj", log_dir=tmp_path)
    n.send("a", "b")
    n.clear_notifications()
    assert n.get_notifications() == []


def test_notifier_empty_returns_list(tmp_path):
    n = Notifier("proj", log_dir=tmp_path)
    assert n.get_notifications() == []


def test_subagent_client_functions(tmp_path, monkeypatch):
    """subagent_* helpers write to the EventLog and return True on success."""
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))

    assert subagent_started("proj", 1, "claude-code", 42, "start task") is True
    assert subagent_progress("proj", 1, "claude-code", 42, "50% done") is True
    assert subagent_completed("proj", 1, "claude-code", 42, "done") is True
    assert subagent_failed("proj", 1, "claude-code", 42, "failed") is True

    from workstreams.event_log import EventLog
    log = EventLog("proj", log_dir=tmp_path / "proj")
    events = log.get_events()
    assert len(events) == 4
    assert events[0].event_type == "started"
    assert events[1].event_type == "progress"
    assert events[2].event_type == "completed"
    assert events[3].event_type == "failed"
    assert all(e.subagent == "claude-code" for e in events)
    assert all(e.issue == 42 for e in events)


def test_subagent_report_generic(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    # Clear cache so the new env var takes effect
    from workstreams import event_log
    event_log._log_cache.clear()

    assert subagent_report("proj", 2, "codex", 7, "error", "boom", {"retry": 3}) is True

    log = EventLog("proj", log_dir=tmp_path / "proj")
    events = log.get_events(workstream_id=2, subagent="codex")
    assert len(events) == 1
    assert events[0].event_type == "error"
    assert events[0].message == "boom"
    assert events[0].data == {"retry": 3}


def test_linux_notify_autodismiss(tmp_path, monkeypatch):
    """Linux notify-send must use --transient + --expire-time and must not
    use critical urgency (which pins the notification open)."""
    import platform as _platform
    from unittest.mock import patch, MagicMock

    # Force the Linux branch regardless of host
    monkeypatch.setattr(_platform, "system", lambda: "Linux")
    log_dir = tmp_path / "proj"
    n = Notifier("proj", log_dir=log_dir)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    with patch("workstreams.notifier.subprocess.run", side_effect=fake_run):
        n.send("Test", "body", urgency="critical")

    cmd = captured["cmd"]
    # Must request auto-dismiss
    assert "--transient" in cmd
    assert "--expire-time" in cmd
    # Critical must be downgraded to normal so it doesn't stay pinned
    assert "critical" not in cmd
    assert cmd.count("normal") >= 1
    # Critical urgency gets a longer (but still finite) expiry
    assert cmd[cmd.index("--expire-time") + 1] == "15000"
