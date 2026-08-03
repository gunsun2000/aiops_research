# Persistent Experiment Job and Live Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing bounded experiment runtime to a persistent background job API, replayable SSE events, cancellation/restart recovery, and the approved three-area research console.

**Architecture:** A SQLite-backed `ExperimentJobStore` is the source of truth for jobs and runtime events. `ExperimentJobRunner` owns one background worker per job, creates a fresh bounded runtime with a job-specific event sink and cancellation signal, and records the final normalized session. FastAPI exposes create/list/detail/cancel/event-stream routes; the browser consumes those routes and never executes Kubernetes commands directly.

**Tech Stack:** Python 3.11+, SQLite standard library, FastAPI/Starlette, vanilla HTML/CSS/JavaScript, existing ExperimentRuntime and ExperimentSession contracts, pytest.

## Global Constraints

- Preserve existing deterministic CLI commands and mock/dry-run/real boundaries.
- Real mode requires both the existing server environment gate and an exact confirmation phrase.
- Persist every job transition and runtime event before broadcasting it.
- Cancellation requests must set the runtime cancellation signal and allow registered cleanup to finish.
- On server restart, nonterminal jobs become `interrupted`; never blindly resume an external mutation.
- Keep AutoGen and AIOpsLab execution as the next integration plan; this plan prepares the shared job contract without falsely marking them connected.
- Do not touch the unrelated root `tmp/` directory.

---

### Task 1: Persistent Job and Event Store

**Files:**
- Create: `src/aiops_k8s_agents/experiment_jobs.py`
- Create: `tests/test_experiment_jobs.py`

**Interfaces:**
- Produces: `ExperimentJob`, `ExperimentJobStatus`, `SQLiteExperimentJobStore`.
- Store methods: `create(request)`, `get(experiment_id)`, `list(limit)`, `transition(...)`, `append_event(event)`, `events_after(experiment_id, sequence)`, `set_result(...)`, `request_cancel(...)`, `interrupt_nonterminal_jobs()`.

- [ ] Write tests proving literal request JSON round-trips, transitions are persisted, events replay after a sequence, cancellation is durable, and restart interruption affects only nonterminal jobs.
- [ ] Run `python -m pytest tests/test_experiment_jobs.py -q` and verify failures occur because the module is missing.
- [ ] Implement the SQLite schema and immutable public job model with thread-safe short-lived connections.
- [ ] Re-run the focused tests and commit `feat: add persistent experiment job store`.

### Task 2: Background Runner, Cancellation, and Restart Recovery

**Files:**
- Create: `src/aiops_k8s_agents/experiment_job_runner.py`
- Create: `tests/test_experiment_job_runner.py`
- Modify: `src/aiops_k8s_agents/experiment_runtime_factory.py`

**Interfaces:**
- Consumes: `SQLiteExperimentJobStore`, `ExperimentRuntimeRequest`, runtime factory accepting a job event sink and cancellation event.
- Produces: `ExperimentJobRunner.submit(request)`, `cancel(experiment_id)`, `is_running(experiment_id)`, `shutdown(wait)`.

- [ ] Write tests proving submit returns immediately, runtime events persist in order, final results persist, cancellation reaches the runtime signal, and startup marks stale jobs interrupted.
- [ ] Verify focused tests fail for the missing runner.
- [ ] Implement the bounded thread runner and event fan-out condition used by SSE waiters.
- [ ] Re-run focused tests and commit `feat: run persistent experiments in background`.

### Task 3: Execution, Query, Cancellation, and SSE API

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Modify: `tests/test_control_plane_web.py`

**Interfaces:**
- Produces:
  - `POST /api/experiments`
  - `GET /api/experiments`
  - `GET /api/experiments/{experiment_id}`
  - `POST /api/experiments/{experiment_id}/cancel`
  - `GET /api/experiments/{experiment_id}/events`
- SSE supports `Last-Event-ID` and terminates after a terminal job event.

- [ ] Write route tests for accepted mock submission, unknown job, validation rejection, real confirmation rejection, cancellation, event replay, and terminal SSE completion.
- [ ] Verify route tests fail because the new endpoints are absent.
- [ ] Add injected store/runner state to `create_app`, request models, route handlers, and `StreamingResponse` formatting.
- [ ] Re-run API tests and commit `feat: expose live experiment job api`.

### Task 4: Approved Research Console Connected to Live Jobs

**Files:**
- Replace: `ui/control_plane_static/index.html`
- Replace: `ui/control_plane_static/styles.css`
- Replace: `ui/control_plane_static/app.js`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: scenario/platform/connection APIs and all Task 3 job APIs.
- Produces: left experiment conditions, center seven-stage timeline and four-agent workflow, right decision/safety inspector, bottom result/artifact summary.

- [ ] Write source-contract tests for the three-area layout, all four scenarios, all four agents, mock/dry-run/real controls, SSE `EventSource`, cancellation, real confirmation, event log, and result artifacts.
- [ ] Verify UI tests fail against the old console.
- [ ] Implement the approved restrained research-console layout and live state reducer; do not show synthetic Agent conclusions before a job produces evidence.
- [ ] Re-run UI and web tests and commit `feat: connect research console to live jobs`.

### Task 5: Documentation and End-to-End Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/submission/execution_code_guide.md`
- Modify: `docs/submission/test_guide.md`

**Interfaces:**
- Documents the local mock demonstration, Ubuntu dry-run/real prerequisites, interruption semantics, and the explicit remaining AutoGen/AIOpsLab web boundary.

- [ ] Document startup, safe mock run, dry-run/real gates, cancellation, persisted database location, and recovery after server restart.
- [ ] Run `python -m pytest` and `go test ./...`.
- [ ] Start the local control plane, exercise one mock job through the browser, verify desktop and mobile screenshots, and confirm no overlap or console errors.
- [ ] Commit `docs: document live experiment console`.

## Self-Review

- Spec coverage: persistent jobs, replayable events, cancellation, restart safety, API, and approved UI each map to one task.
- Scope boundary: AutoGen and AIOpsLab web execution remain explicitly pending, while the common job substrate needed by them is delivered here.
- Type consistency: all runtime requests use the existing `ExperimentRuntimeRequest`; all identifiers use `experiment_id`; SSE cursors use the existing integer event sequence.
- Placeholder scan: no implementation step depends on an undefined future interface.
