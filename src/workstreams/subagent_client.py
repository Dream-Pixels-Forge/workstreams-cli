"""Subagent client helpers - report events from any process.

Import these from your subagent (a Claude Code session, a Codex session,
a script, a cron job...) so it can report progress to the main terminal:

    from workstreams import subagent_progress
    subagent_progress("myproject", 1, "claude-code", 42, "Fixed auth", {"files": 3})

Or use the one-liner CLI that needs no Python import at all:

    workstreams event started --project myproject --workstream 1 \
        --subagent claude-code --issue 42 --message "Fix auth"

All events land in ~/.workstreams/<project>/events.jsonl and show up in
`workstreams monitor`, `workstreams events`, and any other terminal.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import SubagentEvent
from .event_log import get_event_log

# Subagent identifiers are free-form (claude-code, codex, opencode, qwen-code,
# mimocode, hermes, kilo-code, cline, ...). We do NOT restrict them: the whole
# point of workstreams is agent-agnostic dispatch.


def subagent_report(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    event_type: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report an arbitrary event (cross-process)."""
    event_log = get_event_log(project)
    event = SubagentEvent(
        workstream_id=workstream_id,
        subagent=subagent,
        issue=issue,
        event_type=event_type,
        message=message,
        data=data or {},
    )
    return event_log.append(event)


def subagent_started(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    prompt: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report subagent started."""
    return subagent_report(
        project, workstream_id, subagent, issue, "started",
        f"{subagent} started on issue #{issue}" + (f": {prompt}" if prompt else ""),
        {"prompt": prompt, **(data or {})},
    )


def subagent_progress(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report subagent progress."""
    return subagent_report(project, workstream_id, subagent, issue, "progress", message, data)


def subagent_completed(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report subagent completed."""
    return subagent_report(project, workstream_id, subagent, issue, "completed", message, data)


def subagent_failed(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report subagent failed."""
    return subagent_report(project, workstream_id, subagent, issue, "failed", message, data)


def subagent_error(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report a subagent error."""
    return subagent_report(project, workstream_id, subagent, issue, "error", message, data)


def subagent_done(
    project: str,
    workstream_id: int,
    subagent: str,
    issue: int,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Report a subagent finished (used by workstreams work --wait)."""
    return subagent_report(project, workstream_id, subagent, issue, "done", message, data)
