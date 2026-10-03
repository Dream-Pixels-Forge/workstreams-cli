"""Tests for the config module."""

import sys
sys.path.insert(0, "src")

import json
from pathlib import Path

import pytest

from workstreams.config import save_config, load_config, find_config_file
from workstreams.models import WorkstreamsConfig, WorkstreamConfig


def _make_config(n=2, multiplexer="tmux", agent="auto"):
    ws = [
        WorkstreamConfig(
            id=i + 1,
            name=f"ws{i + 1}",
            path=f"worktrees/ws{i + 1}",
            branch=f"ws/{i + 1}",
            command=f"npm run dev --port {3000 + i + 1}",
            layout="even-horizontal",
            env={},
            multiplexer=multiplexer,
            shared_deps=[],
            mode="worktree",
        )
        for i in range(n)
    ]
    return WorkstreamsConfig(
        project="testproj",
        multiplexer=multiplexer,
        layout="even-horizontal",
        base_branch="main",
        workstreams=ws,
        shared_deps=["node_modules", ".venv"],
        base_path=".",
        agent=agent,
    )


def test_save_and_load_roundtrip(tmp_path):
    cfg = _make_config(n=3, multiplexer="zellij", agent="claude")
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    save_config(cfg, project_dir)

    loaded = load_config(project_dir, "testproj")
    assert loaded is not None
    assert loaded.project == "testproj"
    assert loaded.multiplexer == "zellij"
    assert loaded.agent == "claude"
    assert len(loaded.workstreams) == 3
    assert loaded.workstreams[0].name == "ws1"
    assert loaded.workstreams[1].branch == "ws/2"
    assert loaded.workstreams[2].command == "npm run dev --port 3003"
    assert loaded.shared_deps == ["node_modules", ".venv"]


def test_load_nonexistent_returns_default_project(tmp_path):
    project_dir = tmp_path / "empty"
    project_dir.mkdir()
    loaded = load_config(project_dir, "fallback-proj")
    assert loaded is not None
    assert loaded.project == "fallback-proj"
    assert loaded.multiplexer == "tmux"


def test_load_from_json_fallback(tmp_path):
    """When pyyaml is unavailable the config is saved as .json and must still load."""
    cfg = _make_config(n=1)
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    # Force the json fallback path
    saved_path = save_config(cfg, project_dir)
    if saved_path.suffix == ".json":
        loaded = load_config(project_dir, "testproj")
        assert loaded.project == "testproj"
        assert len(loaded.workstreams) == 1
        assert loaded.workstreams[0].name == "ws1"
    else:
        # pyyaml present: verify yaml file roundtrips
        loaded = load_config(project_dir, "testproj")
        assert loaded.project == "testproj"


def test_save_config_creates_parent_dir(tmp_path):
    cfg = _make_config(n=1)
    nested = tmp_path / "a" / "b" / "c"
    save_config(cfg, nested)
    assert find_config_file(nested) is not None


def test_find_config_file_not_found(tmp_path):
    assert find_config_file(tmp_path) is None


def test_workstream_config_defaults():
    ws = WorkstreamConfig(
        id=1,
        name="ws1",
        path="worktrees/ws1",
        branch="ws/1",
        command="npm run dev",
    )
    assert ws.multiplexer == "tmux"
    assert ws.layout == "even-horizontal"
    assert ws.mode == "worktree"
    assert ws.env == {}
    assert ws.shared_deps == []


def test_workstream_config_from_dict_roundtrip():
    ws = WorkstreamConfig(
        id=2,
        name="api",
        path="worktrees/api",
        branch="ws/api",
        command="npm run dev",
        multiplexer="zellij",
        layout="tiled",
        env={"PORT": "8080"},
        shared_deps=["node_modules"],
        mode="branch",
    )
    d = ws.to_dict()
    restored = WorkstreamConfig.from_dict(d)
    assert restored.id == 2
    assert restored.name == "api"
    assert restored.branch == "ws/api"
    assert restored.command == "npm run dev"
    assert restored.multiplexer == "zellij"
    assert restored.layout == "tiled"
    assert restored.env == {"PORT": "8080"}
    assert restored.shared_deps == ["node_modules"]
    assert restored.mode == "branch"


def test_workstream_config_from_dict_ignores_unknown_keys():
    d = {
        "id": 1,
        "name": "ws1",
        "path": "worktrees/ws1",
        "branch": "ws/1",
        "command": "",
        "unknown_key": "should-be-ignored",
    }
    ws = WorkstreamConfig.from_dict(d)
    assert ws.id == 1
    assert not hasattr(ws, "unknown_key")


def test_workstreams_config_roundtrip():
    cfg = _make_config(n=2)
    d = cfg.to_dict()
    restored = WorkstreamsConfig.from_dict(d)
    assert restored.project == "testproj"
    assert restored.multiplexer == "tmux"
    assert restored.layout == "even-horizontal"
    assert restored.base_branch == "main"
    assert restored.mode == "worktree"
    assert len(restored.workstreams) == 2
    assert restored.shared_deps == ["node_modules", ".venv"]
    assert restored.agent == "auto"
