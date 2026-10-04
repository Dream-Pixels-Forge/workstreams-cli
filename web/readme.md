# Workstreams Web Console

Static console for the `workstreams` CLI, served by `dashboard.py` over HTTP and wired to live project data.

## Usage

```bash
workstreams web                 # 127.0.0.1:8765
workstreams web --port 9000 --open
```

From source: `PYTHONPATH=src python3 -m workstreams.cli web`

Web root resolution (`resolve_web_root`): explicit arg → `WORKSTREAMS_WEB_DIR` → repo `<repo>/web` → `cwd/web`.

## Structure

```
web/
├── index.html      ← Shell: header, nav, screen fetch, app.js loader
├── app.js          ← All logic: API client, renderers, dispatch form
├── theme.css       ← Tailwind v4 source (@import/@theme/@source) — edit this
├── style.css       ← BUILT stylesheet — regenerate, don't hand-edit
├── screens/        ← Partial HTML injected into #main-content
│   ├── monitor.html
│   ├── events.html
│   ├── workstreams.html
│   └── settings.html
├── components/     ← Legacy Stitch header.js (unused by the console)
└── monitor.html    ← Legacy standalone mock page (stale, kept as-is)
```

`app.js` exposes `window.WorkstreamsWeb = { onScreenLoaded, start, refresh, state }`.
The inline script in `index.html` fetches `screens/<nav>.html` (relative, checks
`response.ok`) and calls `onScreenLoaded(nav)` after injection. Polling: `/api/config`
+ `/api/status` every 2s, "Updated" tick every 1s.

## HTTP API (dashboard.py)

| Route | Method | Returns |
|---|---|---|
| `/` and static files | GET | `index.html`, `style.css`, `app.js`, `screens/*` (traversal → 403) |
| `/api/config` | GET | `.workstreams.yaml` as JSON (project, multiplexer, workstreams) |
| `/api/status` | GET | `{summary, statuses, last-events}` from `worktrees/*/logs` |
| `/api/events` | GET | Recent subagent events |
| `/api/dispatch` | POST | `{ok, code, message, warnings}` |

Dispatch codes: `0` ok, `2` invalid body (400), `4` mux failure (warning, not error),
`5` unknown workstream (404), `500` unexpected. Warnings (e.g. `pane send returned
False` when no multiplexer session is attached) do not fail the request; the event and
`worker.log` DISPATCH line are still written.

## Building the CSS

`style.css` is generated from `theme.css` with Tailwind v4:

```bash
npx --yes @tailwindcss/cli@4.3.3 -i web/theme.css -o web/style.css --minify
```

Rebuild after adding/changing any Tailwind class in `index.html`, `app.js`, or
`screens/*.html` (classes are detected via `@source` globs). Check `node --check web/app.js`
after JS edits.

## Design Tokens (Stitch: "Workstreams Agent Dashboard")

- Color mode: dark; primary accent `#b8ff47` (electric-lime)
- Surface `#111418`, surface-border `#1c2126`, surface-container `#1a1f24`
- Font: Space Mono (Google Fonts, system-mono fallback), roundness 8px

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/test_web_dashboard.py tests/test_cli_dispatch.py -q
```
