"""CLI entry point for workstreams.

Usage:
  workstreams <command> [options]

Every command accepts --project to pick which project config to use.
Most commands also accept --json for machine-readable output (useful for
coding agents that want to parse status).

Exit codes:
  0  success
  1  general error
  2  invalid arguments
  3  git / gh error
  4  multiplexer unavailable
  5  workstream not found
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import List, Optional

from .config import load_config, save_config, find_config_file
from .manager import WorkstreamsManager
from .event_log import get_event_log
from .subagent_client import subagent_report
from . import __version__


def _load_manager(args) -> WorkstreamsManager:
    """Build a manager from parsed args."""
    base_path = Path.cwd()
    if getattr(args, "project", None):
        # Look up .workstreams.yaml in cwd first, then fall back to cwd
        config = load_config(base_path, project=args.project)
        # If the user passed --project explicitly, trust it over the file's value
        config.project = args.project
    else:
        config = load_config(base_path)

    if getattr(args, "multiplexer", None):
        config.multiplexer = args.multiplexer
    if getattr(args, "layout", None):
        config.layout = args.layout
    if getattr(args, "base_branch", None):
        config.base_branch = args.base_branch

    manager = WorkstreamsManager(config)

    # Auto-init if no workstreams defined and command needs them
    if not config.workstreams and args.command in ("start", "dispatch", "work", "run", "logs", "sync", "assign"):
        manager.config.workstreams = _default_workstreams(manager, getattr(args, "workstream", 1))
        save_config(manager.config, manager.base_path)
    return manager


def _default_workstreams(manager: WorkstreamsManager, first_id: int = 1):
    from .models import WorkstreamConfig
    return [
        WorkstreamConfig(
            id=first_id,
            name=f"ws{first_id}",
            path=f"worktrees/ws{first_id}",
            branch=f"ws/{first_id}",
            command="",
            env={},
        )
    ]


# =============================================================================
# Subcommand builders
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workstreams",
        description="Visually dispatch coding-agent work to subagents in real terminal windows and monitor it in one dashboard.",
        epilog="See `workstreams <command> --help` for per-command options.",
    )
    parser.add_argument("--version", action="version", version=f"workstreams {__version__}")

    sub = parser.add_subparsers(dest="command")

    # ---- shared parent for most commands ----
    def common_parent(name: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=f"{name} - see --help")
        p.add_argument("--project", help="Project name (default: from .workstreams.yaml or cwd)")
        p.add_argument("--json", action="store_true", help="Emit JSON output where supported")
        return p

    # init
    init = common_parent("init")
    init.add_argument("--workstreams", type=int, default=4, help="Number of workstreams to create (default: 4)")
    init.add_argument("--multiplexer", choices=["tmux", "zellij", "nami", "lmux", "wmux", "herdr"], default=None, help="Multiplexer type")
    init.add_argument("--layout", choices=["even-horizontal", "even-vertical", "main-horizontal", "tiled"], default=None)
    init.add_argument("--base-branch", default=None, help="Base branch (default: main)")
    init.add_argument("--mode", choices=["worktree", "branch"], default=None, help="worktree (isolated) or branch (shared dir)")
    init.add_argument("--agent", choices=["auto", "claude", "codex", "opencode", "qwen", "generic"], default=None)
    init.add_argument("--force", action="store_true", help="Overwrite existing config")
    init.add_argument("--no-worktrees", action="store_true", help="Skip creating git worktrees (config only)")

    # start
    start = common_parent("start")
    start.add_argument("--workstream", type=int, help="Start a single workstream by ID")
    start.add_argument("--cmd", help="Override the command sent to each pane")
    start.add_argument("--multiplexer", choices=["tmux", "zellij", "nami", "lmux", "wmux", "herdr"], default=None)
    start.add_argument("--layout", choices=["even-horizontal", "even-vertical", "main-horizontal", "tiled"], default=None)

    # attach
    attach = common_parent("attach")
    attach.add_argument("--multiplexer", choices=["tmux", "zellij", "nami", "lmux", "wmux", "herdr"], default=None)
    attach.add_argument("--session", help="Override session name")

    # status
    status = common_parent("status")
    status.add_argument("--workstream", type=int, help="Show one workstream")
    status.add_argument("--live", action="store_true", help="Watch mode (same as monitor)")
    status.add_argument("--once", action="store_true", help="Single frame, exit")

    # monitor
    monitor = common_parent("monitor")
    monitor.add_argument("--refresh", type=int, default=2, help="Seconds between frames")
    monitor.add_argument("--once", action="store_true", help="Render one frame and exit")

    # workstream add / remove / cleanup
    ws_sub = sub.add_parser("workstream", help="Manage workstreams (add, remove, cleanup)")
    ws_sub_sub = ws_sub.add_subparsers(dest="ws_command")

    ws_add = ws_sub_sub.add_parser("add", help="Add a workstream")
    ws_add.add_argument("--project", help="Project name")
    ws_add.add_argument("--name", required=True)
    ws_add.add_argument("--branch", required=True)
    ws_add.add_argument("--path", help="Worktree path (default: worktrees/<name>)")
    ws_add.add_argument("--command", default="", help="Default command for this pane")
    ws_add.add_argument("--json", action="store_true")

    ws_remove = ws_sub_sub.add_parser("remove", help="Remove a workstream")
    ws_remove.add_argument("--project", help="Project name")
    ws_remove.add_argument("--workstream", type=int, required=True)
    ws_remove.add_argument("--force", action="store_true", help="Delete directory + worktree")
    ws_remove.add_argument("--json", action="store_true")

    ws_cleanup = ws_sub_sub.add_parser("cleanup", help="Clean up completed workstreams")
    ws_cleanup.add_argument("--project", help="Project name")
    ws_cleanup.add_argument("--workstream", type=int)
    ws_cleanup.add_argument("--all", dest="all_done", action="store_true", help="Clean all workstreams")
    ws_cleanup.add_argument("--force", action="store_true")
    ws_cleanup.add_argument("--json", action="store_true")

    # dispatch
    dispatch = common_parent("dispatch")
    dispatch.add_argument("--workstream", type=int, required=True)
    dispatch.add_argument("--subagent", required=True, help="Subagent identifier (claude-code, codex, opencode, qwen-code, mimocode, hermes, kilo-code, cline, ... free-form)")
    dispatch.add_argument("--issue", type=int, default=0)
    dispatch.add_argument("--prompt", help="Prompt / task description sent to the pane")
    dispatch.add_argument("--agent", help="Agent binary to invoke (e.g. 'claude', 'codex', 'opencode run'). If omitted, sends --prompt verbatim to the pane.")
    dispatch.add_argument("--wait", action="store_true", help="Block until subagent reports done/failed")
    dispatch.add_argument("--multiplexer", choices=["tmux", "zellij", "nami", "lmux", "wmux", "herdr"], default=None)

    # work (run agent command directly)
    work = common_parent("work")
    work.add_argument("--workstream", type=int, required=True)
    work.add_argument("--agent", required=True, help="Agent command (claude, codex, opencode, qwen, cline, ...)")
    work.add_argument("--task", required=True, help="Task / prompt for the agent")
    work.add_argument("--subagent", default="agent", help="Identifier used in event log")
    work.add_argument("--issue", type=int, default=0)
    work.add_argument("--wait", action="store_true", help="Block until terminal event")
    work.add_argument("--multiplexer", choices=["tmux", "zellij", "nami", "lmux", "wmux", "herdr"], default=None)

    # run
    run = common_parent("run")
    run.add_argument("--workstream", type=int, required=True)
    run.add_argument("--cmd", required=True, dest="run_command")

    # logs
    logs = common_parent("logs")
    logs.add_argument("--workstream", type=int, required=True)
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--lines", type=int, default=100)

    # tail
    tail = common_parent("tail")
    tail.add_argument("--workstream", type=int)
    tail.add_argument("--lines", type=int, default=20)

    # events
    events = common_parent("events")
    events.add_argument("--workstream", type=int)
    events.add_argument("--since", type=int, default=10, help="Minutes back (default: 10)")
    events.add_argument("--type", choices=["started", "progress", "completed", "failed", "error", "done"], help="Filter")
    events.add_argument("--subagent", help="Filter by subagent name")
    events.add_argument("--limit", type=int, default=50)
    events.add_argument("--clear", action="store_true", help="Clear the event log")

    # event (emit an event from any process - the key agent-integration command)
    event = sub.add_parser("event", help="Emit a subagent event (for subagents / scripts to report)")
    event.add_argument("event_type", choices=["started", "progress", "completed", "failed", "error", "done"])
    event.add_argument("--project", required=True)
    event.add_argument("--workstream", type=int, default=0)
    event.add_argument("--subagent", required=True, help="Subagent identifier (free-form)")
    event.add_argument("--issue", type=int, default=0)
    event.add_argument("--message", default="")
    event.add_argument("--data", help="JSON object of extra data (e.g. '{\"files\": 3}')")
    event.add_argument("--confidence", type=float, default=None, help="Self-rated result quality 0-10 (stored in data.confidence)")
    event.add_argument("--json", action="store_true")

    # confidence (aggregate / gate on subagent self-ratings)
    confidence = common_parent("confidence")
    confidence.add_argument("--workstream", type=int, help="Restrict to one workstream")
    confidence.add_argument("--issue", type=int, help="Restrict to one issue")
    confidence.add_argument("--subagent", help="Filter by subagent name")
    confidence.add_argument("--since", type=int, default=43200, help="Minutes back (default: 30 days)")
    confidence.add_argument("--min-score", type=float, default=8.0, help="Pass threshold for the gate (default: 8.0)")
    confidence.add_argument("--records", action="store_true", help="List individual confidence-bearing events")

    # notify
    notify = common_parent("notify")
    notify.add_argument("--title", required=True)
    notify.add_argument("--message", required=True)
    notify.add_argument("--urgency", choices=["low", "normal", "critical"], default="normal")

    # assign
    assign = common_parent("assign")
    assign.add_argument("--workstream", type=int, required=True)
    assign.add_argument("--issue", type=int, action="append", required=True)

    # sync
    sync = common_parent("sync")
    sync.add_argument("--workstream", type=int)
    sync.add_argument("--rebase", action="store_true")

    # pr
    pr = common_parent("pr")
    pr.add_argument("--workstream", type=int, required=True)
    pr.add_argument("--title", required=True)
    pr.add_argument("--body", default="")
    pr.add_argument("--base", help="Target branch (default: config's base_branch)")
    pr.add_argument("--draft", action="store_true")

    # merge
    merge = common_parent("merge")
    merge.add_argument("--workstream", type=int, required=True)
    merge.add_argument("--method", choices=["merge", "squash", "rebase"], default="squash")
    merge.add_argument("--delete-branch", action="store_true")
    merge.add_argument("--auto", action="store_true")

    # status-json helper
    _ = parser
    return parser


# =============================================================================
# Command handlers
# =============================================================================

def _cmd_init(args) -> int:
    manager = _load_manager(args)
    if args.mode:
        manager.config.mode = args.mode
    if args.agent:
        manager.config.agent = args.agent
    if args.no_worktrees:
        # Skip git worktree creation; just write config
        from .models import WorkstreamConfig
        for i in range(1, args.workstreams + 1):
            manager.config.workstreams.append(WorkstreamConfig(
                id=i, name=f"ws{i}", path=f"worktrees/ws{i}",
                branch=f"ws/{i}", command="", env={},
            ))
        save_config(manager.config, manager.base_path)
        print(f"Initialized config only (no worktrees) for '{manager.config.project}'")
        return 0
    ok = manager.init_project(force=args.force, num_workstreams=args.workstreams, agent=args.agent)
    return 0 if ok else 1


def _cmd_start(args) -> int:
    manager = _load_manager(args)
    manager.start(workstream_id=args.workstream, command=args.cmd)
    return 0


def _cmd_attach(args) -> int:
    manager = _load_manager(args)
    manager.attach(multiplexer=args.multiplexer, session=args.session)
    return 0


def _cmd_status(args) -> int:
    manager = _load_manager(args)
    if args.live:
        manager.monitor(refresh=2, once=False)
        return 0
    manager.status(workstream_id=args.workstream, live=False, as_json=args.json or args.once)
    return 0


def _cmd_monitor(args) -> int:
    manager = _load_manager(args)
    manager.monitor(refresh=args.refresh, once=args.once)
    return 0


def _cmd_workstream(args) -> int:
    manager = _load_manager(args)
    if args.ws_command == "add":
        ws = manager.add_workstream(args.name, args.branch, args.path, args.command)
        if args.json:
            print(json.dumps(ws.to_dict(), indent=2))
        return 0
    if args.ws_command == "remove":
        return manager.remove_workstream(args.workstream, force=args.force)
    if args.ws_command == "cleanup":
        manager.cleanup(workstream_id=args.workstream, force=args.force, all_done=args.all_done)
        return 0
    print("Usage: workstreams workstream {add|remove|cleanup} --help")
    return 2


def _cmd_dispatch(args) -> int:
    manager = _load_manager(args)
    # Build the pane command
    prompt = args.prompt or f"Work on issue #{args.issue} as {args.subagent}" if args.issue else f"as {args.subagent}"
    if args.agent:
        pane_cmd = f"{args.agent} {prompt}"
        if args.issue:
            pane_cmd = f"{args.agent} {prompt}"
    else:
        pane_cmd = prompt

    # Re-use dispatch for logging/notify, then send the actual agent command
    ws = manager.config.workstream(args.workstream)
    if not ws:
        print(f"Workstream {args.workstream} not found", file=sys.stderr)
        return 5

    from .subagent_client import subagent_started, subagent_report as _report
    subagent_started(manager.config.project, args.workstream, args.subagent, args.issue, prompt)
    manager._append_workstream_log(ws, f"DISPATCH [{args.subagent}] {pane_cmd}")
    manager.notifier.send(f"Workstream {ws.name}", f"{args.subagent} started" + (f" on #{args.issue}" if args.issue else ""))
    print(f"Dispatched {args.subagent} -> workstream {ws.name}" + (f" (issue #{args.issue})" if args.issue else ""))

    mux = manager._get_multiplexer()
    if mux is not None:
        try:
            mux.send_command(args.workstream, pane_cmd)
        except Exception as e:
            print(f"  (warning) pane send failed: {e}", file=sys.stderr)

    if args.wait:
        return manager._wait_for_done(args.workstream, args.subagent)
    return 0


def _cmd_work(args) -> int:
    manager = _load_manager(args)
    return manager.work(
        args.workstream,
        agent_cmd=args.agent,
        task=args.task,
        subagent=args.subagent,
        issue=args.issue,
        wait=args.wait,
    )


def _cmd_run(args) -> int:
    manager = _load_manager(args)
    ok = manager.run(args.workstream, args.run_command)
    return 0 if ok else 1


def _cmd_logs(args) -> int:
    manager = _load_manager(args)
    manager.logs(args.workstream, follow=args.follow, lines=args.lines)
    return 0


def _cmd_tail(args) -> int:
    manager = _load_manager(args)
    manager.tail_logs(workstream_id=args.workstream, follow=False)
    return 0


def _cmd_events(args) -> int:
    manager = _load_manager(args)
    if args.clear:
        manager.event_log.clear()
        print("Event log cleared.")
        return 0
    events = manager.get_events(
        workstream_id=args.workstream,
        since_minutes=args.since,
        event_type=args.type,
        subagent=args.subagent,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(events, indent=2, default=str))
        return 0
    for e in events:
        ts = e.get("timestamp", "")[11:19]
        print(f"[{ts}] [{e['subagent']}] ws{e['workstream_id']} #{e['issue']} - {e['event_type']}: {e['message']}")
    if not events:
        print(f"(no events in last {args.since} min)")
    return 0


def _cmd_event(args) -> int:
    """Emit a single event from the calling process (subagent -> main terminal)."""
    data = {}
    if args.data:
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError:
            print(f"Invalid --data JSON: {args.data}", file=sys.stderr)
            return 2
    if getattr(args, "confidence", None) is not None:
        data["confidence"] = args.confidence
    ok = subagent_report(
        project=args.project,
        workstream_id=args.workstream,
        subagent=args.subagent,
        issue=args.issue,
        event_type=args.event_type,
        message=args.message,
        data=data,
    )
    if args.json:
        print(json.dumps({"ok": ok, "event_type": args.event_type, "subagent": args.subagent}))
    else:
        if ok:
            print(f"event [{args.event_type}] {args.subagent} ws{args.workstream} #{args.issue} -> {args.project}")
        else:
            print("failed to write event", file=sys.stderr)
    return 0 if ok else 1


def _cmd_confidence(args) -> int:
    """Aggregate / gate on subagent self-rated confidence scores."""
    from .confidence import get_confidence, confidence_records, clamp_score

    # clamp the threshold so a bogus --min-score can't break the gate
    min_score = clamp_score(args.min_score)
    if min_score is None:
        print(f"Invalid --min-score: {args.min_score}", file=sys.stderr)
        return 2

    # The event log is keyed by project, but confidence read commands are
    # project-scoped like the rest of the read side; fall back to .workstreams.yaml
    # if no --project was given.
    import os
    from .config import load_config
    project = getattr(args, "project", None)
    if not project:
        cfg = load_config(Path.cwd())
        project = cfg.project

    if args.records:
        records = confidence_records(
            project=project,
            workstream_id=args.workstream,
            issue=args.issue,
            subagent=args.subagent,
            since_minutes=args.since,
        )
        if args.json:
            print(json.dumps([r.to_dict() for r in records], indent=2, default=str))
            return 0
        if not records:
            print(f"(no confidence reports in last {args.since} min)")
            return 0
        for r in records:
            ts = r.timestamp[11:19]
            print(f"[{ts}] [{r.subagent}] ws{r.workstream_id} #{r.issue} - {r.event_type}: {r.score}/10 {r.message}")
        return 0

    summary = get_confidence(
        project=project,
        workstream_id=args.workstream,
        issue=args.issue,
        subagent=args.subagent,
        since_minutes=args.since,
        min_score=min_score,
    )
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2, default=str))
        return 0 if summary.passed else 1

    scope = f"ws{args.workstream}" if args.workstream else "project"
    if args.issue:
        scope += f" #{args.issue}"
    if summary.n_reports == 0:
        print(f"No confidence reports for {scope} yet.")
        return 1
    avg = f"{summary.avg_score:.1f}" if summary.avg_score is not None else "n/a"
    latest = f"{summary.latest_score:.1f}" if summary.latest_score is not None else "n/a"
    mark = "PASS" if summary.passed else "FAIL"
    print(f"Confidence for {scope}: {mark}")
    print(f"  latest: {latest}/10 ({summary.latest_event_type} from {summary.latest_subagent})")
    print(f"  average: {avg}/10 over {summary.n_reports} report(s)")
    print(f"  threshold: {min_score}/10 -> {summary.latest_message}")
    return 0 if summary.passed else 1


def _cmd_notify(args) -> int:
    manager = _load_manager(args)
    manager.notify(args.title, args.message, args.urgency)
    return 0


def _cmd_assign(args) -> int:
    manager = _load_manager(args)
    manager.assign(args.workstream, args.issue)
    return 0


def _cmd_sync(args) -> int:
    manager = _load_manager(args)
    return manager.sync(workstream_id=args.workstream, rebase=args.rebase)


def _cmd_pr(args) -> int:
    manager = _load_manager(args)
    return manager.pr(args.workstream, args.title, args.body, args.base, args.draft)


def _cmd_merge(args) -> int:
    manager = _load_manager(args)
    return manager.merge(args.workstream, args.method, args.delete_branch, args.auto)


HANDLERS = {
    "init": _cmd_init,
    "start": _cmd_start,
    "attach": _cmd_attach,
    "status": _cmd_status,
    "monitor": _cmd_monitor,
    "workstream": _cmd_workstream,
    "dispatch": _cmd_dispatch,
    "work": _cmd_work,
    "run": _cmd_run,
    "logs": _cmd_logs,
    "tail": _cmd_tail,
    "events": _cmd_events,
    "event": _cmd_event,
    "confidence": _cmd_confidence,
    "notify": _cmd_notify,
    "assign": _cmd_assign,
    "sync": _cmd_sync,
    "pr": _cmd_pr,
    "merge": _cmd_merge,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    handler = HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
