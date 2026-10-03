"""File-based event log for cross-process subagent communication.

Events live in ~/.workstreams/<project>/events.jsonl. Multiple processes
(main agent, dispatched subagents in tmux panes, external scripts) append
concurrently, so writes use O_APPEND (atomic on POSIX for small writes)
plus an optional lock file for large payloads.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import SubagentEvent


def default_log_dir(project: str) -> Path:
    override = os.environ.get("WORKSTREAMS_DATA_DIR")
    if override:
        return Path(override) / project
    return Path.home() / ".workstreams" / project


class EventLog:
    """Append-only JSONL event log shared across processes."""

    def __init__(self, project: str, log_dir: Optional[Path] = None):
        self.project = project
        self.log_dir = Path(log_dir) if log_dir else default_log_dir(project)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.log_dir / "events.jsonl"
        self.lock_file = self.log_dir / "events.lock"

    # -- locking ---------------------------------------------------------

    def _acquire_lock(self, timeout: float = 2.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return True
            except FileExistsError:
                # If the lock is older than 10s, consider it stale and steal it
                try:
                    age = time.time() - self.lock_file.stat().st_mtime
                    if age > 10:
                        self.lock_file.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(0.01)
        return False

    def _release_lock(self) -> None:
        try:
            self.lock_file.unlink()
        except OSError:
            pass

    # -- append / read ----------------------------------------------------

    def append(self, event: SubagentEvent) -> bool:
        """Append an event. Returns True on success."""
        line = json.dumps(event.to_dict()) + "\n"
        acquired = self._acquire_lock()
        try:
            # O_APPEND makes concurrent small writes atomic on POSIX;
            # the lock additionally guards against torn writes of large lines.
            fd = os.open(str(self.events_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except OSError:
            return False
        finally:
            if acquired:
                self._release_lock()

    def get_events(
        self,
        workstream_id: Optional[int] = None,
        since: Optional[datetime] = None,
        event_type: Optional[str] = None,
        subagent: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SubagentEvent]:
        """Read filtered events (newest last)."""
        if not self.events_file.exists():
            return []

        events: List[SubagentEvent] = []
        with open(self.events_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = SubagentEvent.from_dict(data)
                except Exception:
                    continue
                if workstream_id is not None and event.workstream_id != workstream_id:
                    continue
                if subagent is not None and event.subagent != subagent:
                    continue
                if event_type is not None and event.event_type != event_type:
                    continue
                if since is not None:
                    try:
                        ts = datetime.fromisoformat(event.timestamp)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=UTC)
                        if ts < since:
                            continue
                    except ValueError:
                        pass
                events.append(event)
        if limit is not None:
            events = events[-limit:]
        return events

    def tail(self, lines: int = 20) -> List[SubagentEvent]:
        """Return the last N events without scanning old lines."""
        if not self.events_file.exists():
            return []
        all_events: List[SubagentEvent] = []
        with open(self.events_file, "r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # read up to ~256KB from the end
            chunk_start = max(0, size - 256 * 1024)
            f.seek(chunk_start)
            data = f.read()
            for line in data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    all_events.append(SubagentEvent.from_dict(json.loads(line)))
                except Exception:
                    continue
        return all_events[-lines:]

    def stats(self) -> Dict[str, Any]:
        """Quick counters for the dashboard summary bar."""
        events = self.get_events()
        counts: Dict[str, int] = {}
        for e in events:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        return {"total": len(events), "by_type": counts}

    def clear(self) -> None:
        if self.events_file.exists():
            self.events_file.unlink()


_log_cache: Dict[str, EventLog] = {}


def get_event_log(project: str) -> EventLog:
    """Get (or create) a cached EventLog for the project."""
    if project not in _log_cache:
        _log_cache[project] = EventLog(project)
    return _log_cache[project]
