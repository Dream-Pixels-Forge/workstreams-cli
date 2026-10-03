# Native lmux Multiplexer — Implementation Plan

> **For Hermes:** Execute task-by-task using strict TDD (test-driven-development skill). No production code without a failing test first.

**Goal:** Make `workstreams` drive lmux natively via its JSON-over-socket protocol (workspace/surface/pane model), so coding agents can dispatch work into real lmux surfaces and verify output via `read-screen` — first-class lmux support, not a tmux-dialect hack.

**Architecture:** A new `LmuxMultiplexer` class implements the `MultiplexerBase` interface by speaking lmux's native wire protocol (JSON command/args over `/run/user/1000/lmux.sock`). A thin socket client handles connect/send/receive. Workstream→surface ID mapping is persisted in the shared JSONL event log for cross-process determinism. The dialect detector in `multiplexer/__init__.py` is extended to recognize the native lmux dialect so auto-detect can select it.

**Tech Stack:** Python 3 stdlib only (`socket`, `json`, `subprocess`, `shutil`, `os`). No new dependencies.

---

## lmux wire protocol (verified from `lmux help` + strace)

- Daemon: `lmux daemon` listens on `/run/user/1000/lmux.sock` (env `XDG_RUNTIME_DIR`).
- Client op: connect → write single JSON `{"cmd":"<name>","args":{...}}` → read JSON reply → close.
- IDs are global integers: `workspace` ≈ session, `surface` ≈ tab/window, `pane` ≈ split.
- Commands we use:
  - `workspace.create <title>` → `{"id":N}`
  - `surface.create <ws> <title>` → `{"id":N}`
  - `surface.send_text <text> <surface> [ws]` → ok
  - `surface.send-key <key> <surface> [ws]`
  - `surface.split <h|v> <surface> [ws]`
  - `read-screen [surface] [ws]` / `capture-pane` → pane text
  - `pane.list` / `surface.list` / `workspace.list` / `tree`
  - `workspace.close <id>`, `surface.close <id> [ws]`
  - `ping` → `{"version":...}`
- First call after daemon start has ~5s PTY warm-up latency → use generous timeouts (10s).

## File map
- Create: `src/workstreams/multiplexer/lmux_client.py` (raw JSON socket client)
- Create: `src/workstreams/multiplexer/lmux.py` (LmuxMultiplexer)
- Modify: `src/workstreams/multiplexer/__init__.py` (register lmux, extend dialect detect)
- Modify: `src/workstreams/multiplexer/base.py` (add `ensure_usable` + surface-map hook)
- Create: `tests/test_lmux_client.py`, `tests/test_lmux.py`
- Modify: `tests/test_multiplexer_default.py` (lmux now detectable)

## Verification gates (Phase 2 SPEC)
1. TDD: every new method has a test that failed first.
2. Unit: socket client round-trips against a fake in-memory server.
3. Integration: against the REAL lmux daemon, `start` creates a workspace + N surfaces and `send_command` delivers a marker string; `read-screen` returns the marker (genuine proof, not a no-op).
4. Auto-detect: `_installed("lmux")` returns True on this box (native dialect present).
5. No regressions: full `pytest tests -q` green.

---

### Task 1: lmux JSON socket client
**Objective:** Minimal `LmuxClient` that connects to the socket and round-trips a JSON command.

Files:
- Create: `src/workstreams/multiplexer/lmux_client.py`
- Test: `tests/test_lmux_client.py`

Step 1 — failing test: spin up a fake Unix-socket server in the test that echoes `{"ok":true}` for `ping`, assert `client.cmd("ping")` returns the dict.
Step 2 — run, watch it fail (module missing).
Step 3 — implement `LmuxClient(socket_path).cmd(name, args, timeout)` + `daemon_ensure()`.
Step 4 — green. Step 5 — commit.

### Task 2: LmuxMultiplexer core (workspace + surface create)
**Objective:** `start()` creates one workspace and one surface per workstream; records the ID map.

Files: Modify `lmux.py`, Test `tests/test_lmux.py`
Step 1 — test: with a stubbed `LmuxClient`, `start([ws1, ws2])` issues `workspace.create` once and `surface.create` twice, and stores `self._surface_map = {1: s1, 2: s2}`.
Step 2/3/4/5 — TDD cycle + commit.

### Task 3: send_command + surface map persistence
**Objective:** `send_command(id, cmd)` sends to the recorded surface; map persists to JSONL log.

Step 1 — test: after `start`, `send_command(1, "echo hi")` calls `surface.send_text` with the mapped surface id; the map is written and re-loadable.
Step 2–5.

### Task 4: capture via read-screen (the real proof)
**Objective:** `capture(id, lines)` returns `read-screen` output for that surface.

Step 1 — test: stub client returns pane text; `capture` slices last N lines.
Step 2–5.

### Task 5: attach / is_running / kill / list_windows
**Objective:** Complete the base interface.

`attach` → best-effort `lmux` TUI (print guidance, non-blocking). `is_running` → `workspace.list` non-empty. `kill` → `workspace.close`. `list_windows` → `surface.list`.
Step 1 — test each with stubs. Step 2–5.

### Task 6: register in get_multiplexer + dialect detect
**Objective:** `get_multiplexer("lmux", cfg)` returns `LmuxMultiplexer`; `_installed("lmux")` True when native dialect present.

Step 1 — test: dialect detect returns True for a binary whose help shows `workspace.create` + `surface.send_text`.
Step 2–5. Update `__init__.py` registration and `_PLATFORM_PREFERENCE` docs.

### Task 7: end-to-end against real daemon
**Objective:** Real integration proof (gate 3). Run `workstreams start --multiplexer lmux` in a temp project, dispatch a marker, `read-screen` shows the marker.

This task runs against the live daemon; mark PASS only when the marker string is observed in pane output.

### Task 8: bump 0.6.3, build, install, docs
Update version in `__init__.py`/`pyproject.toml`/`README.md`/`SKILL.md`; add lmux native section; build wheel; pipx install; full test suite.
