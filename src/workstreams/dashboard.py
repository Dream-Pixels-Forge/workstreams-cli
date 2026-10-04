"""Live monitoring dashboard.

Renders a full-screen TUI (curses-free, ANSI based) showing all
workstreams, their git status, running PIDs, log tails, alerts, and
the most recent subagent events. Ctrl+C or `q` exits.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import subprocess
import time
import urllib.parse
from datetime import datetime, UTC, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import WorkstreamStatus, SubagentEvent
from .event_log import get_event_log
from .notifier import Notifier
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import WorkstreamsManager

# Logger
logger = logging.getLogger(__name__)

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
        except (AttributeError, TypeError, OSError) as e:
            logger.warning(f"Failed to get pane target for workstream {ws.id}: {e}")

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
    def _last_commit(ws_path: Path) -> Optional[str]:
        """Get the last commit hash for a workstream path.

        Returns None if the commit cannot be determined,
        rather than silently returning an empty string.
        """
        result: Optional[str] = None
        try:
            subprocess_result = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                cwd=ws_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if subprocess_result.returncode == 0 and subprocess_result.stdout.strip():
                result = subprocess_result.stdout.strip()[:50]
        except (subprocess.SubprocessError, OSError):
            pass
        return result

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
        """Find a PID for the workstream, cross-platform.

        On POSIX: uses pgrep. On Windows: returns None (no built-in
        process-name search without extra deps).
        """
        import platform
        if platform.system() == "Windows":
            return None
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
        # Cross-platform: read file and scan in Python instead of grep
        try:
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            alerts = []
            for i, ln in enumerate(lines, 1):
                low = ln.lower()
                if any(kw in low for kw in ("error", "fail", "warning", "traceback")):
                    alerts.append(f"{i}:{ln.rstrip()}")
            return alerts[-3:]
        except OSError:
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


# =============================================================================
# Web console: HTTP server exposing LiveDashboard data as JSON + static UI
# =============================================================================


def resolve_web_root(explicit: Optional[Path] = None) -> Optional[Path]:
    """Locate the static web console.

    Search order: explicit argument > ``WORKSTREAMS_WEB_DIR`` env var >
    ``web/`` in a source checkout > ``web/`` in the current directory.
    Returns None when no directory containing index.html is found.
    """
    candidates: List[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env = os.environ.get("WORKSTREAMS_WEB_DIR")
    if env:
        candidates.append(Path(env))
    # dashboard.py lives at <repo>/src/workstreams/ -> <repo>/web
    candidates.append(Path(__file__).resolve().parents[2] / "web")
    candidates.append(Path.cwd() / "web")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


class WebDashboard:
    """HTTP server serving the web console and a JSON API.

    Endpoints:
      GET  /api/config   - project configuration (.workstreams.yaml)
      GET  /api/status   - summary + workstream statuses + recent events
      GET  /api/events   - recent subagent events
      POST /api/dispatch - dispatch a subagent (same core as the CLI)
      GET  /*            - static files from the web/ console
    """

    def __init__(
        self,
        manager: "WorkstreamsManager",
        host: str = "127.0.0.1",
        port: int = 8765,
        web_root: Optional[Path] = None,
    ):
        self.manager = manager
        self.host = host
        self.port = port
        self.web_root = resolve_web_root(web_root)
        self.dashboard = LiveDashboard(manager, auto_refresh=False)
        self.httpd: Optional[ThreadingHTTPServer] = None

    # -- API handlers -------------------------------------------------------

    def api_config(self) -> Dict[str, Any]:
        return self.manager.config.to_dict()

    def api_status(self) -> Dict[str, Any]:
        statuses = self.dashboard._get_all_statuses()
        events = self.dashboard._get_recent_events()
        summary = {
            "total": len(statuses),
            "active": sum(1 for s in statuses if s.pid is not None),
            "clean": sum(1 for s in statuses if s.git_status == "clean"),
            "dirty": sum(1 for s in statuses if s.git_status == "dirty"),
            "alerts": sum(len(s.alerts) for s in statuses),
        }
        return {
            "summary": summary,
            "statuses": [s.to_dict() for s in statuses],
            "events": [e.to_dict() for e in events[-20:]],
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def api_events(self) -> Dict[str, Any]:
        return {"events": [e.to_dict() for e in self.dashboard._get_recent_events()]}

    def api_dispatch(self, body: Any) -> Tuple[Dict[str, Any], int]:
        from .dispatch import dispatch_workstream

        if not isinstance(body, dict):
            return {"ok": False, "code": 2, "message": "JSON object body required"}, 400
        try:
            workstream = int(body.get("workstream"))
        except (TypeError, ValueError):
            return {"ok": False, "code": 2, "message": "'workstream' (int) is required"}, 400
        subagent = str(body.get("subagent") or "").strip()
        if not subagent:
            return {"ok": False, "code": 2, "message": "'subagent' (str) is required"}, 400
        try:
            issue = int(body.get("issue") or 0)
            wait = bool(body.get("wait"))
        except (TypeError, ValueError):
            return {"ok": False, "code": 2, "message": "'issue' must be an int"}, 400
        prompt = str(body.get("prompt") or "") or None
        agent = str(body.get("agent") or "") or None

        result = dispatch_workstream(
            self.manager,
            workstream,
            subagent,
            issue=issue,
            prompt=prompt,
            agent=agent,
            wait=wait,
        )
        payload = {
            "ok": result.code == 0,
            "code": result.code,
            "message": result.message,
            "warnings": result.warnings,
        }
        if result.code == 0:
            status = 200
        elif result.code == 5:
            status = 404
        else:
            status = 500
        return payload, status

    # -- static files -------------------------------------------------------

    def serve_static(self, handler: BaseHTTPRequestHandler, raw_path: str) -> None:
        if self.web_root is None:
            handler.send_json(
                {"error": "web console not found - set WORKSTREAMS_WEB_DIR"}, 404
            )
            return
        rel = urllib.parse.unquote(raw_path).lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = (self.web_root / rel).resolve()
        try:
            target.relative_to(self.web_root.resolve())
        except ValueError:
            handler.send_json({"error": "forbidden"}, 403)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            handler.send_json({"error": f"not found: {raw_path}"}, 404)
            return
        try:
            data = target.read_bytes()
        except OSError as e:
            handler.send_json({"error": f"read failed: {e}"}, 500)
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)

    # -- server plumbing ----------------------------------------------------

    def make_server(self) -> ThreadingHTTPServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "workstreams-web"
            sys_version = ""

            def log_message(self, fmt: str, *args: Any) -> None:
                logger.debug("web: " + fmt, *args)

            def send_json(self, obj: Any, status: int = 200) -> None:
                data = json.dumps(obj).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                path = urllib.parse.urlparse(self.path).path
                try:
                    if path == "/api/config":
                        self.send_json(outer.api_config())
                    elif path == "/api/status":
                        self.send_json(outer.api_status())
                    elif path == "/api/events":
                        self.send_json(outer.api_events())
                    elif path.startswith("/api/"):
                        self.send_json({"error": f"unknown endpoint: {path}"}, 404)
                    else:
                        outer.serve_static(self, path)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                path = urllib.parse.urlparse(self.path).path
                if path != "/api/dispatch":
                    self.send_json({"error": f"unknown endpoint: {path}"}, 404)
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    body = json.loads(raw or b"{}")
                except (ValueError, json.JSONDecodeError):
                    self.send_json({"ok": False, "code": 2, "message": "invalid JSON body"}, 400)
                    return
                try:
                    payload, status = outer.api_dispatch(body)
                    self.send_json(payload, status)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        httpd.daemon_threads = True
        self.httpd = httpd
        return httpd

    def serve_forever(self, open_browser: bool = False) -> None:
        httpd = self.make_server()
        host, port = httpd.server_address[:2]
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        url = f"http://{display_host}:{port}/"
        print(f"Workstreams web console: {url}")
        print(f"  API: {url}api/status, {url}api/config, {url}api/events")
        print(f"  POST {url}api/dispatch")
        if self.web_root is None:
            print("  (static console not found - API only; set WORKSTREAMS_WEB_DIR)")
        if open_browser:
            import webbrowser

            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001 - browser open is best-effort
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down web console...")
        finally:
            httpd.server_close()
