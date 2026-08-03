# AIOpsLab Web Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the registered AIOpsLab detection benchmark as a persistent, cancellable web Job with SSE progress and research artifacts while keeping it separate from Chaos Mesh recovery experiments.

**Architecture:** A dedicated benchmark request, SQLite store, and background runner share the Control Plane process but use separate tables and API routes. A bounded adapter resolves only server-registered benchmark definitions and invokes the existing AIOpsLab automation script without a shell. The existing recovery Job remains unchanged.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, Server-Sent Events, subprocess argv execution, existing AIOpsLab runner, JavaScript/CSS UI, pytest

## Global Constraints

- AIOpsLab is a separate benchmark Job, not a Chaos Mesh recovery stage.
- Browser input may select only registered benchmark IDs and bounded repetition counts.
- The server operator supplies `AIOPSLAB_ROOT`, `AIOPSLAB_PYTHON`, and `KUBECONFIG`; these paths never come from the browser.
- Production execution uses an argv list with no shell and writes artifacts below `runs/control-plane/aiopslab/`.
- Missing runtime prerequisites fail before the AIOpsLab subprocess starts.
- Tests use an injected fake executor and do not require the external AIOpsLab repository.
- Existing deterministic, AutoGen, CLI, and recovery Job behavior must remain compatible.

---

### Task 1: Persistent AIOpsLab Benchmark Job Model

**Files:**
- Create: `src/aiops_k8s_agents/aiopslab_jobs.py`
- Test: `tests/test_aiopslab_jobs.py`

**Interfaces:**
- Produces: `AIOpsLabBenchmarkRequest`, `AIOpsLabBenchmarkJob`, `SQLiteAIOpsLabJobStore`
- Persists: request, status, result, error, and ordered `RuntimeEvent` values

- [ ] Write failing tests for request validation, SQLite round-trip, event ordering, cancellation, result storage, and startup interruption.
- [ ] Run `python -m pytest tests/test_aiopslab_jobs.py -q` and confirm RED.
- [ ] Implement the immutable request/job models and separate SQLite tables in the existing Job database.
- [ ] Run the focused tests and commit `feat: add persistent aiopslab benchmark jobs`.

### Task 2: Bounded Benchmark Executor and Background Runner

**Files:**
- Create: `config/aiopslab_benchmarks.json`
- Create: `src/aiops_k8s_agents/aiopslab_benchmark.py`
- Create: `src/aiops_k8s_agents/aiopslab_job_runner.py`
- Test: `tests/test_aiopslab_benchmark.py`
- Test: `tests/test_aiopslab_job_runner.py`

**Interfaces:**
- Consumes: registered benchmark ID and server-owned runtime paths
- Produces: one report per repetition, aggregate summary, streamed benchmark events, and sanitized failure state

- [ ] Write failing tests for registry resolution, argv construction, missing prerequisites, fake execution, repeated runs, cancellation, and output sanitization.
- [ ] Run the focused tests and confirm RED.
- [ ] Implement a no-shell executor around `scripts/server_aiopslab_auto_detection.py` and a persistent background runner.
- [ ] Parse generated JSON reports with `summarize_aiopslab_reports` and save Markdown/CSV summaries in the Job artifact directory.
- [ ] Run the focused tests and commit `feat: run bounded aiopslab benchmark jobs`.

### Task 3: AIOpsLab Benchmark API and SSE

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Test: `tests/test_control_plane_web.py`

**Interfaces:**
- Adds: `GET /api/benchmarks/aiopslab`
- Adds: `POST /api/benchmarks/aiopslab/jobs`
- Adds: list, detail, SSE, and cancel routes under `/api/benchmarks/aiopslab/jobs`

- [ ] Write failing API tests for readiness rejection, fake Job completion, persistence, SSE replay, cancellation, and artifact links.
- [ ] Run the focused API tests and confirm RED.
- [ ] Attach the AIOpsLab store/runner to the app lifecycle without changing recovery endpoints.
- [ ] Expose only registered problem metadata and sanitized errors.
- [ ] Run the focused tests and commit `feat: expose aiopslab benchmark web jobs`.

### Task 4: Compact Benchmark Console and Documentation

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `README.md`
- Modify: `docs/submission/control_plane_ui_guide.md`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Displays: readiness, registered problem, repetitions, progress, TTD, accuracy, reward, event log, and artifact downloads
- Preserves: the current three-area recovery workspace; benchmark controls remain collapsed until requested

- [ ] Write failing UI contract tests for the compact AIOpsLab panel and all benchmark API calls.
- [ ] Run the focused UI tests and confirm RED.
- [ ] Add a collapsed benchmark panel under Results so the primary recovery workflow is not cluttered.
- [ ] Render mock/fake boundaries and benchmark results separately from Kubernetes recovery metrics.
- [ ] Document Ubuntu environment variables, cancellation, artifacts, and evidence boundaries.
- [ ] Run `python -m pytest` and `cd go/aiops-guard && go test ./...`.
- [ ] Start a fake-executor server, complete one benchmark Job, verify SSE/refresh restoration and browser errors, then commit `feat: integrate aiopslab benchmark console`.
