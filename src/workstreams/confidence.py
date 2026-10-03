"""Confidence scoring — let subagents self-rate result quality.

A subagent can attach a confidence score (0-10) to any event, signalling
how sure it is that the delivered result meets the required bar. The main
agent (or a CI gate) can then query the latest / aggregate confidence and
decide whether to accept, re-dispatch, or escalate.

    # subagent reports a high-confidence completion
    workstreams event completed --project p --workstream 1 --subagent claude-code \
        --issue 42 --message "All tests green" --confidence 9

    # main agent / CI gate: pass only if latest confidence >= 8
    workstreams confidence --project p --workstream 1 --issue 42 --min-score 8
    # exit 0 -> gate passed, exit 1 -> below threshold

Scores are read straight from the event log's `data.confidence` field, so
no new storage is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .event_log import get_event_log
from .models import SubagentEvent

# Confidence scale is 0-10. Anything at/above this is treated as a
# "high confidence" result by default.
DEFAULT_MIN_SCORE = 8


def clamp_score(value: Any) -> Optional[float]:
    """Normalise a confidence value to a float in [0, 10], or None.

    Accepts ints, floats, and numeric strings. Values are clamped to
    [0, 10] so a misbehaving subagent can't emit e.g. 100.
    """
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0:
        return 0.0
    if score > 10:
        return 10.0
    return score


@dataclass
class ConfidenceRecord:
    """One confidence-bearing event, normalised for display."""

    workstream_id: int
    subagent: str
    issue: int
    event_type: str
    score: Optional[float]
    message: str
    timestamp: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConfidenceSummary:
    """Aggregated confidence view for a workstream (optionally per issue)."""

    workstream_id: int
    latest_score: Optional[float]
    latest_event_type: str
    latest_subagent: str
    latest_message: str
    avg_score: Optional[float]
    n_reports: int
    passed: bool
    min_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_score(event: SubagentEvent) -> Optional[float]:
    """Pull a confidence score out of an event (data.confidence preferred)."""
    score = event.data.get("confidence")
    if score is None:
        # also accept top-level 'score' in data for convenience
        score = event.data.get("score")
    return clamp_score(score)


def get_confidence(
    project: str,
    workstream_id: Optional[int] = None,
    issue: Optional[int] = None,
    subagent: Optional[str] = None,
    since_minutes: int = 60 * 24 * 30,  # 30 days
    min_score: float = DEFAULT_MIN_SCORE,
) -> ConfidenceSummary:
    """Aggregate confidence for a workstream (and optional issue/subagent).

    Only events that carry a confidence score are counted. `passed` is True
    when the *latest* score is at or above `min_score` and at least one
    scored report exists.
    """
    from datetime import datetime, UTC, timedelta

    event_log = get_event_log(project)
    since = datetime.now(UTC) - timedelta(minutes=since_minutes)

    events = event_log.get_events(
        workstream_id=workstream_id,
        since=since,
        subagent=subagent,
    )
    if issue is not None:
        events = [e for e in events if e.issue == issue]

    scored = [e for e in events if extract_score(e) is not None]

    latest_score: Optional[float] = None
    latest_event_type = ""
    latest_subagent = ""
    latest_message = ""
    total = 0.0
    n = 0

    for e in scored:
        s = extract_score(e)
        total += s or 0.0
        n += 1
        # events are oldest->newest, so the last scored event is the latest
        latest_score = s
        latest_event_type = e.event_type
        latest_subagent = e.subagent
        latest_message = e.message

    avg_score = (total / n) if n else None
    passed = (
        latest_score is not None
        and latest_score >= min_score
    )

    return ConfidenceSummary(
        workstream_id=workstream_id or 0,
        latest_score=latest_score,
        latest_event_type=latest_event_type,
        latest_subagent=latest_subagent,
        latest_message=latest_message,
        avg_score=avg_score,
        n_reports=n,
        passed=passed,
        min_score=min_score,
    )


def confidence_records(
    project: str,
    workstream_id: Optional[int] = None,
    issue: Optional[int] = None,
    subagent: Optional[str] = None,
    since_minutes: int = 60 * 24 * 30,
) -> List[ConfidenceRecord]:
    """Return all confidence-bearing events, oldest first."""
    from datetime import datetime, UTC, timedelta

    event_log = get_event_log(project)
    since = datetime.now(UTC) - timedelta(minutes=since_minutes)
    events = event_log.get_events(
        workstream_id=workstream_id, since=since, subagent=subagent
    )
    if issue is not None:
        events = [e for e in events if e.issue == issue]

    out: List[ConfidenceRecord] = []
    for e in events:
        s = extract_score(e)
        if s is None:
            continue
        out.append(
            ConfidenceRecord(
                workstream_id=e.workstream_id,
                subagent=e.subagent,
                issue=e.issue,
                event_type=e.event_type,
                score=s,
                message=e.message,
                timestamp=e.timestamp,
                data=e.data,
            )
        )
    return out
