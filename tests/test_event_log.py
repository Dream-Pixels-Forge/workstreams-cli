"""Tests for the event log and subagent client modules."""

import sys
sys.path.insert(0, "src")

import os
import time
from datetime import datetime, UTC

import pytest

from workstreams.models import SubagentEvent
from workstreams.event_log import EventLog, default_log_dir


def _make_event(ws_id=1, subagent="claude-code", event_type="progress", issue=42, message="msg"):
    return SubagentEvent(
        workstream_id=ws_id,
        subagent=subagent,
        issue=issue,
        event_type=event_type,
        message=message,
    )


def test_event_log_append_and_read(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    assert log.append(_make_event(message="first")) is True
    assert log.append(_make_event(message="second")) is True

    events = log.get_events()
    assert len(events) == 2
    assert events[0].message == "first"
    assert events[1].message == "second"
    assert events[0].subagent == "claude-code"


def test_event_log_filter_by_workstream(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    log.append(_make_event(ws_id=1, message="ws1"))
    log.append(_make_event(ws_id=2, message="ws2"))
    log.append(_make_event(ws_id=1, message="ws1b"))

    assert len(log.get_events(workstream_id=1)) == 2
    assert len(log.get_events(workstream_id=2)) == 1
    assert log.get_events(workstream_id=1)[0].message == "ws1"
    assert log.get_events(workstream_id=1)[1].message == "ws1b"


def test_event_log_filter_by_type(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    log.append(_make_event(event_type="started"))
    log.append(_make_event(event_type="completed"))
    log.append(_make_event(event_type="error"))

    assert len(log.get_events(event_type="started")) == 1
    assert len(log.get_events(event_type="completed")) == 1
    assert len(log.get_events(event_type="error")) == 1
    assert log.get_events(event_type="started")[0].event_type == "started"


def test_event_log_filter_by_subagent(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    log.append(_make_event(subagent="claude-code"))
    log.append(_make_event(subagent="codex"))
    log.append(_make_event(subagent="claude-code"))

    assert len(log.get_events(subagent="claude-code")) == 2
    assert len(log.get_events(subagent="codex")) == 1


def test_event_log_limit(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    for i in range(10):
        log.append(_make_event(message=f"msg-{i}"))

    last3 = log.get_events(limit=3)
    assert len(last3) == 3
    assert last3[0].message == "msg-7"
    assert last3[2].message == "msg-9"


def test_event_log_since(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    log.append(_make_event(message="old"))
    time.sleep(0.02)
    cutoff = datetime.now(UTC)
    time.sleep(0.02)
    log.append(_make_event(message="new"))

    recent = log.get_events(since=cutoff)
    assert all(e.message == "new" for e in recent)
    assert len(recent) == 1


def test_event_log_tail(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    for i in range(20):
        log.append(_make_event(message=f"msg-{i}"))

    tail = log.tail(5)
    assert len(tail) == 5
    assert tail[0].message == "msg-15"
    assert tail[4].message == "msg-19"


def test_event_log_stats(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    log.append(_make_event(event_type="started"))
    log.append(_make_event(event_type="progress"))
    log.append(_make_event(event_type="progress"))
    log.append(_make_event(event_type="completed"))

    stats = log.stats()
    assert stats["total"] == 4
    assert stats["by_type"]["started"] == 1
    assert stats["by_type"]["progress"] == 2
    assert stats["by_type"]["completed"] == 1


def test_event_log_clear(tmp_path):
    log = EventLog("proj", log_dir=tmp_path / "proj")
    log.append(_make_event(message="before"))
    log.clear()
    assert log.get_events() == []


def test_event_log_default_dir_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path / "data"))
    result = default_log_dir("myproj")
    assert result == tmp_path / "data" / "myproj"


def test_subagent_event_serialization():
    e = SubagentEvent(
        workstream_id=3,
        subagent="hermes",
        issue=10,
        event_type="failed",
        message="boom",
        data={"file": "main.py"},
    )
    d = e.to_dict()
    assert d["workstream_id"] == 3
    assert d["subagent"] == "hermes"
    assert d["event_type"] == "failed"
    assert d["data"] == {"file": "main.py"}

    restored = SubagentEvent.from_dict(d)
    assert restored.workstream_id == 3
    assert restored.subagent == "hermes"
    assert restored.issue == 10
    assert restored.data == {"file": "main.py"}


def test_subagent_event_from_dict_missing_keys():
    e = SubagentEvent.from_dict({"workstream_id": 1, "subagent": "claude-code"})
    assert e.workstream_id == 1
    assert e.subagent == "claude-code"
    assert e.issue == 0
    assert e.event_type == "progress"
    assert e.message == ""
    assert e.data == {}


def test_subagent_event_from_dict_ignores_unknown_keys():
    e = SubagentEvent.from_dict({
        "workstream_id": 1,
        "subagent": "x",
        "issue": 1,
        "event_type": "started",
        "message": "hi",
        "weird_field": "ignored",
    })
    assert e.message == "hi"
    assert not hasattr(e, "weird_field")


def test_event_log_rotation(tmp_path):
    """When events.jsonl exceeds max_bytes, it rotates to events-<ts>.jsonl."""
    from workstreams.event_log import EventLog, _rotate_file
    from workstreams.models import SubagentEvent

    log_dir = tmp_path / "proj"
    log = EventLog("proj", log_dir=log_dir, max_bytes=100, max_files=50)

    # Append enough events to exceed 100 bytes
    for i in range(20):
        e = SubagentEvent(
            workstream_id=1,
            subagent="test",
            issue=0,
            event_type="progress",
            message=f"event number {i} with some padding text to grow the log file",
        )
        assert log.append(e) is True

    # At least one rotated file should exist
    rotated = log.rotated_files()
    assert len(rotated) >= 1, "expected at least one rotated file"
    for rf in rotated:
        assert rf.exists()
        assert rf.name.startswith("events-")
        assert rf.name.endswith(".jsonl")

    # With max_files=50, no pruning yet -> total across all files == 20
    total = 0
    for fpath in [log.events_file] + list(rotated):
        if fpath.exists():
            with open(fpath, "r", encoding="utf-8") as f:
                total += sum(1 for line in f if line.strip())
    assert total == 20, f"expected 20 total events across files, got {total}"

    # clear removes all
    log.clear()
    assert log.get_events() == []
    assert log.rotated_files() == []


def test_event_log_max_files_pruning(tmp_path):
    """Rotated files are pruned to max_files (oldest removed first)."""
    from workstreams.event_log import EventLog, _rotate_file
    from workstreams.models import SubagentEvent
    import os, time

    log_dir = tmp_path / "proj"
    log_dir.mkdir()
    log = EventLog("proj", log_dir=log_dir, max_bytes=50, max_files=3)

    # Create the current events.jsonl with content exceeding max_bytes
    # so _rotate_file actually triggers
    with open(log.events_file, "w") as f:
        for i in range(20):
            f.write('{"workstream_id":1,"subagent":"x","issue":0,"event_type":"progress","message":"' + str(i) + '","timestamp":"2026-01-01T00:00:00","data":{}}\n')

    # Manually create 5 fake rotated files with staggered mtimes
    for i in range(5):
        fake = log_dir / f"events-20260101{i:06d}.jsonl"
        fake.write_text("{}\n")
        os.utime(fake, (time.time() + i, time.time() + i))

    rotated = log.rotated_files()
    assert len(rotated) == 5

    # Trigger rotation + pruning
    _rotate_file(log.events_file, 50, 3)
    # After pruning, keep newest 3 rotated files
    rotated_after = log.rotated_files()
    assert len(rotated_after) == 3
