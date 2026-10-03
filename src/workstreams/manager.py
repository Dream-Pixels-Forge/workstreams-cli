"""Core Workstreams Manager - init, start, dispatch, sync, PR, merge, monitor."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_config, save_config
from .models import WorkstreamConfig, WorkstreamsConfig
from .event_log import get_event_log, EventLog
from .notifier import Notifier
from .subagent_client import subagent_report, subagent_done, subagent_started
from .multiplexer import get_multiplexer


class WorkstreamsManager:
    """Main manager for workstreams."""

    def __init__(self, config: WorkstreamsConfig):
        self.config = config
        self.base_path = Path(config.base_path).resolve()
        self.config_file = self.base_path / ".workstreams.yaml"
        self.event_log = get_event_log(config.project)
        self.notifier = Notifier(config.project)
        self._mux = None

    # -- multiplexer ---------------------------------------------------------

    def _get_multiplexer(self):
        if self._mux is None:
            try:
                self._mux = get_multiplexer(self.config.multiplexer, self.config)
            except ValueError:
                self._mux = None
        return self._mux

    # -- init ----------------------------------------------------------------

    def init_project(
        self,
        force: bool = False,
        num_workstreams: int = 4,
        agent: Optional[str] = None,
    ) -> bool:
        """Initialize workstreams for a project.

        Creates git worktrees (or branches) + config file. Does NOT
        create a multiplexer session - call start() for that.
        """
        if self.config_file.exists() and not force:
            print(
                f"Configuration already exists at {self.config_file}. "
                "Use --force to overwrite."
            )
            return False

        if not self.config.workstreams:
            for i in range(1, num_workstreams + 1):
                ws = WorkstreamConfig(
                    id=i,
                    name=f"ws{i}",
                    path=f"worktrees/ws{i}",
                    branch=f"ws/{i}",
                    command="",
                    env={},
                )
                self.config.workstreams.append(ws)

        if agent:
            self.config.agent = agent

        for ws in self.config.workstreams:
            self._create_workstream(ws)

        save_config(self.config, self.base_path)
        print(
            f"Initialized {len(self.config.workstreams)} workstream(s) for "
            f"project '{self.config.project}'"
        )
        print(f"  Config: {self.config_file}")
        print("  Next:  workstreams start [--cmd 'claude']")
        return True

    def _create_workstream(self, ws: WorkstreamConfig) -> None:
        ws_path = self.base_path / ws.path
        ws_path.parent.mkdir(parents=True, exist_ok=True)

        if self.config.mode == "worktree":
            try:
                # Fast path: branch already exists
                result = subprocess.run(
                    ["git", "worktree", "add", str(ws_path), ws.branch],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                _ = result
                created = True
            except (subprocess.CalledProcessError, subprocess.SubprocessError):
                created = False
            if not created:
                # Branch may not exist yet - create it from base branch
                base = self.config.base_branch
                probe = subprocess.run(["git", "rev-parse", "--verify", base], capture_output=True, text=True)
                if probe.returncode != 0:
                    base = "HEAD"
                    print(f"  (base branch '{self.config.base_branch}' not found; using HEAD)")
                r2 = subprocess.run(
                    ["git", "branch", ws.branch, base],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if r2.returncode != 0 and "already" not in (r2.stderr or "").lower():
                    print(f"  warning: could not create branch {ws.branch}: {(r2.stderr or '').strip()}")
                r3 = subprocess.run(
                    ["git", "worktree", "add", str(ws_path), ws.branch],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if r3.returncode != 0:
                    # Clean partial state and fail with a clear message
                    if ws_path.exists() and ws_path.is_dir():
                        shutil.rmtree(ws_path, ignore_errors=True)
                    print(f"  error: git worktree add failed for {ws.branch}: {(r3.stderr or '').strip()}")
                    print(f"  Run 'git worktree prune' and retry, or use --no-worktrees.")
                    return
        else:
            ws_path.mkdir(parents=True, exist_ok=True)

        (ws_path / "logs").mkdir(exist_ok=True)

    # -- start / attach -------------------------------------------------------

    def start(self, workstream_id: Optional[int] = None, command: Optional[str] = None) -> None:
        """Start workstreams in the configured multiplexer."""
        workstreams = self._filter_ws(workstream_id)
        mux = self._get_multiplexer()
        if mux is None:
            print(f"Unsupported multiplexer: {self.config.multiplexer}")
            return
        mux.start([ws.to_dict() for ws in workstreams], command)

    def attach(self, multiplexer: Optional[str] = None, session: Optional[str] = None) -> None:
        mux_name = multiplexer or self.config.multiplexer
        sess = session or f"workstreams-{self.config.project}"
        mux = get_multiplexer(mux_name, self.config)
        mux.attach(sess)

    # -- status / monitor ------------------------------------------------------

    def status(self, workstream_id: Optional[int] = None, verbose: bool = False, live: bool = False, as_json: bool = False) -> None:
        if live:
            self.monitor(refresh=2, once=False)
            return
        statuses = []
        for ws in self._filter_ws(workstream_id):
            from .dashboard import LiveDashboard
            dash = LiveDashboard(self, auto_refresh=False)
            statuses.append(dash._get_workstream_status(ws))

        if as_json:
            print(json.dumps([s.to_dict() for s in statuses], indent=2, default=str))
            return

        for s in statuses:
            print(f"\n=== Workstream {s.id}: {s.name} ===")
            print(f"  Path:     {s.path}")
            print(f"  Branch:   {s.branch}")
            print(f"  Git:      {s.git_status}")
            print(f"  Last:     {s.last_commit or s.last_activity or '-'}")
            print(f"  Pane:     {s.pane or '-'}")
            if s.pid:
                print(f"  PID:      {s.pid}")
            if s.alerts:
                print("  Alerts:")
                for a in s.alerts:
                    print(f"    - {a}")

    def monitor(self, refresh: int = 2, once: bool = False) -> None:
        from .dashboard import LiveDashboard
        dash = LiveDashboard(self, auto_refresh=not once)
        dash.refresh_rate = float(refresh)
        if once:
            print(dash.render_once())
        else:
            dash.run()

    # -- dispatch (the core workstream concept) --------------------------------

    def dispatch(
        self,
        workstream_id: int,
        subagent: str,
        issue: int,
        prompt: Optional[str] = None,
        wait: bool = False,
    ) -> int:
        """Dispatch a subagent to a workstream pane.

        Logs a `started` event, appends to the workstream log, notifies
        other terminals, and (if the multiplexer session is running)
        sends the prompt to the pane via tmux send-keys.

        Returns exit code: 0 ok, 5 workstream not found, 4 mux unavailable.
        """
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return 5

        prompt = prompt or f"Work on issue #{issue} as {subagent}"

        subagent_started(self.config.project, workstream_id, subagent, issue, prompt)

        self._append_workstream_log(ws, f"DISPATCH [{subagent}] issue #{issue}: {prompt}")

        self.notifier.send(
            f"Workstream {ws.name}",
            f"{subagent} started on issue #{issue}",
        )
        print(f"Dispatched {subagent} -> workstream {ws.name} (issue #{issue})")

        mux = self._get_multiplexer()
        if mux is not None:
            try:
                mux.send_command(workstream_id, prompt)
            except Exception as e:
                print(f"  (warning) could not send to pane: {e}", file=sys.stderr)

        if wait:
            # Block until the subagent reports 'done' or 'completed'
            return self._wait_for_done(workstream_id, subagent)

        return 0

    def _wait_for_done(self, workstream_id: int, subagent: str) -> int:
        """Poll the event log until this subagent reports done/completed/failed."""
        print(f"Waiting for {subagent} on workstream {workstream_id} to finish...")
        import time as _time
        deadline = _time.time() + 4 * 3600  # 4h safety
        last_seen = 0
        while _time.time() < deadline:
            events = self.event_log.get_events(workstream_id=workstream_id)
            tail = [e for e in events if e.subagent == subagent]
            if len(tail) > last_seen:
                last_seen = len(tail)
                for e in tail:
                    if e.event_type in ("completed", "failed", "done"):
                        label = {"completed": "completed", "failed": "FAILED", "done": "done"}[e.event_type]
                        print(f"  {subagent} {label}: {e.message}")
                        return 0 if e.event_type != "failed" else 1
            _time.sleep(3)
        print("  (timeout) no terminal event received", file=sys.stderr)
        return 2

    # -- work (new: run agent command in pane + wait) ---------------------------

    def work(
        self,
        workstream_id: int,
        agent_cmd: str,
        task: str,
        subagent: str = "agent",
        issue: int = 0,
        wait: bool = False,
    ) -> int:
        """Run an agent command in a workstream pane.

        This is the agent-agnostic entry point: the `agent_cmd` is anything
        like `claude`, `codex`, `opencode run`, `qwen`, `cline`, ...
        We build: `<agent_cmd> <task>` (plus optional flags via env) and
        send it to the pane.
        """
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return 5

        command = f"{agent_cmd} {task}"
        self._append_workstream_log(ws, f"WORK [{subagent}] {command}")

        if wait:
            subagent_started(self.config.project, workstream_id, subagent, issue, command)

        mux = self._get_multiplexer()
        if mux is not None:
            try:
                mux.send_command(workstream_id, command)
                print(f"Sent to workstream {ws.name}: {command}")
            except Exception as e:
                print(f"(warning) pane send failed: {e}", file=sys.stderr)
        else:
            print(f"(no multiplexer session - ran command in shell instead)")
            result = subprocess.run(command, shell=True, cwd=self.base_path / ws.path)
            rc = result.returncode

        if wait:
            return self._wait_for_done(workstream_id, subagent)
        return 0

    # -- assign ----------------------------------------------------------------

    def assign(self, workstream_id: int, issue_numbers: List[int]) -> None:
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return
        self._append_workstream_log(ws, f"ASSIGN issues {issue_numbers}")
        print(f"Assigned issues {issue_numbers} to workstream {ws.name}")

    # -- sync -------------------------------------------------------------------

    def sync(self, workstream_id: Optional[int] = None, rebase: bool = False) -> int:
        rc = 0
        for ws in self._filter_ws(workstream_id):
            ws_path = self.base_path / ws.path
            if not ws_path.exists():
                print(f"  {ws.name}: path missing, skipping")
                rc = 3
                continue
            print(f"Syncing {ws.name}...")
            for cmd in (
                ["git", "fetch", "origin"],
                ["git", "rebase", f"origin/{self.config.base_branch}"] if rebase
                else ["git", "merge", f"origin/{self.config.base_branch}"],
            ):
                result = subprocess.run(cmd, cwd=ws_path, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"  failed: {result.stderr.strip() or result.stdout.strip()}")
                    rc = 3
                    break
            else:
                print(f"  Synced {ws.name}")
        return rc

    # -- PR -------------------------------------------------------------------

    def pr(
        self,
        workstream_id: int,
        title: str,
        body: str = "",
        base: Optional[str] = None,
        draft: bool = False,
    ) -> int:
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return 5
        base = base or self.config.base_branch

        ws_path = self.base_path / ws.path
        result = subprocess.run(
            ["git", "push", "origin", ws.branch],
            cwd=ws_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Push failed: {result.stderr.strip()}")
            return 3

        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base,
            "--head", ws.branch,
        ]
        if draft:
            cmd.append("--draft")
        result = subprocess.run(cmd, cwd=ws_path, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Created PR: {result.stdout.strip()}")
        else:
            print(f"Failed to create PR: {result.stderr.strip()}")
        return 0 if result.returncode == 0 else 3

    # -- merge ------------------------------------------------------------------

    def merge(
        self,
        workstream_id: int,
        method: str = "squash",
        delete_branch: bool = False,
        auto: bool = False,
    ) -> int:
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return 5

        cmd = ["gh", "pr", "merge", ws.branch, "--method", method]
        if delete_branch:
            cmd.append("--delete-branch")
        if auto:
            cmd.append("--auto")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Merged {ws.name} ({method})")
            if delete_branch:
                ws_path = self.base_path / ws.path
                subprocess.run(["git", "worktree", "remove", str(ws_path)], check=False, capture_output=True)
                if ws_path.exists():
                    shutil.rmtree(ws_path, ignore_errors=True)
        else:
            print(f"Failed to merge: {result.stderr.strip()}")
        return 0 if result.returncode == 0 else 3

    # -- run -------------------------------------------------------------------

    def run(self, workstream_id: int, command: str) -> bool:
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return False
        ws_path = self.base_path / ws.path
        result = subprocess.run(command, shell=True, cwd=ws_path, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        self._append_workstream_log(ws, f"RUN: {command} -> exit {result.returncode}")
        return result.returncode == 0

    # -- logs ------------------------------------------------------------------

    def logs(self, workstream_id: int, follow: bool = False, lines: int = 100) -> None:
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return
        ws_path = self.base_path / ws.path
        log_file = ws_path / "logs" / "worker.log"
        if not log_file.exists():
            print(f"No log file at {log_file}")
            return
        # Use Python for cross-platform (tail -f equivalent on Windows)
        if follow:
            import time as _time
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    # Seek to end, then poll
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end="")
                        else:
                            _time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        else:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            for ln in all_lines[-lines:]:
                print(ln, end="")

    def tail_logs(self, workstream_id: Optional[int] = None, follow: bool = True) -> None:
        ws_list = self._filter_ws(workstream_id)
        if len(ws_list) == 1:
            self.logs(ws_list[0].id, follow=follow)
            return
        print("Tailing logs from all workstreams (Ctrl+C to stop):")
        for ws in ws_list:
            print(f"\n--- {ws.name} ({self.base_path / ws.path}) ---")
            self.logs(ws.id, follow=False, lines=20)

    # -- events / notify -------------------------------------------------------

    def get_events(
        self,
        workstream_id: Optional[int] = None,
        since_minutes: int = 10,
        event_type: Optional[str] = None,
        subagent: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(minutes=since_minutes)
        events = self.event_log.get_events(
            workstream_id=workstream_id,
            since=since,
            event_type=event_type,
            subagent=subagent,
            limit=limit,
        )
        return [e.to_dict() for e in events]

    def notify(self, title: str, message: str, urgency: str = "normal") -> None:
        self.notifier.send(title, message, urgency)

    # -- workstream management ---------------------------------------------------

    def add_workstream(self, name: str, branch: str, path: Optional[str] = None, command: str = "") -> WorkstreamConfig:
        existing = len(self.config.workstreams)
        new_id = max((ws.id for ws in self.config.workstreams), default=0) + 1
        ws = WorkstreamConfig(
            id=new_id,
            name=name,
            path=path or f"worktrees/{name}",
            branch=branch,
            command=command,
            env={},
        )
        self.config.workstreams.append(ws)
        self._create_workstream(ws)
        save_config(self.config, self.base_path)
        print(f"Added workstream {new_id} ({name}) -> {ws.path} on {branch}")
        _ = existing
        return ws

    def remove_workstream(self, workstream_id: int, force: bool = False) -> int:
        ws = self.config.workstream(workstream_id)
        if not ws:
            print(f"Workstream {workstream_id} not found")
            return 5
        ws_path = self.base_path / ws.path
        if ws_path.exists() and ws_path.is_dir():
            if not force:
                print(f"Refusing to remove {ws_path} without --force (workstream may have uncommitted work)")
                return 1
            # Remove worktree (best effort)
            subprocess.run(["git", "worktree", "remove", str(ws_path)], check=False, capture_output=True)
            shutil.rmtree(ws_path, ignore_errors=True)
        self.config.workstreams = [x for x in self.config.workstreams if x.id != workstream_id]
        save_config(self.config, self.base_path)
        print(f"Removed workstream {workstream_id} ({ws.name})")
        return 0

    def cleanup(self, workstream_id: Optional[int] = None, force: bool = False, all_done: bool = False) -> None:
        """Remove worktrees for completed (or all) workstreams."""
        targets = self._filter_ws(workstream_id) if not all_done else self._filter_ws(workstream_id)
        if all_done:
            targets = self._filter_ws(None)
        for ws in targets:
            ws_path = self.base_path / ws.path
            if not ws_path.exists():
                continue
            if not force and not workstream_id and not all_done:
                print(f"Skipping {ws.name} (use --force or --all)")
                continue
            subprocess.run(["git", "worktree", "remove", str(ws_path)], check=False, capture_output=True)
            shutil.rmtree(ws_path, ignore_errors=True)
            print(f"Cleaned up {ws.name}")

    # -- helpers -----------------------------------------------------------------

    def _filter_ws(self, workstream_id: Optional[int]) -> List[WorkstreamConfig]:
        if workstream_id is None:
            return list(self.config.workstreams)
        return [ws for ws in self.config.workstreams if ws.id == workstream_id]

    def _append_workstream_log(self, ws: WorkstreamConfig, line: str) -> None:
        ws_path = self.base_path / ws.path
        log_file = ws_path / "logs" / "worker.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).isoformat()
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {line}\n")
        except OSError:
            pass

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat()
