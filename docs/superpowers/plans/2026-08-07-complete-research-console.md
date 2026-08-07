# Complete Research Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete every implementable requirement in `CODEX_AIOPS_UI_IMPLEMENTATION_PROMPT.md` on `feat/ui-research-console-redesign` without fabricating runtime data.

**Architecture:** Preserve FastAPI + SQLite + SSE runtime contracts. Add only narrow read metadata needed by the UI, then implement missing behavior in the existing static HTML/CSS/JavaScript console. Keep recovery, AIOpsLab, comparison and artifact boundaries separate.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, vanilla HTML/CSS/JavaScript, pytest, GitHub Actions, headless Chrome.

## Global Constraints

- Default control plane URL remains `http://127.0.0.1:18180/`.
- Never fabricate experiment or benchmark metrics.
- Never run a Real Kubernetes mutation in CI.
- Deterministic controller never displays a model.
- AIOpsLab stays separate from Chaos Mesh recovery.
- Existing safety gates, validators, allowlists, replica limits, cancellation and artifacts remain authoritative.

---

### Task 1: AIOpsLab persisted metadata and history contract

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Test: `tests/test_control_plane_web.py`

**Interfaces:**
- Produces benchmark catalog and job payload fields `detector_id` and `detector_label`.
- Existing `/api/benchmarks/aiopslab/jobs` remains the history source.

- [ ] Add a failing API test asserting catalog/runtime job payloads expose stable detector metadata.
- [ ] Run the focused test and confirm failure.
- [ ] Add `detector_id="ai-mcmp-four-agent"` and `detector_label="AI-MCMP Four-Agent"` to public AIOpsLab payloads.
- [ ] Re-run focused tests and confirm success.

### Task 2: AIOpsLab three-tab user interface

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes `/api/benchmarks/aiopslab`, `/api/benchmarks/aiopslab/jobs`, job detail/events/artifact URLs.
- Produces tabs `evaluation`, `comparison`, `history`.

- [ ] Add failing UI contract assertions for the three tabs, comparison state and history table/pagination.
- [ ] Implement the tab markup and accessible tab switching.
- [ ] Fetch persisted AIOpsLab jobs and render recent results/history.
- [ ] Aggregate actual results by detector. If only one detector exists, show the real detector plus `비교 가능한 Detector가 1개입니다.` instead of fake competitors.
- [ ] Add job detail expansion including events and actual artifacts.
- [ ] Add responsive styles and empty/loading/error states.
- [ ] Run UI contract tests and JavaScript syntax checks.

### Task 3: Experiment result filters, URL state and pagination

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- URL query parameters: `period`, `scenario`, `controller`, `mode`, `status`, `q`, `page`, `page_size`.
- Existing `/api/experiments?limit=100` remains the loaded data source.

- [ ] Add failing contract tests for reset control, page controls and URL-sync functions.
- [ ] Parse result filters from URL on boot.
- [ ] Update URL on filters/search/page changes without losing primary hash route.
- [ ] Debounce Experiment ID search around 300 ms.
- [ ] Reset page to 1 on filter changes.
- [ ] Paginate the filtered list and show current page/total results/loaded-limit note.
- [ ] Add explicit no-results state with filter reset action.
- [ ] Keep summary statistics based on the full filtered set, excluding missing metrics from averages.
- [ ] Re-run tests and syntax checks.

### Task 4: Experiment detail completion

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Detail tab query parameter: `detail_tab`.
- Rerun pre-fills the existing recovery form; it never submits automatically.

- [ ] Add failing contract tests for ID copy, grouped download, rerun prefill, detail-tab URL state, log controls and event payload area.
- [ ] Implement ID copy feedback.
- [ ] Implement grouped artifact menu showing only actual artifacts.
- [ ] Implement rerun prefill and navigate to recovery form; Real remains unexecuted.
- [ ] Synchronize six detail tabs to URL.
- [ ] Add bounded log view with level/search/autoscroll controls and download when data exists.
- [ ] Render event name/time/stage/summary and expandable payload.
- [ ] Re-run tests and syntax checks.

### Task 5: Loading/error/empty/accessibility consistency

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

- [ ] Add `aria-live` error/status regions where missing.
- [ ] Add skeleton/refresh states for AIOpsLab and results without replacing existing content during refresh.
- [ ] Ensure every visible input has a label and selectable cards use buttons/`aria-pressed`.
- [ ] Ensure missing values remain non-numeric placeholders.
- [ ] Verify 1440/1920 responsive CSS contracts.

### Task 6: Full verification and screenshots

**Files:**
- Modify: `.github/workflows/ui-redesign-check.yml`

- [ ] Run full Python tests.
- [ ] Run Go guard tests.
- [ ] Run CLI entrypoint check.
- [ ] Run JavaScript syntax checks for `app.js` and `reference-ui.js`.
- [ ] Start server on `127.0.0.1:18180`.
- [ ] Capture 1672×941 screenshots for overview, recovery, AIOpsLab evaluation, AIOpsLab comparison, AIOpsLab history, experiment results and experiment detail.
- [ ] Upload screenshots as the workflow artifact.
- [ ] Do not claim Real external-environment validation; report it as the remaining environment-specific check.
