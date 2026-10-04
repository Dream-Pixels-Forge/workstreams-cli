## Goal: Implement Stitch Dashboard in web Directory

### Objective
Implement a functional dashboard derived from the Google Stitch project "Workstreams Agent Dashboard" (projects/18260495634110963971), with all implementation files placed exclusively inside the `web/` directory. The dashboard should render key Stitch screen data as a working web application.

### Context
The Google Stitch project contains 20+ screens including dashboards (Celestial & Polar Topology, 3D Celestial Astrolabe, Project Monitor, Workstreams Matrix & Dispatch Control), UI components, and assets. This goal implements one of these dashboards as a working web application within the `web/` directory, leveraging the project's design tokens, screen structures, and visual patterns.

### Deliverables
- [ ] `web/index.html` - Main dashboard entry point with dashboard structure
- [ ] `web/style.css` - Styling using Stitch design tokens (colors, typography, roundness)
- [ ] `web/app.js` - Dashboard application logic that fetches/integrates Stitch screen data
- [ ] `web/components/` - Reusable UI components derived from Stitch screen designs
- [ ] `web/manifest.json` - Web app manifest for installability
- [ ] `web/readme.md` - Documentation of the implemented dashboard

### Definition of Done
- [ ] All deliverable files exist inside `web/` directory
- [ ] `web/index.html` renders without console errors in Chrome/Firefox
- [ ] CSS uses design tokens matching Stitch project's dark theme (#111418 surface, #b8ff47 primary accent, #space_mono font)
- [ ] `web/app.js` successfully integrates with at least one Stitch screen's data/structure
- [ ] No TypeScript/JS errors when running `npx webhint` or similar linting
- [ ] Dashboard is functional and accessible (basic a11y checks pass)

### Verification Steps
1. Open `web/index.html` in a browser - verify it renders without errors
2. Check that CSS variables match Stitch design tokens (use browser devtools)
3. Run `npx eslint web/` - zero errors
4. Run `npx webhint web/` - accessibility score 80+
5. Verify `web/manifest.json` has proper short_name and start_url
6. Confirm all files are inside `web/` directory (no files outside)

### Anti-Drift Rules
- Stay within scope of implementing a dashboard from Stitch project
- Do not modify code outside the `web/` directory
- Do not implement features beyond dashboard functionality
- If Stitch data integration requires external APIs, create a new goal
- All UI styling must use the Stitch project's design tokens (colors, fonts, roundness)

### Estimated Effort
Medium - 8-12 hours to implement core dashboard functionality with Stitch design integration.

### Pipeline Orchestrator Mandatory
This goal **MUST** use the `pipeline-orchestrator` skill as a strict mandatory coordinator for all implementation phases. The pipeline-orchestrator will:
1. Load and coordinate the appropriate subagents for each implementation phase
2. Ensure all work stays within the `web/` directory boundary
3. Manage handoffs between design, implementation, and verification phases
4. Track progress and enforce the goal completion criteria
5. Report blockers and enforce anti-drift rules

The pipeline-orchestrator is not optional - it must be invoked before any implementation work begins and must sign off on each phase transition.