"""Tests for confidence scoring (0-10 self-rated result quality)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workstreams.confidence import (
    clamp_score,
    confidence_records,
    extract_score,
    get_confidence,
)
from workstreams.models import SubagentEvent
from workstreams.event_log import EventLog


def _mk_event(score=None, subagent="claude-code", issue=7, event_type="completed", ws=1):
    data = {}
    if score is not None:
        data["confidence"] = score
    return SubagentEvent(
        workstream_id=ws,
        subagent=subagent,
        issue=issue,
        event_type=event_type,
        message="msg",
        data=data,
    )


# ---------------------------------------------------------------------------
# clamp_score
# ---------------------------------------------------------------------------

def test_clamp_score_none():
    assert clamp_score(None) is None


def test_clamp_score_valid_range():
    assert clamp_score(5) == 5.0
    assert clamp_score("7.5") == 7.5
    assert clamp_score(0) == 0.0
    assert clamp_score(10) == 10.0


def test_clamp_score_clamps_out_of_range():
    assert clamp_score(-3) == 0.0
    assert clamp_score(100) == 10.0


def test_clamp_score_garbage_is_none():
    assert clamp_score("not-a-number") is None
    assert clamp_score([1, 2]) is None


# ---------------------------------------------------------------------------
# extract_score
# ---------------------------------------------------------------------------

def test_extract_score_reads_confidence():
    assert extract_score(_mk_event(score=8)) == 8.0


def test_extract_score_reads_score_key_too():
    e = SubagentEvent(workstream_id=1, subagent="x", issue=1, event_type="completed", message="", data={"score": 6})
    assert extract_score(e) == 6.0


def test_extract_score_missing_returns_none():
    assert extract_score(_mk_event(score=None)) is None


# ---------------------------------------------------------------------------
# get_confidence aggregation
# ---------------------------------------------------------------------------

def test_get_confidence_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(_mk_event(score=5))
    log.append(_mk_event(score=9))

    summary = get_confidence("p", workstream_id=1, issue=7, min_score=8)
    assert summary.passed is True
    assert summary.latest_score == 9.0
    assert summary.n_reports == 2
    assert summary.avg_score == pytest.approx(7.0)


def test_get_confidence_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(_mk_event(score=3))

    summary = get_confidence("p", workstream_id=1, issue=7, min_score=8)
    assert summary.passed is False
    assert summary.latest_score == 3.0


def test_get_confidence_no_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(SubagentEvent(workstream_id=1, subagent="x", issue=7, event_type="started", message="", data={}))

    summary = get_confidence("p", workstream_id=1, issue=7, min_score=8)
    assert summary.n_reports == 0
    assert summary.passed is False
    assert summary.latest_score is None


def test_get_confidence_filters_unscored_events(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(_mk_event(score=None))          # no confidence -> ignored
    log.append(_mk_event(score=10, subagent="codex"))

    summary = get_confidence("p", workstream_id=1, issue=7, min_score=8)
    assert summary.n_reports == 1
    assert summary.latest_subagent == "codex"


def test_get_confidence_issue_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(SubagentEvent(workstream_id=1, subagent="a", issue=1, event_type="completed", message="", data={"confidence": 2}))
    log.append(SubagentEvent(workstream_id=1, subagent="a", issue=2, event_type="completed", message="", data={"confidence": 9}))

    s1 = get_confidence("p", workstream_id=1, issue=1, min_score=8)
    s2 = get_confidence("p", workstream_id=1, issue=2, min_score=8)
    assert s1.latest_score == 2.0 and s1.passed is False
    assert s2.latest_score == 9.0 and s2.passed is True


# ---------------------------------------------------------------------------
# confidence_records
# ---------------------------------------------------------------------------

def test_confidence_records_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(_mk_event(score=1, subagent="a"))
    log.append(_mk_event(score=5, subagent="b"))
    log.append(_mk_event(score=9, subagent="c"))

    records = confidence_records("p", workstream_id=1, issue=7)
    assert [r.subagent for r in records] == ["a", "b", "c"]
    assert [r.score for r in records] == [1.0, 5.0, 9.0]


def test_confidence_records_excludes_unscored(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSTREAMS_DATA_DIR", str(tmp_path))
    from workstreams import event_log
    event_log._log_cache.clear()

    log = EventLog("p", log_dir=tmp_path / "p")
    log.append(_mk_event(score=None, subagent="no-score"))
    log.append(_mk_event(score=7, subagent="scored"))

    records = confidence_records("p", workstream_id=1, issue=7)
    assert [r.subagent for r in records] == ["scored"]
