# Four-Scenario Research Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect all four registered Chaos Mesh scenarios to one mock-safe 4-Agent experiment workflow and present the resulting ExperimentSession in the research console.

**Architecture:** The backend owns canonical scenario inputs and converts each mutual-supervision report into an immutable `ExperimentSession`. The web UI submits only a scenario identifier and validation backend, then renders evidence, diagnosis, four-Agent reviews, consensus, safety validation, execution, and recovery from the returned session instead of hard-coded presentation data.

**Tech Stack:** Python 3.13, FastAPI, dataclasses, vanilla JavaScript, CSS, pytest.

## Global Constraints

- Keep `mock`, `dry-run`, and `real` boundaries explicit.
- The web route remains mock-only; real Kubernetes control remains CLI-gated.
- Do not hard-code a preferred Action in the UI. Render the Action selected by the current research policy.
- Preserve existing API routes and deterministic tests.
- Store every web experiment under one `experiment_id`.

---

### Task 1: Canonical scenario experiment service

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_data.py`
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Test: `tests/test_control_plane_data.py`
- Test: `tests/test_control_plane_web.py`

**Interfaces:**
- Produces: `scenario_catalog() -> list[dict[str, object]]`
- Produces: `run_scenario_experiment_mock(scenario_id: str, backend: str) -> ExperimentSession`
- Produces: `POST /api/experiments/mock`
- Produces: `GET /api/experiments/{experiment_id}`

- [ ] **Step 1: Write failing data-layer tests**

Add parameterized tests for `cpu-stress`, `memory-stress`, `network-delay`, and `pod-kill`. Assert that each result has a distinct `experiment_id`, the selected scenario, expected target/metric evidence, all four active Agents, and completed mock execution.

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
python -m pytest tests/test_control_plane_data.py -q
```

Expected: failure because the scenario service does not exist.

- [ ] **Step 3: Implement canonical scenario definitions and session storage**

Create immutable scenario definitions in `control_plane_data.py`, call the existing `run_mutual_supervision_mock()`, attach scenario metadata, normalize the report with `normalize_experiment_session()`, and store it in one module-level `InMemoryExperimentSessionStore`.

- [ ] **Step 4: Add failing web-route tests**

Assert that `POST /api/experiments/mock` returns one normalized session and that `GET /api/experiments/{experiment_id}` returns the same stored record. Assert `404` for unknown session identifiers and `400` for unknown scenarios.

- [ ] **Step 5: Implement the FastAPI routes**

Add a scenario request model and the two API routes without removing `/api/mock-alert` or `/api/mutual-supervision/mock`.

- [ ] **Step 6: Run focused backend tests**

Run:

```powershell
python -m pytest tests/test_control_plane_data.py tests/test_control_plane_web.py tests/test_experiment_session.py -q
```

Expected: all tests pass.

### Task 2: Unified four-scenario web workspace

**Files:**
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: `POST /api/experiments/mock`
- Renders: scenario selector, current Evidence, four-Agent decisions, peer reviews, consensus, safety boundary, Action, recovery result, and seven ExperimentSession stages.

- [ ] **Step 1: Write failing static UI contract tests**

Assert that the UI references `/api/experiments/mock`, all four scenario identifiers, `currentSession`, and the seven research stage labels.

- [ ] **Step 2: Verify the UI tests fail**

Run:

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

Expected: failure because the current UI calls the legacy mutual-supervision route and keeps separate result state.

- [ ] **Step 3: Replace the fragmented experiment state**

Use `currentSession`, `experimentHistory`, `selectedScenario`, and `running` as shared UI state. Selecting a scenario updates its target and metric summary; running it calls the new experiment endpoint.

- [ ] **Step 4: Build the single-screen research console**

Keep the sidebar for secondary research navigation, but make the main experiment screen a continuous workspace containing scenario selection, Evidence, four-Agent reviews, consensus and safety, decision inspector, timeline, and live trace.

- [ ] **Step 5: Run focused UI tests**

Run:

```powershell
python -m pytest tests/test_control_plane_ui.py -q
```

Expected: all tests pass.

### Task 3: Regression and browser verification

**Files:**
- Modify only if a regression is found in Task 1 or Task 2.

**Interfaces:**
- Verifies the complete mock-safe browser flow for all four scenarios.

- [ ] **Step 1: Run Python regression tests**

```powershell
python -m pytest
```

- [ ] **Step 2: Run Go Guard regression tests when Go is available**

```powershell
cd go/aiops-guard
go test ./...
```

- [ ] **Step 3: Start the control plane**

```powershell
aiops-k8s-agents serve-control-plane
```

- [ ] **Step 4: Verify all four scenarios in a browser**

For each scenario, confirm selection, request success, Evidence values, selected Action, final session state, and absence of console errors. Verify desktop and mobile layouts have no overlap or clipping.

- [ ] **Step 5: Commit the implementation**

```powershell
git add docs/superpowers/plans/2026-07-30-four-scenario-research-console.md `
  src/aiops_k8s_agents/control_plane_data.py `
  src/aiops_k8s_agents/control_plane_web.py `
  ui/control_plane_static/app.js `
  ui/control_plane_static/styles.css `
  tests/test_control_plane_data.py `
  tests/test_control_plane_web.py `
  tests/test_control_plane_ui.py
git commit -m "feat: connect four scenarios to research console"
```
