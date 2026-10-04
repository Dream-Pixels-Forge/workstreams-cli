"""Workstreams - visually dispatch coding-agent work to subagents in real
terminal windows and monitor it in one dashboard.

Agent-agnostic: works with Claude Code, Codex, OpenCode, Qwen Code,
MiMoCode, Hermes, Kilo Code, Cline, and any other coding agent you can
run from a shell.

Quick start:
    pip install workstreams-cli
    workstreams init --project myproj --workstreams 3
    workstreams start --cmd "claude"
    workstreams dispatch --workstream 1 --subagent claude-code --issue 42 --prompt "Fix auth"
    workstreams monitor
"""

from .models import (
    WorkstreamConfig,
    WorkstreamsConfig,
    WorkstreamStatus,
    SubagentEvent,
)
from .config import load_config, save_config, config_path_in, find_config_file
from .manager import WorkstreamsManager
from .event_log import EventLog, get_event_log, default_log_dir
from .notifier import Notifier
from .subagent_client import (
    subagent_report,
    subagent_started,
    subagent_progress,
    subagent_completed,
    subagent_failed,
    subagent_error,
    subagent_done,
)
from .multiplexer import MultiplexerBase, TmuxMultiplexer, ZellijMultiplexer, get_multiplexer
from .confidence import (
    ConfidenceRecord,
    ConfidenceSummary,
    get_confidence,
    confidence_records,
    clamp_score,
    extract_score,
)

__version__ = "0.6.4"

__all__ = [
    # models
    "WorkstreamConfig",
    "WorkstreamsConfig",
    "WorkstreamStatus",
    "SubagentEvent",
    # config
    "load_config",
    "save_config",
    "config_path_in",
    "find_config_file",
    # manager
    "WorkstreamsManager",
    # events
    "EventLog",
    "get_event_log",
    "default_log_dir",
    # notifications
    "Notifier",
    # subagent client
    "subagent_report",
    "subagent_started",
    "subagent_progress",
    "subagent_completed",
    "subagent_failed",
    "subagent_error",
    "subagent_done",
    # multiplexers
    "MultiplexerBase",
    "TmuxMultiplexer",
    "ZellijMultiplexer",
    "get_multiplexer",
    # confidence scoring
    "ConfidenceRecord",
    "ConfidenceSummary",
    "get_confidence",
    "confidence_records",
    "clamp_score",
    "extract_score",
]
