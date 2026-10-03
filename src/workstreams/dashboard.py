"""Live monitoring dashboard.

Renders a full-screen TUI (curses-free, ANSI based) showing all
workstreams, their git status, running PIDs, log tails, alerts, and
the most recent subagent events. Ctrl+C or `q` exits.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import WorkstreamStatus, SubagentEvent
from .event_log import get_event_log
from .notifier import Notifier
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import WorkstreamsManager

# ANSI helpers
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

HEADER = "1;36"
DIM = "90"
GREEN = "32"
YELLOW = "33"
RED = "31"
CYAN = "36"
BLUE = "34"
MAGENTA = "35"
BOLD = "1"


class LiveDashboard:
    """Terminal-based live monitoring dashboard."""

    def __init__(self, manager: "WorkstreamsManager", auto_refresh: bool = True):
        self.manager = manager
        self.running = False
        self.refresh_rate = 2.0
        self.width = 100
        self.auto_refresh = auto_refresh

    # -- public API --------------------------------------------------------

    def run(self) -> None:
        """Run the dashboard until KeyboardInterrupt or 'q' key."""
        self.running = True
        self._detect_width()
        try:
            while self.running:
                self._render()
                if not self.auto_refresh:
                    break
                # Wait for refresh interval, but break early on 'q'
                try:
                    import select
                    ready, _, _ = select.select([sys.stdin], [], [], self.refresh_rate)
                    if ready:
                        ch = sys.stdin.read(1)
                        if ch in ("q", "Q", "\x03"):
                            break
                except (ImportError, OSError):
                    time.sleep(self.refresh_rate)
        except KeyboardInterrupt:
            pass
        finally:
            # Show cursor, reset
            print("\n\033[?25h\033[0m", end="")

    def render_once(self) -> str:
        """Render one frame and return it (for tests / `workstreams status --once`)."""
        self._detect_width()
        return self._build_frame()

    # -- internals ---------------------------------------------------------

    def _detect_width(self) -> None:
        try:
            import shutil
            w = shutil.get_terminal_size().columns
            self.width = max(60, min(w, 140))
        except Exception:
            self.width = 100

    def _render(self) -> None:
        frame = self._build_frame()
        # Clear and print
        sys.stdout.write("\033[2J\033[H\033[?25l")
        sys.stdout.write(frame + "\n")
        sys.stdout.flush()

    def _build_frame(self) -> str:
        now = datetime.now().strftime("%H:%M:%S")
        project = self.manager.config.project
        lines: List[str] = []
        w = self.width

        lines.append(_c(HEADER, "=" * w))
        title = f"  WORKSTREAMS MONITOR  |  {project}  |  {now}  |  q/Ctrl+C to exit"
        lines.append(_c(HEADER, title))
        lines.append(_c(HEADER, "=" * w))

        statuses = self._get_all_statuses()
        total = len(statuses)
        active = sum(1 for s in statuses if s.pid is not None)
        dirty = sum(1 for s in statuses if s.git_status == "dirty")
        clean = sum(1 for s in statuses if s.git_status == "clean")
        errors = sum(len(s.alerts) for s in statuses)

        summary = (
            f"  Total: {total}  |  "
            f"{_c(GREEN, f'Active: {active}')}  |  "
            f"{_c(GREEN, f'Clean: {clean}')}  "
            f"{_c(YELLOW, f'Dirty: {dirty}')}  |  "
            f"{_c(RED, f'Alerts: {errors}')}"
        )
        lines.append(summary)
        lines.append(_c(DIM, "-" * w))

        # Workstream table header
        header = (
            f"  {'ID':>3}  {'NAME':<16}  {'BRANCH':<20}  "
            f"{'GIT':<8}  {'PID':>8}  {'LAST COMMIT / ACTIVITY'}"
        )
        lines.append(_c(BOLD, header))
        lines.append(_c(DIM, "-" * w))

        for s in statuses:
            lines.append(self._workstream_row(s))

        # Alerts
        all_alerts: List[str] = []
        for s in statuses:
            for alert in s.alerts:
                all_alerts.append(f"[{s.name}] {alert}")
        if all_alerts:
            lines.append("")
            lines.append(_c(BOLD, _c(YELLOW, "  RECENT ALERTS:")))
            for alert in all_alerts[-5:]:
                lines.append(f"  {_c(YELLOW, '⚠')}  {alert}")

        # Subagent activity
        events = self._get_recent_events()
        if events:
            lines.append("")
            lines.append(_c(BOLD, _c(MAGENTA, "  SUBAGENT ACTIVITY (last 10):")))
            for event in events[-10:]:
                color = self._event_color(event.event_type)
                ts = event.timestamp[11:19] if event.timestamp else ""
                lines.append(
                    f"  {_c(color, ts)}  "
                    f"{_c(CYAN, '[' + event.subagent + ']')}"
                    f"  #{event.issue}  {_c(color, event.event_type)}: "
                    f"{event.message[:60]}"
                )

        return "\n".join(lines)

    def _workstream_row(self, s: WorkstreamStatus) -> str:
        if s.git_status == "clean":
            git_color = GREEN
            git_text = "clean"
        elif s.git_status == "dirty":
            git_color = YELLOW
            git_text = "dirty"
        else:
            git_color = RED
            git_text = s.git_status or "unknown"

        pid_text = str(s.pid) if s.pid else "-"
        activity = s.last_commit or s.last_activity or "-"

        return (
            f"  {s.id:>3}  {_c(BOLD, s.name[:16].ljust(16))}  {s.branch[:20].ljust(20)}  "
            f"{_c(git_color, git_text.ljust(8))}  {pid_text:>8}  {activity[:40]}"
        )

    # -- data gathering -----------------------------------------------------

    def _get_all_statuses(self) -> List[WorkstreamStatus]:
        return [self._get_workstream_status(ws) for ws in self.manager.config.workstreams]

    def _get_workstream_status(self, ws) -> WorkstreamStatus:
        ws_path = Path(self.manager.config.base_path) / ws.path
        git_status = "unknown"
        last_commit = ""
        last_activity = ""
        pid: Optional[int] = None
        pane: Optional[str] = None
        alerts: List[str] = []

        # Resolve tmux pane if configured
        try:
            mux = self.manager._get_multiplexer()
            if mux is not None:
                pane = mux.pane_target(ws.id)
                if getattr(mux, "is_running", lambda: False)():
                    pid = 1  # marker that session is alive
        except Exception:
            pass

        if ws_path.exists():
            git_status = self._git_status(ws_path)
            last_commit = self._last_commit(ws_path)
            last_activity = self._last_activity(ws_path)

            # PID via tmux process check or pgrep
            if pid is None:
                pid = self._find_pid(ws_path, ws.name)

            alerts = self._log_alerts(ws_path)

        return WorkstreamStatus(
            id=ws.id,
            name=ws.name,
            branch=ws.branch,
            path=str(ws_path),
            git_status=git_status,
            last_commit=last_commit,
            last_activity=last_activity,
            pid=pid,
            command=ws.command,
            pane=pane,
            alerts=alerts,
        )

    @staticmethod
    def _git_status(ws_path: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=ws_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return "not-git"
            return "dirty" if result.stdout.strip() else "clean"
        except (subprocess.SubprocessError, OSError):
            return "unknown"

    @staticmethod
    def _last_commit(ws_path: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                cwd=ws_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:50]
        except (subprocess.SubprocessError, OSError):
            pass
        return ""

    @staticmethod
    def _last_activity(ws_path: Path) -> str:
        log = ws_path / "logs" / "worker.log"
        if not log.exists():
            return ""
        try:
            mtime = log.stat().st_mtime
            delta = datetime.now() - datetime.fromtimestamp(mtime)
            secs = int(delta.total_seconds())
            if secs < 60:
                return f"{secs}s ago"
            if secs < 3600:
                return f"{secs // 60}m ago"
            return f"{secs // 3600}h ago"
        except OSError:
            return ""

    @staticmethod
    def _find_pid(ws_path: Path, ws_name: str) -> Optional[int]:
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"workstreams-{ws_name}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().split()[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return None

    @staticmethod
    def _log_alerts(ws_path: Path) -> List[str]:
        log = ws_path / "logs" / "worker.log"
        if not log.exists():
            return []
        try:
            result = subprocess.run(
                ["grep", "-in", "error\\|fail\\|warning\\|traceback", str(log)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                lines = [ln for ln in result.stdout.strip().split("\n") if ln]
                return lines[-3:]
        except (OSError, subprocess.SubprocessError):
            pass
        return []

    def _get_recent_events(self) -> List[SubagentEvent]:
        event_log = get_event_log(self.manager.config.project)
        since = datetime.now(UTC) - timedelta(minutes=10)
        return event_log.get_events(since=since)

    @staticmethod
    def _event_color(event_type: str) -> str:
        return {
            "started": CYAN,
            "progress": BLUE,
            "completed": GREEN,
            "done": GREEN,
            "failed": RED,
            "error": RED,
        }.get(event_type, "37")

    # -- module-level helpers ---------------------------------------------

import sys  # noqa: E402  (used in run() for select loop)
