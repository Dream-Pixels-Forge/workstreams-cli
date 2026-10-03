"""Configuration loading and saving for workstreams."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .models import WorkstreamConfig, WorkstreamsConfig


def _yaml_load(text: str) -> Optional[Dict[str, Any]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _yaml_dump(data: Dict[str, Any]) -> str:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None  # type: ignore[return-value]
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def config_path_in(base_path: Path) -> Path:
    return base_path / ".workstreams.yaml"


def load_config(
    base_path: Optional[Path] = None,
    project: Optional[str] = None,
) -> WorkstreamsConfig:
    """Load workstreams configuration.

    Resolution order:
    1. <base_path>/.workstreams.yaml (if it exists and matches --project when given)
    2. Environment variables (WORKSTREAMS_PROJECT / _MULTIPLEXER / _LAYOUT / _BASE_BRANCH / _MODE)
    3. Sensible defaults
    """
    base_path = (base_path or Path.cwd()).resolve()
    config_file = config_path_in(base_path)
    # Fall back to the JSON config if YAML is not present (no-pyyaml installs)
    if not config_file.exists():
        json_fallback = config_file.with_suffix(".json")
        if json_fallback.exists():
            config_file = json_fallback
    data: Dict[str, Any] = {}
    if config_file.exists():
        try:
            text = config_file.read_text()
            if config_file.suffix == ".json":
                parsed = json.loads(text)
                data = parsed if isinstance(parsed, dict) else {}
            else:
                parsed = _yaml_load(text)
                if parsed is not None:
                    data = parsed
                else:
                    # Fallback parser for simple YAML (no pyyaml installed)
                    parsed = _simple_yaml_load(text)
                    if parsed is not None:
                        data = parsed
        except (OSError, json.JSONDecodeError):
            data = {}

    workstreams = [
        WorkstreamConfig.from_dict(ws) if isinstance(ws, dict) else ws
        for ws in data.get("workstreams", [])
    ]

    project = project or data.get("project") or os.environ.get("WORKSTREAMS_PROJECT")
    if not project:
        project = base_path.name or "myproject"

    return WorkstreamsConfig(
        project=project,
        multiplexer=data.get("multiplexer") or os.environ.get("WORKSTREAMS_MULTIPLEXER") or "tmux",
        layout=data.get("layout") or os.environ.get("WORKSTREAMS_LAYOUT") or "even-horizontal",
        base_branch=data.get("base_branch") or os.environ.get("WORKSTREAMS_BASE_BRANCH") or "main",
        mode=data.get("mode") or os.environ.get("WORKSTREAMS_WORKTREE_MODE") or "worktree",
        workstreams=workstreams,
        shared_deps=data.get("shared_deps")
        or (
            [d for d in os.environ.get("WORKSTREAMS_SHARED_DEPS", "").split(",") if d]
            if os.environ.get("WORKSTREAMS_SHARED_DEPS")
            else []
        ),
        base_path=str(base_path),
        agent=data.get("agent", "auto"),
    )


def _simple_yaml_load(text: str) -> Optional[Dict[str, Any]]:
    """Very small YAML subset parser: top-level scalars and lists of key: value maps.

    Only used as a fallback when pyyaml is not installed. Supports the shape
    that save_config produces. Not a general YAML parser.
    """
    result: Dict[str, Any] = {}
    current: Optional[Dict[str, Any]] = None
    in_workstreams = False
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.startswith("workstreams:"):
            in_workstreams = True
            result["workstreams"] = []
            continue
        if not line.startswith(" "):
            in_workstreams = False
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if value:
                if value.startswith("[") and value.endswith("]"):
                    inner = value[1:-1].strip()
                    result[key] = [v.strip().strip("'\"") for v in inner.split(",")] if inner else []
                else:
                    result[key] = value.strip("'\"")
            else:
                result[key] = None
            continue

        if in_workstreams:
            # New workstream entry: "- key: value"
            if stripped.startswith("- "):
                if current is not None:
                    result["workstreams"].append(current)
                current = {}
                item = stripped[2:]
                if ":" in item:
                    k, _, v = item.partition(":")
                    current[k.strip()] = _parse_scalar(v.strip())
                else:
                    current.setdefault("name", _parse_scalar(item))
                continue
            # Sub-keys inside a workstream entry
            if current is not None and ":" in stripped:
                k, _, v = stripped.partition(":")
                k, v = k.strip(), v.strip()
                if v:
                    current[k] = _parse_scalar(v)
                else:
                    current[k] = {}
                continue
            # Indented list under a key (shared_deps style)
            if stripped.startswith("- ") and current is not None:
                pass
        # Top-level list value continuation (shared_deps)
        if not line.startswith(" ") is False and False:
            pass
    if current:
        result.setdefault("workstreams", []).append(current)
    # Convert "key:\n  - a\n  - b" style lists that follow a scalar None
    for key, value in list(result.items()):
        if value is None and key != "workstreams":
            # Look ahead: already handled in-line; leave as None
            pass
    return result if result else None


def _parse_scalar(value: str) -> Any:
    if value == "" or value is None:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [v.strip().strip("'\"") for v in inner.split(",")] if inner else []
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def save_config(config: WorkstreamsConfig, base_path: Optional[Path] = None) -> Path:
    """Save configuration to .workstreams.yaml (or .json fallback without pyyaml)."""
    base_path = Path(base_path or config.base_path).resolve()
    base_path.mkdir(parents=True, exist_ok=True)
    config_file = config_path_in(base_path)

    config_dict: Dict[str, Any] = {
        "project": config.project,
        "multiplexer": config.multiplexer,
        "layout": config.layout,
        "base_branch": config.base_branch,
        "mode": config.mode,
        "shared_deps": config.shared_deps,
        "agent": config.agent,
        "workstreams": [
            {
                "id": ws.id,
                "name": ws.name,
                "path": ws.path,
                "branch": ws.branch,
                "command": ws.command,
                "env": ws.env,
            }
            for ws in config.workstreams
        ],
    }

    dumped = _yaml_dump(config_dict)
    if dumped is None:
        config_file.with_suffix(".json").write_text(json.dumps(config_dict, indent=2) + "\n")
        if config_file.exists():
            config_file.unlink()
        return config_file.with_suffix(".json")
    config_file.write_text(dumped)
    return config_file


def find_config_file(base_path: Path) -> Optional[Path]:
    for candidate in (config_path_in(base_path), base_path / ".workstreams.json"):
        if candidate.exists():
            return candidate
    return None
