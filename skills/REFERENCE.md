# Workstreams Reference Documentation

## API Reference

### workstreams init
```bash
workstreams init [OPTIONS]

Options:
  --project NAME          Project name (default: directory name)
  --workstreams N         Number of workstreams to create (default: 4)
  --multiplexer TYPE      tmux|zellij|nami|lmux|wmux|herdr (default: tmux)
  --layout LAYOUT         even-horizontal|even-vertical|main-horizontal|tiled
  --base-branch BRANCH    Base branch (default: main)
  --mode MODE             worktree|branch (default: worktree)
  --agent TYPE            auto|claude|codex|opencode|qwen|generic
  --force                 Overwrite existing configuration
  --no-worktrees          Skip git worktree creation
  --json                  Emit JSON output
```

### workstreams start
```bash
workstreams start [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Start a single workstream by ID
  --cmd CMD               Override the command sent to each pane
  --multiplexer TYPE      tmux|zellij|nami|lmux|wmux|herdr
  --layout LAYOUT         even-horizontal|even-vertical|main-horizontal|tiled
  --json                  Emit JSON output
```

### workstreams status
```bash
workstreams status [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Show one workstream
  --live                  Watch mode (same as monitor)
  --once                  Single frame, exit
  --json                  Emit JSON output
```

### workstreams dispatch
```bash
workstreams dispatch [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Target workstream (required)
  --subagent IDENT        Subagent identifier: claude-code, codex, opencode,
                          qwen-code, mimocode, hermes, kilo-code, cline, ...
  --issue NUM             GitHub issue number (default: 0)
  --prompt TEXT           Prompt / task description sent to the pane
  --agent CMD             Agent binary to invoke (e.g. 'claude', 'codex')
  --wait                  Block until subagent reports done/failed
  --multiplexer TYPE      tmux|zellij|nami|lmux|wmux|herdr
  --json                  Emit JSON output
```

### workstreams work
```bash
workstreams work [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Target workstream (required)
  --agent CMD             Agent command (claude, codex, opencode, qwen, cline, ...)
  --task TEXT             Task / prompt for the agent
  --subagent IDENT        Identifier used in the event log (default: agent)
  --issue NUM             GitHub issue number
  --wait                  Block until terminal event
  --multiplexer TYPE      tmux|zellij|nami|lmux|wmux|herdr
  --json                  Emit JSON output
```

### workstreams events
```bash
workstreams events [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Filter by workstream
  --since MINUTES         Minutes back (default: 10)
  --type TYPE             started|progress|completed|failed|error|done
  --subagent IDENT        Filter by subagent name
  --limit N               Max events to return (default: 50)
  --clear                 Clear the event log
  --json                  Emit JSON output
```

### workstreams event
```bash
workstreams event EVENT_TYPE [OPTIONS]

Arguments:
  EVENT_TYPE              started|progress|completed|failed|error|done

Options:
  --project NAME          Project name (required)
  --workstream ID         Workstream ID (default: 0)
  --subagent IDENT        Subagent identifier (required)
  --issue NUM             GitHub issue number
  --message TEXT          Message
  --data JSON             JSON object of extra data
  --json                  Emit JSON output
```

### workstreams notify
```bash
workstreams notify [OPTIONS]

Options:
  --project NAME          Project name
  --title TEXT            Notification title (required)
  --message TEXT          Notification message (required)
  --urgency LEVEL         low|normal|critical (default: normal)
  --json                  Emit JSON output
```

### workstreams assign
```bash
workstreams assign [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Target workstream (required)
  --issue NUM             GitHub issue number (repeatable)
  --json                  Emit JSON output
```

### workstreams sync
```bash
workstreams sync [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Target workstream (default: all)
  --rebase                Use rebase instead of merge
  --json                  Emit JSON output
```

### workstreams pr
```bash
workstreams pr [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Source workstream (required)
  --title TEXT            PR title (required)
  --body TEXT             PR body
  --base BRANCH           Target branch (default: config's base_branch)
  --draft                 Create draft PR
  --json                  Emit JSON output
```

### workstreams merge
```bash
workstreams merge [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Workstream to merge (required)
  --method METHOD         merge|squash|rebase (default: squash)
  --delete-branch         Delete branch after merge
  --auto                  Auto-merge when CI passes
  --json                  Emit JSON output
```

### workstreams workstream add
```bash
workstreams workstream add [OPTIONS]

Options:
  --project NAME          Project name
  --name NAME             Workstream name (required)
  --branch BRANCH         Git branch (required)
  --path PATH             Worktree path (default: worktrees/<name>)
  --command CMD           Default command for this pane
  --json                  Emit JSON output
```

### workstreams workstream remove
```bash
workstreams workstream remove [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Workstream to remove (required)
  --force                 Delete directory + worktree
  --json                  Emit JSON output
```

### workstreams workstream cleanup
```bash
workstreams workstream cleanup [OPTIONS]

Options:
  --project NAME          Project name
  --workstream ID         Clean specific workstream
  --all                   Clean all workstreams
  --force                 Force cleanup without confirmation
  --json                  Emit JSON output
```

### workstreams logs / tail / run / monitor / attach
```bash
workstreams logs --workstream ID [--follow] [--lines N]
workstreams tail [--workstream ID] [--lines N]
workstreams run --workstream ID --cmd COMMAND
workstreams monitor [--refresh N] [--once]
workstreams attach [--session NAME] [--multiplexer TYPE]
```

## Data Structures

### WorkstreamConfig
```python
@dataclass
class WorkstreamConfig:
    id: int
    name: str
    path: str
    branch: str
    command: str
    env: dict[str, str]
    multiplexer: str
    layout: str
    shared_deps: list[str]
    mode: str  # worktree|branch
```

### WorkstreamStatus
```python
@dataclass
class WorkstreamStatus:
    id: int
    name: str
    branch: str
    path: str
    git_status: str  # clean|dirty|unknown
    last_commit: str
    last_activity: str
    pid: int | None
    command: str
    pane: str | None
    log_tail: list[str]
    alerts: list[str]
```

### WorkstreamsConfig
```python
@dataclass
class WorkstreamsConfig:
    project: str
    multiplexer: str
    layout: str
    base_branch: str
    mode: str
    workstreams: list[WorkstreamConfig]
    shared_deps: list[str]
    base_path: str
    agent: str  # auto|claude|codex|opencode|qwen|generic
```

## Git Operations

### Worktree Operations
```bash
# Create worktree
git worktree add ../project-ws1 ws/backend

# Remove worktree
git worktree remove ../project-ws1

# List worktrees
git worktree list

# Prune stale
git worktree prune
```

### Branch Operations
```bash
# Create branch from base
git checkout -b ws/backend main

# Sync with base
git fetch origin main
git rebase origin/main

# Push
git push origin ws/backend
```

## Multiplexer Commands

### tmux
```bash
# Create session
tmux new-session -d -s project

# Create panes
tmux split-window -h -t project:0
tmux split-window -v -t project:0

# Layouts
tmux select-layout -t project even-horizontal
tmux select-layout -t project even-vertical
tmux select-layout -t project main-horizontal
tmux select-layout -t project tiled

# Send command to pane
tmux send-keys -t project:0.0 "npm run dev" Enter

# Attach
tmux attach -t project
```

### zellij
```bash
# Create session
zellij attach project --create

# New tab
zellij action new-tab

# New pane
zellij action new-pane

# Layout
zellij action toggle-floating-panes
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| WORKSTREAMS_PROJECT | Project name | - |
| WORKSTREAMS_MULTIPLEXER | Multiplexer type | tmux |
| WORKSTREAMS_LAYOUT | Layout | even-horizontal |
| WORKSTREAMS_BASE_BRANCH | Base branch | main |
| WORKSTREAMS_WORKTREE_MODE | worktree|branch | worktree |
| WORKSTREAMS_SHARED_DEPS | Shared dependencies | - |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Git error |
| 4 | Multiplexer error |
| 5 | Workstream not found |
| 6 | Already running |
| 7 | Dirty working tree |
| 8 | Merge conflict |
| 9 | Permission denied |