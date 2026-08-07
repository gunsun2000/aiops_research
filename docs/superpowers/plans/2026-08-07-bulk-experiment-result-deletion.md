# Bulk Experiment Result Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe `전체 삭제` action that permanently deletes all terminal recovery experiment results while preserving queued/running/cancelling experiments.

**Architecture:** Reuse the existing single-result deletion safety path for artifact validation and database deletion. Add `DELETE /api/experiments` to iterate terminal jobs server-side, then expose one event-driven destructive button above the results table that refreshes history/dashboard/pagination after success.

**Tech Stack:** Python, SQLite, FastAPI, vanilla JavaScript, pytest, GitHub Actions.

## Global Constraints

- Eligible statuses: `completed`, `failed`, `blocked`, `cancelled`, `interrupted`.
- Protected statuses: `queued`, `running`, `cancelling`.
- Delete Job + related events + validated experiment artifacts.
- Never accept client filesystem paths.
- Never cancel active jobs as part of bulk deletion.
- Require a destructive confirmation dialog.
- Do not introduce `MutationObserver` or continuous polling.

---

### Task 1: Bulk delete API contract

**Files:**
- Modify: `tests/test_experiment_result_deletion.py`
- Modify: `src/aiops_k8s_agents/control_plane_web.py`

**Interfaces:**
- Consumes: existing single experiment deletion helpers and `SQLiteExperimentJobStore.list/delete`.
- Produces: `DELETE /api/experiments` response with `deleted`, `artifacts_deleted`, `protected_active`, and `deleted_experiment_ids`.

- [ ] Add tests with multiple terminal jobs plus one active job.
- [ ] Verify the test fails before the endpoint exists.
- [ ] Implement bulk deletion by selecting terminal jobs server-side and reusing the single-delete helper.
- [ ] Verify no-terminal deletion returns success with `deleted: 0`.
- [ ] Run focused deletion tests.

### Task 2: Results-screen bulk delete UX

**Files:**
- Modify: `tests/test_complete_research_console_ui.py`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/styles.css` only if spacing/destructive styling requires it.

**Interfaces:**
- Consumes: `DELETE /api/experiments`.
- Produces: `#delete-all-experiments` button and `deleteAllExperimentResults()`.

- [ ] Add UI contract tests for the top-level `전체 삭제` button, confirmation, active-job wording, DELETE call, refresh event, and disabled state.
- [ ] Verify UI test fails before implementation.
- [ ] Place the button above the experiment results table near result controls.
- [ ] Disable when `state.jobs` has no terminal jobs.
- [ ] Confirm permanent deletion and active-job protection in Korean.
- [ ] On success reload history, reset pagination to page 1, update dashboard/distribution, clear deleted detail state, and show deletion counts.
- [ ] Run UI contract tests and JavaScript syntax checks.

### Task 3: Full verification

- [ ] Run full Python unit tests.
- [ ] Verify Go Guard and CLI checks through CI.
- [ ] Verify UI Redesign Check completes browser capture successfully.
- [ ] Report the final commit without merging the draft PR.
