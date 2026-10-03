# workstreams

Visually dispatch coding-agent work to subagents in real terminal windows and monitor it in one dashboard — for any coding agent (Claude Code, Codex, OpenCode, Qwen Code, Hermes, Cline, and more).

`workstreams` runs your coding agents in parallel across terminal multiplexers (tmux, zellij, tmuxp, zed, neovim terminals) with:

- **Live monitoring dashboard** — real-time TUI showing the status of every workstream
- **Cross-process subagent event logging** — agents report progress back into a shared event stream
- **Cross-terminal notifications** — get pinged when a workstream needs attention or finishes
- **Git worktree isolation** — each workstream gets its own branch and working directory
- **Agent-agnostic** — works with any agent you can launch from a shell

## Installation

```bash
pip install workstreams
# with optional YAML config support
pip install workstreams[yaml]
```

## Quick Start

```bash
# Initialize 3 parallel workstreams for a project
workstreams init --project myproj --workstreams 3

# Start all workstreams (tmux panes, one agent each)
workstreams start --multiplexer tmux --cmd "claude"

# Dispatch a subagent task to a workstream
workstreams dispatch --workstream 1 --subagent claude-code --issue 42 --prompt "Fix auth"

# Watch everything in one dashboard
workstreams monitor
```

See [skills/SKILL.md](skills/SKILL.md) and [skills/EXAMPLES.md](skills/EXAMPLES.md) for the full command reference and real-world examples.

## Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize workstreams for a project |
| `start` | Launch workstreams across a multiplexer |
| `attach` | Attach to a specific workstream |
| `status` | Check status of all workstreams |
| `dispatch` | Send a task to a workstream's agent |
| `work` / `run` | Run commands inside a workstream |
| `logs` / `events` | View subagent activity across workstreams |
| `monitor` | Live TUI dashboard |
| `notify` / `sync` | Cross-terminal notifications and state sync |
| `workstream add\|remove\|cleanup` | Manage workstreams |

## License

MIT
