"""Shared dispatch core used by both the CLI and the web console.

Single source of truth for building the pane command (prompt precedence)
and for the side effects of a dispatch: event log, worker log, notification,
and sending the command to the multiplexer pane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from .manager import WorkstreamsManager


@dataclass
class DispatchResult:
    """Outcome of a dispatch: exit code, human message, non-fatal warnings."""

    code: int
    message: str
    warnings: List[str] = field(default_factory=list)


def build_pane_command(
    subagent: str,
    issue: int = 0,
    prompt: Optional[str] = None,
    agent: Optional[str] = None,
) -> Tuple[str, str]:
    """Return ``(resolved_prompt, pane_cmd)``.

    ``prompt`` always wins over the ``--issue`` template; ``agent`` (if given)
    is prefixed to the pane command only.
    """
    resolved = prompt or (
        f"Work on issue #{issue} as {subagent}" if issue else f"as {subagent}"
    )
    pane_cmd = f"{agent} {resolved}" if agent else resolved
    return resolved, pane_cmd


def dispatch_workstream(
    manager: "WorkstreamsManager",
    workstream_id: int,
    subagent: str,
    issue: int = 0,
    prompt: Optional[str] = None,
    agent: Optional[str] = None,
    wait: bool = False,
) -> DispatchResult:
    """Dispatch a subagent to a workstream pane.

    Returns code 5 when the workstream is unknown; otherwise 0 (or the
    ``_wait_for_done`` exit code when ``wait`` is set). Mux send failures are
    collected as warnings instead of failing the dispatch.
    """
    resolved, pane_cmd = build_pane_command(subagent, issue, prompt, agent)

    ws = manager.config.workstream(workstream_id)
    if not ws:
        return DispatchResult(5, f"Workstream {workstream_id} not found")

    # Dynamic module access so tests can patch subagent_client.subagent_started
    from . import subagent_client

    subagent_client.subagent_started(
        manager.config.project, workstream_id, subagent, issue, resolved
    )
    manager._append_workstream_log(ws, f"DISPATCH [{subagent}] {pane_cmd}")
    manager.notifier.send(
        f"Workstream {ws.name}",
        f"{subagent} started" + (f" on #{issue}" if issue else ""),
    )
    message = f"Dispatched {subagent} -> workstream {ws.name}" + (
        f" (issue #{issue})" if issue else ""
    )

    warnings: List[str] = []
    mux = manager._get_multiplexer()
    if mux is not None:
        try:
            sent = mux.send_command(workstream_id, pane_cmd)
            if sent is False:
                warnings.append("pane send returned False")
        except Exception as e:  # noqa: BLE001 - mux failures must not crash dispatch
            warnings.append(f"pane send failed: {e}")

    code = 0
    if wait:
        code = manager._wait_for_done(workstream_id, subagent)
    return DispatchResult(code, message, warnings)
