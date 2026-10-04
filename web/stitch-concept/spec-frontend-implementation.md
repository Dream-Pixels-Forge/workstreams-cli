# Workstreams Architecture & Frontend Implementation Specification
**Target Audience:** Autonomous Coding Agents & Senior Systems Engineers  
**System:** `workstreams` (CLI Subagent & Git Worktree Orchestrator Web Console)  
**Design System:** Workstreams Terminal Matrix (`#111418` dark graphite base, `#b8ff47` electric lime accent, `Space Mono` typography)

---

## 1. Architectural Overview & System Mental Model

`workstreams` coordinates multi-agent autonomous software engineering across isolated git worktrees, tmux multiplexer sessions, and Unix domain socket IPC buses. The web frontend exposes four primary navigation routes and three interchangeable topology display engines under the **Events** view:

```
[workstreams Web Console]
├── 1. Monitor (/monitor) ─────────── Fleet state table, active tmux tail, worker alerts
├── 2. Events (/events) ──────────── Multi-modal agent dispatch & bus topology:
│   ├── Mode A: [Circle] ──────────── Polar quadrant radar & telemetry data rays
│   ├── Mode B: [—o Lines] ────────── Altium/KiCad-grade functional PCB trace bus
│   └── Mode C: [3D View] ─────────── Three.js celestial armillary astrolabe mesh
├── 3. Workstreams (/workstreams) ─── Subagent fleet matrix cards, AST conflict radar
└── 4. Settings (/settings) ───────── LLM router, cgroups sandbox policies, daemon IPC
```

---

## 2. Core Navigation Chrome & Shell

All screens share a rigid persistent shell built on a 12-column grid:
- **Left Navigation Rail (Width: 220px)**:
  - Header: `workstreams` wordmark with green branch glyph.
  - Primary links: `Monitor` (`/monitor`), `Events` (`/events`), `Workstreams` (`/workstreams`), `Settings` (`/settings`).
  - Footer: `Docs` external link with glyph.
- **Top Utility Bar (Height: 56px)**:
  - Repository selector dropdown (e.g. `api-platform` `~/projects/api-platform`).
  - System status pill: `● LIVE` indicator + poll interval switcher (`Updated 2s ago`, dropdown `2s`).
  - Alert notification bell badge (`1`) and user avatar chip.

---

## 3. Screen 1: Project Monitor (`/monitor`)

### Purpose
The command-line command center providing real-time visibility into all dispatched subagents, running processes, git worktree states, and recent stderr alerts.

### Component Breakdown
1. **Summary Metric Ribbons**:
   - `TOTAL WORKSTREAMS` (4)
   - `ACTIVE` (2 - cyan/lime indicator)
   - `CLEAN` (2)
   - `DIRTY` (2 - warning triangle)
   - `ALERTS` (1 - red alert pill)
2. **Workstreams Data Table**:
   - Columns: `ID` (`#01..#04`), `WORKSTREAM / PATH`, `BRANCH`, `WORKER / PID`, `GIT STATE` (`CLEAN` / `DIRTY (3)`), `LAST ACTIVITY`.
   - Row interaction: clicking a row sets it as `FOCUSED` (highlighted green border) and updates the lower inspection panel.
3. **Inspector & PTY Multiplexer Dock (Split Tabs)**:
   - Tabs: `Overview`, `Terminal Output (tmux:0.1)`, `Git Diff (+42 -8)`, `Worker Log`.
   - Real-time auto-scrolling log container displaying raw stdout/stderr with syntax highlights (`[14:32:08] [claude-code] test_refresh_token_rotation PASSED`).
   - Quick action bar: `Checkout worktree locally` (shell copy) and `Kill worker process (PID 4812)`.
4. **Live Subagent Activity Rail (Right Side, 340px)**:
   - Stack of timestamped agent actions: `claude-code`, `codex`, `pytest` with status badges (`PROGRESS`, `STARTED`, `COMPLETED`, `FAILED`).
   - `Recent alerts` expandable accordion displaying stack traces (e.g. `TypeError: Incompatible return value`).

---

## 4. Screen 2: Events & Topology Panel (`/events`)

The Events screen is the orchestrator's central visual differentiator. It contains a top mode switcher:
```html
<div class="flex items-center gap-1 bg-[#191c20] p-1 rounded border border-[#2d3139]">
  <button id="mode-circle" class="tab-btn">[Circle]</button>
  <button id="mode-lines" class="tab-btn">[—o Lines]</button>
  <button id="mode-3d" class="tab-btn active">[3D View]</button>
</div>
```

### Shared Events View Components (Persist Across All 3 Modes)
- **Header Telemetry Bar**: Active orchestrator PID (`PID 4100`), Active Conduits (`4 Channels`, `0 Drops`, `p95: 24ms`), Dispatch Rate (`18.4 pkts/sec`), Event Queue (`0 backlogged`, `1 ALERT`).
- **Telemetry Key & Sync Clock**: Visual legend for packet states (`Task Dispatch`, `Started Signal`, `Diff Stream`, `Test Ack`, `Traceback Alert`).
- **Bottom Diagnostic Strip**:
  - Left Card: Dynamic sub-metric depending on mode (Geodesic Conduit / Polar Quadrants / Eye Diagram).
  - Center Card: Interrupt Vector Table / Pipeline Stages / Sequential Arc telemetry.
  - Right Card: DMA throughput metrics / Bus bandwidth.
  - Full-Width Log Tail: Monospace terminal tailing `tail -f` IPC dispatches with auto-scroll toggles.

---

### Display Mode A: `[Circle]` — Polar Ephemeris & Radar HUD

#### Mathematical & Visual Formulation
- **Central Core**: Concentric circles centered at `(cx, cy)` representing the main orchestrator (`PID 4100`).
- **4 Polar Quadrants**:
  - `QI: FE STREAM` (0° to 90°)
  - `QII: WORKTREE` (90° to 180°)
  - `QIII: TEST VERIF` (180° to 270°)
  - `QIV: CODE GEN` (270° to 360°)
- **Concentric Grid Calibration**: Degree ticks at 5° increments, range rings at 25%, 50%, 75%, 100% radius.
- **Data Rays & Nodes**:
  - Subagents mapped as radial coordinates $(r, \theta)$.
  - Connecting lines drawn as curved circular arcs or straight vector spokes with pulsing dot markers.
  - Data bubbles displaying numeric percentages and operational tags (`[100% OK]`, `[AST SYNC]`, `[STREAMING COMPONENT]`).

---

### Display Mode B: `[—o Lines]` — Altium/KiCad-Grade Functional PCB Bus

#### Strict Engineering Rule: "0% Decorative // 100% Reason to Exist"
Every line, pin, via, and passive component must represent an actual architectural IPC mechanism:

1. **Central Package**: `ORCHESTRATOR // IC-01 [PID 4100 // AMD64-EMU]` represented as a 64-pin Quad Flat Package (QFP) with pin-out labels (`CLK_IN`, `RST_N`, `DMA_TX0..3`, `SHM_CLK`, `IPC_SYN`).
2. **5 Orthogonal Signal Buses (45° and 90° Routing Only)**:
   - **North Bus (`NORTH_BUS: MMAP_RING_BUFFER_PBF`)**:
     - Connects IC-01 to a memory-mapped Protobuf v3 ring buffer at `0x7F00_0000` (65,536 slots).
     - Routes out to test point `TP01: PERF_PROBE_NANOS`.
   - **West Bus (`WEST_BUS: JWT_TX[0..7] + ANTHROPIC_RX`)**:
     - Feeds `ws/api-auth` (PID 4812).
     - Routes through a 100µF decoupling capacitor `C104 (TOKEN_BUCKET // RATE_LIMIT)` to hardware-throttle token streams.
   - **Southwest Bus (`SW_BUS: PYTEST_SERDES_D0`)**:
     - 45° runner trace connecting `ws/integration-tests` (PID 5012) through resistor `R12 (50Ω DIFF_PAIR TERMINATOR)` and `TP12 (EXIT_CODE [0])`.
   - **South Bus (`SOUTH_BUS: DMA_VDOM_HMR_CH1`)**:
     - Multi-lane parallel DMA bus feeding `ws/web-console` (PID 4980).
     - Routed through an 8-pad via array (`SHM ZERO-COPY VIA ARRAY 4x2`) bridging user-space `L1_TOP_COPPER` to kernel-space `L2_SHM`.
   - **East Bus (`EAST_BUS: ABT_DIFF_MERGE`)**:
     - Connects conflict resolver to `ws/docs` (PID 5120) through diode `D1 (LOCK_VOLTAGE_CLAMP)` to trap uncommitted mutations.
3. **Dedicated Sub-Panels**:
   - **Eye Diagram (Oscilloscope)**: Synthetic SVG differential sine waves displaying eye opening height (`380mV`), jitter (`0.12 ps`), and SNR (`42.4 dB`).
   - **Interrupt Vector Table (IVT)**: Hex registers `0x00 INT_SYSCALL_DISPATCH`, `0x04 GIT_AST_DIFF_MERGE`, `0x08 PTY_BUFFER_FLUSH`, `0x0C DOCS_DIRTY_CONFLICT`.

---

### Display Mode C: `[3D View]` — Three.js Celestial Armillary Astrolabe

#### Three.js Engine Implementation Guide
Inject a `<script src="https://ajax.googleapis.com/ajax/libs/threejs/r125/three.min.js">` canvas into a full-height container (`min-height: 600px`).

1. **Scene Setup & Lighting**:
   - `THREE.PerspectiveCamera(42, width / height, 0.1, 1000)` at `(0, 26, 74)`.
   - Background: Transparent or `#0a0e14` with subtle exponential fog (`THREE.FogExp2(0x0a0e14, 0.0016)`).
   - Key lights: Ambient (`#182438`), Directional Lime (`#b8ff47`), Point Cyan (`#38bdf8`), Point Amber (`#f59e0b`).
2. **Central Orchestrator Gyro-Core**:
   - Core Mesh: `THREE.DodecahedronGeometry(3.6, 1)` with specular dark graphite material.
   - Wireframe overlay: `THREE.DodecahedronGeometry(3.65, 1)` with lime wireframe.
   - Inner nucleus: Breathing `THREE.IcosahedronGeometry(1.6, 2)` scaled via `1.0 + sin(t * 3.8) * 0.18`.
   - Gimbal Rings: 3 nested `THREE.TorusGeometry` rings (radii `5.2`, `6.4`, `7.6`) rotating on X, Y, and Z axes.
3. **Concentric Armillary Astrolabe Rims**:
   - Tilted toruses with micro-graduations:
     - Equator Ring: Radius `25`, Color `#b8ff47`, 90 graduation tick lines with major/cardinal pips.
     - Ecliptic Ring: Radius `16`, Color `#38bdf8`, tilted at 60°.
     - Solstice & Polar Rims: Radii `32` and `38`.
   - Outer Geodesic Constellation Cage: Wireframe sphere (`radius: 34`) with `THREE.Points` at each vertex.
4. **Sculpted 3D Subagent Geometries (Role-Differentiated)**:
   - `ws/api-auth`: **Octahedron** (`radius: 2.6`) in cyan `#38bdf8` (Cryptographic authentication token).
   - `ws/web-console`: **Hexagonal Cylinder** (`radius: 1.8`, `height: 3.2`) in lime `#b8ff47` (Continuous stream pipe).
   - `ws/integration-tests`: **Crystalline Box** (`size: 2.4`) in emerald `#34d399` (Structural validation cube).
   - `ws/docs`: **Tetrahedron** (`radius: 2.8`) in red `#f87171` (Conflict warning pyramid).
   - Each node contains a planar reticle ring disc (`RingGeometry`) and crosshairs.
5. **Elevated Quadratic Bezier Conduits & Pulse Packets**:
   - From Core `(0,0,0)` to each subagent position `P_agent`:
     - Calculate midpoint `P_mid = (P_start + P_agent) * 0.5`.
     - Elevate arc: `P_mid.y += (P_agent.y > 0 ? 9 : -9)`.
     - Create `THREE.QuadraticBezierCurve3(P_start, P_mid, P_agent)`.
   - Travel packets: 4 glowing spheres per conduit advancing along curve progress `t += speed`.
6. **Interaction Loop**:
   - Window mouse coordinates update `targetRotX` and `targetRotY` with smooth inertial damping `rot += (target - rot) * 0.045`.

---

## 5. Screen 3: Workstreams Matrix & Dispatch (`/workstreams`)

### Purpose
Concurrent fleet management and git worktree isolation manager.

### Component Breakdown
1. **Control Bar**:
   - Metrics: `4 Running`, `Sparse-Checkout (Linux Namespaces + cgroups v2)`, `Lock-Free Optimistic Merge (Pass 98.4%)`, `1.84M Tokens Accum`.
   - CTA buttons: `Dry Run Merge`, `Sync All Worktrees`, `+ Dispatch New Workstream` (lime button).
2. **Subagent Workstream Cards (2×2 Grid)**:
   Each card encapsulates:
   - Header: Agent name, status pill (`RUNNING`, `STREAMING CHUNKS`, `EXECUTING PYTEST`, `DIRTY BUFFER`), PID, round-trip latency.
   - Model info: Assigned LLM (`claude-3-7-sonnet`, `deepseek-coder-v2`, `gemini-2.0-flash`), role, VRAM/RAM allocation.
   - Worktree path: Local sandbox path (`/tmp/workstreams/wt-api-auth`) and git branch.
   - Live telemetry: Test coverage bar, touched file count, and animated CSS token stream equalizer bars.
   - Card Actions: `Terminal PTY`, `Diff Viewer (+124)`, `Rebase onto Main`, `Pause Subagent`.
3. **Conflict Radar & Dispatch Timeline (Bottom Left)**:
   - Multi-branch git commit stream timeline visualizing trunk and worktree commits (`c701bf4`, `8fd19e4`, `HEAD v2.4.1`).
   - Non-overlapping AST conflict score (`94.2% automatically resolvable`).
4. **Inter-Agent IPC Conduits Stream (Bottom Right)**:
   - Live feed of inter-agent messages (`120 msg/s`) with packet filters (`All`, `Dispatches`, `Git Ops`, `Alerts`).
   - Interactive CLI input prompt: `> inject IPC message to bus (e.g. broadcast:sync --force)...`.

---

## 6. Screen 4: System & Agent Engine Configuration (`/settings`)

### Purpose
Fine-grained control over multi-model LLM routing, cgroups resource sandboxing, daemon sockets, and provider API credentials.

### Component Breakdown
1. **Tabbed Sub-Navigation**:
   - `[01] GENERAL & CLI`, `[02] SUBAGENT MODELS & ROUTING`, `[03] GIT & WORKTREE ISOLATION`, `[04] IPC & DAEMON SOCKETS`, `[05] SECURITY & API KEYS`.
2. **LLM Model Routing Matrix (4 Role Cards)**:
   - `ROLE: CODE_GENERATION` (Hot-path): Primary model selector (`claude-3-7-sonnet`), Fallback selector, Reasoning level (`HIGH`), Temperature slider (`0.20`), Max tokens.
   - `ROLE: QUICK_FIX_REFACTOR` (Fast-lane): Model (`gpt-4o-code-stream`), Reasoning (`NONE`), Temp (`0.10`).
   - `ROLE: TEST_SUITE_FUZZING` (Local vLLM/Ollama): Local model (`deepseek-coder-v2:instruct`), Target conduit endpoint (`http://127.0.0.1:11434`), VRAM buffer gauge.
   - `ROLE: DOCS_SUMMARY`: Lightweight fast engine (`gemini-2.0-flash-exp`).
3. **Budget Sentinel & Auto-Throttle**:
   - Spent progress bar (`$450.00 Expended / $600.00 Hard Cap`), Soft limit threshold, Toggle `Auto-Throttle Active`.
4. **Provider Conduits & Secret Vault**:
   - Secure table showing Anthropic, OpenAI, and vLLM credentials with key fingerprint (`sk-ant-api03-...382f`), status, latency, and `Reveal` / `Cycle` actions.
5. **Git Worktree & Filesystem Sandbox Policies**:
   - Base storage directory, flags (`Auto-clean post-merge`, `Force ephemeral tmpfs mount`).
   - Sparse checkout profile matrix (`Full Repo`, `Cone Mode (Fast)`, `Custom Pattern`).
   - cgroups v2 resource limits: CPU Ceiling per subagent (`2.0 vCPU`), RAM Ceiling (`1.50 GB`), PID Fork limit (`256 PIDs`).
6. **Daemon & IPC Conduits**:
   - Unix socket path (`unix:///var/run/workstreams.sock`), serialization engine (`Protobuf v3 zero-copy mmap`), heartbeat frequency (`250ms`), terminal multiplexer hook (`zellij / tmux`).
7. **Action Bar**:
   - `Export config.toml`, `Revert to Defaults`, `Test Provider Conduits`, `Restart Daemon` (lime button).

---

## 7. Implementation Checklist for Autonomous Agents

When implementing these views in your tech stack (React / Next.js / Vue / Svelte + Tailwind CSS):

- [ ] **Tailwind Theme Setup**:
  Configure colors: `surface: #111418`, `surface-container-low: #191c20`, `surface-container-high: #272a2f`, `primary: #b8ff47`, `primary-glow: rgba(184, 255, 71, 0.15)`, `cyan: #38bdf8`, `emerald: #34d399`, `amber: #f59e0b`, `rose: #f87171`.
- [ ] **Typography**:
  Import `'Space Mono', monospace` for all code tags, hashes, metrics, latency badges, and terminal logs.
- [ ] **Three.js Asset Isolation**:
  When building the 3D astrolabe view, encapsulate the WebGL canvas inside a React `useRef` / `useEffect` hook, ensure window resize listeners recalculate `camera.aspect` and `renderer.setSize`, and clean up the animation loop with `cancelAnimationFrame` on component unmount.
- [ ] **State Machine for Display Modes**:
  Manage the `/events` active view (`circle` | `lines` | `3d`) in URL query parameters (`?mode=3d`) or global workspace store so user state persists across page refreshes.
- [ ] **SVG Altium Trace Precision**:
  For the PCB trace lines mode, use strictly right-angle and 45-degree SVG paths (`M ... L ... L ...`) with `stroke-linecap="round"` and `stroke-linejoin="round"`, applying glowing drop-shadow filters for active live buses.
- [ ] **Terminal Emulation**:
  Implement auto-scrolling log tails with a sticky bottom lock that disengages when the user manually scrolls up to inspect previous trace logs.
