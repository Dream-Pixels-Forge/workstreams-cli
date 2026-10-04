## Goal: Wire Workstreams Web Console to Real Data from workstreams-cli

### Objective
Replace all mock data in the workstreams web console with real data from the workstreams-cli project, wiring the UI to the actual data models (WorkstreamConfig, WorkstreamStatus, SubagentEvent) and the .workstreams.yaml configuration. The console should dynamically render from real workstream data instead of static mock data.

### Context
The workstreams-cli project contains real data models in `src/workstreams/models.py`:
- `WorkstreamConfig`: static configuration (id, name, path, branch, command, env)
- `WorkstreamStatus`: real-time status (id, name, branch, path, git_status, last_commit, last_activity, pid, command, pane, log_tail, alerts)
- `SubagentEvent`: events from subagents (workstream_id, subagent, issue, event_type, message, timestamp)

The project also has real configuration in `.workstreams.yaml`:
```yaml
project: myproj
multiplexer: tmux
layout: even-horizontal
base_branch: main
mode: worktree
shared_deps: []
agent: generic
workstreams:
- id: 1
  name: ws1
  path: worktrees/ws1
  branch: ws/1
  command: ''
  env: {}
- id: 2
  name: ws2
  path: worktrees/ws2
  branch: ws/2
  command: ''
  env: {}
```

The web console currently uses mock data and needs to be wired to this real data source. The console has 4 screens (Monitor, Events, Workstreams, Settings) that should all read from the actual workstream data.

### Deliverables
- [x] `web/index.html` — Updated to embed real data from .workstreams.yaml and use real data models
- [x] `web/style.css` — ~~No changes needed~~ **CORRECTION:** was an unbuilt 13-line Tailwind scaffold (inert in browsers, no `.hidden` rule). Rebuilt from new `web/theme.css` via `npx --yes @tailwindcss/cli@4.3.3 -i web/theme.css -o web/style.css --minify`; design tokens unchanged
- [x] `web/app.js` — Completely rewired to fetch/use real data instead of mock `stitchData`
- [x] `web/screens/monitor.html` — Real workstream status data, git states, PIDs, log tails, alerts
- [x] `web/screens/events.html` — Real subagent events from the event log, real telemetry data
- [x] `web/screens/workstreams.html` — Real workstream cards with actual agent names, LLMs, paths
- [x] `web/screens/settings.html` — Real config values from .workstreams.yaml
- [x] `tailwind.config.js` — No changes needed (untouched; build uses `@theme` in theme.css, Tailwind v4)
- [x] `readme.md` — Updated to document real data wiring

### Definition of Done
- [x] All deliverable files exist inside `web/` directory
- [x] `web/index.html` renders without console errors and embeds real data (verified in Chrome: zero console messages)
- [x] `web/app.js` successfully loads and processes real data models (WorkstreamConfig, WorkstreamStatus, SubagentEvent)
- [x] Monitor screen displays real workstream status (git_status, pids, log_tail, alerts from actual data)
- [x] Events screen displays real subagent events (event_type, message, timestamp from actual data)
- [x] Workstreams screen displays real workstream cards (name, path, branch, LLM role from actual data)
- [x] Settings screen displays real config values (project, multiplexer, layout, mode, agent from .workstreams.yaml)
- [x] No mock data remaining in any of the screen files (all data sourced from real workstreams-cli data models; grep for stitchData/mock/lorem/fake/radial/orbital → empty)
- [ ] `npx eslint web/` — **N/A: no ESLint config exists in the repo** (eslint is not a dependency; no eslint.config.* / .eslintrc*). JS verified with `node --check web/app.js` instead
- [x] Dashboard is functional and accessible (Lighthouse navigation audit: Accessibility 100, Best Practices 100, SEO 100; UI dispatch round-trip verified)

### Anti-Drift Rules
- Stay within scope of wiring console to real workstreams-cli data
- Do not modify data models or project configuration files
- Do not implement features beyond data wiring
- All UI updates must use real data model fields, not hardcoded values
- If real data is unavailable, report blocker and do not use hardcoded mock data as fallback

### Verification Steps
1. Open `web/index.html` in a browser — verify it renders without console errors and data is populated from real sources
2. Check that Monitor screen shows real workstream status data (verify by examining generated HTML for actual PID values, git statuses, etc.)
3. Check that Events screen shows real subagent events (verify event_type, message, timestamp fields are populated from real data)
4. Check that Workstreams screen shows real workstream card data (verify name, path, branch fields are from actual .workstreams.yaml)
5. Check that Settings screen shows real config values (verify project, multiplexer, layout, mode, agent fields match .workstreams.yaml)
6. Run `npx eslint web/` — zero errors
7. Verify no hardcoded mock data patterns remain in the code (search for patterns that were in the original mock data)

### Anti-Drift Enforcement
- Pipeline orchestrator must track this as a distinct goal from the original implementation
- All phase transitions must be recorded in `dev-notes/PROGRESS.md`
- Goal-met audit must verify real data is used, not mock data
- Any assumptions about data shape must be explicitly stated and verified

### Estimated Effort
High — requires rewriting data flow in app.js and all 4 screen files to use real data models instead of mock data. Estimated 12-16 hours.

### Pipeline Orchestrator Mandatory
This goal **MUST** use the `goal-writer` skill for specification, and the `goal-met` skill for independent audit verification. The pipeline orchestrator enforces that each screen file is updated independently and verified before moving to the next.