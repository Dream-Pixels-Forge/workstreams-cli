# Pipeline Progress

## Current State
- Project: workstreams-cli
- Started: 2026-10-03
- Current Phase: 3 (Engineer)
- Status: in-progress

## Phase Completion
- [x] Phase 0: Bootstrap — lmux protocol audit (JSON-over-socket, command surface mapped)
- [x] Phase 1: Brainstorm — native LmuxMultiplexer design (workspace/surface/pane model)
- [x] Phase 2: Governance — SPEC below + verification gates (TDD + end-to-end read-screen proof)
- [ ] Phase 3: Engineer — implementation (this plan)

## Decisions Made
- Native `LmuxMultiplexer` speaking lmux's JSON protocol — NOT a tmux-dialect wrapper.
- Track workstream→surface ID map in shared JSONL log so re-runs stay deterministic.
- Daemon auto-start: `lmux daemon` when socket is missing, with a `WORKSTREAMS_LMUX_NO_DAEMON` escape hatch.
- `read-screen` per surface is the "real proof" mechanism (equivalent of tmux capture-pane).
- Auto-detect: `_installed("lmux")` will now detect the native dialect (`workspace.create` + `surface.send_text` in help) and return True, so the platform default on Linux can pick lmux when it's genuinely usable.

## Blockers
- None. Daemon verified responding on `/run/user/1000/lmux.sock`.
