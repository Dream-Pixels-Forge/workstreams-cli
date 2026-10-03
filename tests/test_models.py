import sys
sys.path.insert(0, "src")

from workstreams.models import WorkstreamConfig, WorkstreamsConfig

def test_workstream_config_defaults():
    ws = WorkstreamConfig(id=1, name="ws1", path="worktrees/ws1", branch="ws/1", command="")
    assert ws.id == 1
    assert ws.name == "ws1"
    assert ws.branch == "ws/1"

def test_config_serializes():
    cfg = WorkstreamsConfig(project="demo", workstreams=[WorkstreamConfig(id=1, name="ws1", path="p", branch="b", command="")])
    d = cfg.to_dict()
    assert d["project"] == "demo"
    assert d["workstreams"][0]["id"] == 1
