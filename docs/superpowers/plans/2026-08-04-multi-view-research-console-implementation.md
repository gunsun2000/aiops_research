# Multi-View Research Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the existing 4-Agent AIOps console into seven focused views that share one experiment context while preserving every current API, job, SSE, safety, AutoGen, AIOpsLab, and comparison capability.

**Architecture:** Keep the current FastAPI routes and JavaScript runtime services unchanged. Recompose the static HTML into a sidebar application shell with view panels, add hash-based navigation and shared context rendering to `app.js`, and replace the one-page CSS with a responsive operational-console layout. Existing element IDs remain authoritative so current render and event functions continue to work.

**Tech Stack:** HTML5, vanilla JavaScript, CSS, FastAPI static serving, pytest, Playwright browser verification.

## Global Constraints

- Work on `codex/full-research-platform-v1`, not `master`.
- Preserve all existing API routes and request payloads.
- Preserve `mock`, `dry-run`, and `real` boundaries and confirmation gates.
- Do not label unavailable AutoGen, Kubernetes, Prometheus, Chaos Mesh, or AIOpsLab runtimes as ready.
- Preserve every DOM ID consumed by `ui/control_plane_static/app.js`.
- Keep AIOpsLab separate from Chaos Mesh recovery experiments.
- Keep AutoGen as a selectable 4-Agent controller, not a fifth Agent.
- Do not modify or delete the untracked `tmp/` directory.

---

### Task 1: Multi-view static UI contract

**Files:**
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Requires navigation container `id="platform-nav"`.
- Requires view buttons and panels for `overview`, `experiment`, `agents`, `observability`, `analysis`, `aiopslab`, and `history`.
- Requires shared context IDs `global-experiment-id`, `global-scenario`, `global-controller`, `global-stage`.
- Requires existing experiment, comparison, and AIOpsLab IDs to remain present exactly once.

- [x] **Step 1: Add failing multi-view contract tests**

Assert seven navigation buttons, seven matching view panels, shared context IDs, separate placement markers for recovery comparison and AIOpsLab, and updated asset version `v=14`.

- [x] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

Expected: failure because the existing HTML has no platform navigation or view panels.

### Task 2: Application shell and focused view markup

**Files:**
- Modify: `ui/control_plane_static/index.html`

**Interfaces:**
- Keeps all IDs listed by the `elements` registry in `app.js`.
- Produces `button[data-view]` and `section[data-view-panel]` pairs.
- Places `experiment-controls`, `live-workflow`, and `decision-inspector` only in the experiment view.
- Places `recovery-comparison-panel` only in the analysis view.
- Places `aiopslab-benchmark-panel` only in the AIOpsLab view.

- [x] **Step 1: Replace the single-page shell with semantic multi-view markup**

Build a sidebar, compact top bar, persistent experiment context bar, and seven view panels. Move existing controls into their matching views without renaming IDs.

- [x] **Step 2: Run the focused test and verify markup GREEN**

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

Expected: multi-view contract passes; JavaScript navigation assertions may still fail until Task 3.

### Task 3: Shared view navigation and experiment context

**Files:**
- Modify: `ui/control_plane_static/app.js`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Produces `selectPlatformView(viewName)`.
- Persists active view in `window.location.hash`.
- Produces `renderGlobalContext(job)`.
- Does not close SSE streams or clear Job state during view changes.

- [x] **Step 1: Add failing navigation behavior contract tests**

Assert the script binds `data-view` buttons, updates `location.hash`, handles `hashchange`, and updates all shared context IDs from the current job.

- [x] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

- [x] **Step 3: Implement navigation and global context rendering**

Initialize the view from the URL hash, expose only the selected panel, preserve current Job state, and route result/benchmark shortcuts to their corresponding views.

- [x] **Step 4: Run the focused test and verify GREEN**

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

### Task 4: Professional responsive visual system

**Files:**
- Modify: `ui/control_plane_static/styles.css`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Desktop shell: fixed-width sidebar plus fluid content.
- Tablet: compact sidebar and stacked experiment inspector.
- Mobile: horizontal view navigation and one-column content.
- Palette: neutral canvas, white surfaces, ink navy, teal state emphasis, amber warning, red failure.

- [x] **Step 1: Add failing visual structure assertions**

Assert application-shell, sidebar, hidden view panel, active panel, context bar, and desktop/mobile breakpoint selectors.

- [x] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

- [x] **Step 3: Replace CSS with the responsive console system**

Style stable navigation, compact panels, tables, forms, timelines, charts, empty states, badges, and mobile reflow without gradients, decorative blobs, nested card styling, or oversized headings.

- [x] **Step 4: Run the focused test and verify GREEN**

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

### Task 5: Regression and browser verification

**Files:**
- Modify only if verification reveals a regression.

**Interfaces:**
- Verifies existing FastAPI and Job contracts remain unchanged.
- Verifies one Mock experiment, navigation, AutoGen readiness display, comparison view, and AIOpsLab view.

- [x] **Step 1: Run focused web and UI tests**

```powershell
python -m pytest tests/test_control_plane_ui.py tests/test_control_plane_web.py -q
```

- [x] **Step 2: Run the complete Python suite**

```powershell
python -m pytest
```

- [x] **Step 3: Run Go Guard regression tests**

```powershell
cd go/aiops-guard
go test ./...
```

- [x] **Step 4: Start the local control plane and perform browser QA**

Verify desktop and mobile screenshots, all seven views, Mock execution, SSE completion, no console errors, no clipped text, and truthful disconnected runtime states.

- [x] **Step 5: Review the final diff and commit**

Stage only the implementation plan, UI files, and UI tests. Leave `tmp/` untouched.
