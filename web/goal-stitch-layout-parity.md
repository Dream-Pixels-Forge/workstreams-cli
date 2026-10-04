## Goal: Rework web console layout to match the Stitch concept

### Objective
Restyle and restructure the `web/` frontend so all 4 screens visually and structurally match the Google Stitch concept "Workstreams Agent Dashboard", without touching the backend or the real-data API wiring.

### Context
The real-data wiring (commit `234ba77`) works functionally, but the UI does not match the Stitch concept it was supposed to implement — layout is a mess: soft rounded generic-dashboard look instead of the concept's dense, brutalist TUI aesthetic, wrong shell geometry (96px icon rail vs spec'd 220px rail + 56px top bar), no inspector dock / activity rail structure, pill badges instead of square telemetry chips.

Reference material (fetched 2026-10-04 into `web/stitch-concept/`):
- `monitor.png`, `workstreams.png`, `events.png`, `settings.png` — concept screenshots (Google Stitch project `projects/18260495634110963971`)
- `workstreams.html`, `events.html`, `settings.html` — Stitch-generated concept HTML
- `spec-frontend-implementation.md` — "Workstreams Architecture & Frontend Implementation Specification" (shell geometry, screen-by-screen component breakdown)
- Design system: `dev-notes/DESIGN.md` + designMd "Workstreams Terminal Matrix" (0px radius, 1px `#2A333E`/`#414E5E` structural borders, surface ladder `#101317/#171C22/#1D242C`, phosphor lime `#B8FF47`, Space Mono labels/headlines, Hanken Grotesk body, square ■/▲ state glyphs)

**Stated assumptions:**
- Monitor concept HTML was not retrievable (download returned the spec doc); its reference is `monitor.png` + the spec section "Screen 1: Project Monitor".
- Events targets **Mode B "Lines"** (the PCB-trace bus shown in `events.png`). Circle/3D-View modes are out of scope.

### Deliverables
- [x] `web/stitch-concept/` — reference pack present (screenshots + concept HTML + spec); already fetched, verify intact
- [x] `web/theme.css` — tokens reworked to the Terminal Matrix design system (0px radius default, surface/border ladder, state colors `started/progress/completed/failed/warning`, Space Mono + Hanken Grotesk type scale, spacing scale)
- [x] `web/index.html` — shell rebuilt per spec: **220px left rail** (wordmark + `Monitor/Events/Workstreams/Settings` nav + `Docs` footer) and **56px top utility bar** (repo selector, `● LIVE` pill + poll switcher, bell badge, avatar)
- [x] `web/screens/monitor.html` + `app.js` renderer — metric ribbon, workstreams data table (focused-row green border), Inspector dock with tabs (`Overview / Terminal Output / Git Diff / Worker Log`), right-side **340px** activity rail (`Subagent activity` + `Recent alerts`)
- [x] `web/screens/workstreams.html` + renderer — header ribbon, 2×2 subagent fleet cards (telemetry banner, sparklines, `Force Recycle` etc.), Dispatch Timeline & Conflict Radar panel, Inter-Agent IPC Comets panel
- [x] `web/screens/events.html` + renderer — mode switcher (`Circle/Lines/3D View`, Lines active), topology canvas region, signal control + commit trace panels, streaming telemetry log rows
- [x] `web/screens/settings.html` + renderer — numbered sections `1) LLM Model Routing` (role cards, budget sentinel, providers/secrets), `2) Git Worktree & Filesystem Sandbox Patches` (form grid), `3) Daemon & IPC Comets`
- [x] `web/style.css` — rebuilt from `theme.css` via `npx --yes @tailwindcss/cli@4.3.3 -i web/theme.css -o web/style.css --minify`
- [x] Real-data wiring preserved: all rendering still driven by `/api/config`, `/api/status`, `/api/events`; dispatch form still POSTs `/api/dispatch`

### Definition of Done
- [x] `grep -r "rounded-" web/index.html web/screens/` → zero matches (0px radius rule)
- [x] Computed styles: left rail width = 220px, top bar height = 56px
- [x] Every hex color in `web/theme.css` is a member of the designMd token palette (scripted check, zero extras)
- [x] Each screen contains all required regions listed in Deliverables, verified by DOM inspection against its concept screenshot
- [x] `PYTHONPATH=src python3 -m pytest tests/ -q` → 135 passed, 1 skipped (backend untouched)
- [x] `node --check web/app.js` → clean; Tailwind build succeeds
- [x] Browser check on all 4 screens: zero console errors, no horizontal overflow, header text contrast ≥4.5:1
- [x] UI dispatch round-trip still works: form submit → event appears → `worker.log` DISPATCH line written
- [x] Lighthouse (snapshot) Accessibility ≥ 95

### Verification Steps
1. `grep -rn "rounded-" web/index.html web/screens/ ; grep -oE "#[0-9a-fA-F]{6}" web/theme.css | sort -u` — first empty, second ⊆ palette from `dev-notes/DESIGN.md`
2. `PYTHONPATH=src python3 -m pytest tests/ -q && node --check web/app.js && npx --yes @tailwindcss/cli@4.3.3 -i web/theme.css -o web/style.css --minify`
3. Serve a temp project (`PYTHONPATH=src python3 -m workstreams.cli web --port 8899` in `/tmp/opencode/stitch-parity`), open all 4 screens, capture screenshots, compare side-by-side with `web/stitch-concept/*.png` region-by-region; check `document.querySelector('aside').getBoundingClientRect().width === 220` and header height 56
4. Submit a dispatch from the Workstreams screen → confirm event + `worker.log` line; check browser console = 0 messages
5. Lighthouse snapshot audit → record Accessibility/Best-Practices/SEO scores
6. Output the Goal Completion Check (goal-writer checklist) as final report; then run the `goal-met` audit before claiming done

### Anti-Drift Rules
- Stay within scope of Objective: layout/visual rework of `web/` only.
- Do not modify backend (`dashboard.py`, `cli.py`, `dispatch.py`) or API response shapes.
- Do not reintroduce mock data; if a concept region lacks backing data, render from available API data or omit it and report the omission — never fabricate.
- Do not build Events Circle/3D modes, Three.js/astrolabe visuals, or new routes — new goal.
- Leave legacy `web/monitor.html` and `web/components/header.js` untouched.
- Do not commit or push without explicit user request.
- If blocked or information is missing, report it — do not improvise around it.

### Estimated Effort
Large — shell + 4 screen restructures + token rework + side-by-side parity verification; roughly 1–2 sittings.
