"""Data models for workstreams."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional


@dataclass
class WorkstreamConfig:
    """Configuration for a single workstream."""

    id: int
    name: str
    path: str
    branch: str
    command: str
    env: Dict[str, str] = field(default_factory=dict)
    multiplexer: str = "tmux"
    layout: str = "even-horizontal"
    shared_deps: List[str] = field(default_factory=list)
    mode: str = "worktree"  # worktree|branch

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkstreamConfig":
        known = {
            "id", "name", "path", "branch", "command", "env",
            "multiplexer", "layout", "shared_deps", "mode",
        }
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class WorkstreamsConfig:
    """Project-level configuration."""

    project: str
    multiplexer: str = "default"  # "default" = auto-detect platform best
    layout: str = "even-horizontal"
    base_branch: str = "main"
    mode: str = "worktree"  # worktree|branch
    workstreams: List[WorkstreamConfig] = field(default_factory=list)
    shared_deps: List[str] = field(default_factory=list)
    base_path: str = "."
    agent: str = "auto"  # auto|claude|codex|opencode|qwen|generic

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkstreamsConfig":
        known = {
            "project", "multiplexer", "layout", "base_branch", "mode",
            "shared_deps", "base_path", "agent",
        }
        workstreams = [
            WorkstreamConfig.from_dict(ws) for ws in data.get("workstreams", [])
        ]
        base = {k: v for k, v in data.items() if k in known and k != "workstreams"}
        base["workstreams"] = workstreams
        return cls(**base)

    def workstream(self, ws_id: int) -> Optional[WorkstreamConfig]:
        for ws in self.workstreams:
            if ws.id == ws_id:
                return ws
        return None


@dataclass
class WorkstreamStatus:
    """Real-time status of a workstream."""

    id: int
    name: str
    branch: str
    path: str
    git_status: str = "unknown"
    last_commit: str = ""
    last_activity: str = ""
    pid: Optional[int] = None
    command: str = ""
    pane: Optional[str] = None
    log_tail: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubagentEvent:
    """Event from a subagent (or any external process)."""

    workstream_id: int
    subagent: str
    issue: int
    event_type: str  # started, progress, completed, failed, error, done
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentEvent":
        return cls(
            workstream_id=data.get("workstream_id", 0),
            subagent=data.get("subagent", "unknown"),
            issue=data.get("issue", 0),
            event_type=data.get("event_type", "progress"),
            message=data.get("message", ""),
            timestamp=data.get("timestamp", datetime.now(UTC).isoformat()),
            data=data.get("data", {}) or {},
        )
