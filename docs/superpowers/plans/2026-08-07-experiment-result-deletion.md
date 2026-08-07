# Experiment Result Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe permanent deletion of terminal recovery experiment results, their persisted events, and owned experiment artifacts from the Research Console.

**Architecture:** Extend `SQLiteExperimentJobStore` with a terminal-only delete operation, expose it through `DELETE /api/experiments/{experiment_id}`, and add destructive actions to the experiment list and detail view. Artifact paths are resolved exclusively by the server and validated to remain inside the repository-controlled artifact root.

**Tech Stack:** Python 3.11+, SQLite, FastAPI, vanilla JavaScript, pytest.

## Global Constraints

- Only terminal experiment jobs may be deleted.
- `queued`, `running`, and `cancelling` jobs must return 409 and remain intact.
- Related runtime events are removed through SQLite `ON DELETE CASCADE`.
- The client never submits artifact filesystem paths.
- Artifact cleanup must reject paths outside the repository-controlled artifact root.
- UI deletion always requires explicit confirmation.
- No `MutationObserver` or continuous polling may be introduced.

---

### Task 1: Store deletion

**Files:**
- Modify: `tests/test_experiment_jobs.py`
- Modify: `src/aiops_k8s_agents/experiment_jobs.py`

**Interfaces:**
- Produces `SQLiteExperimentJobStore.delete(experiment_id: str) -> ExperimentJob`.

- [ ] Add failing tests that a completed job and its events are deleted and a running job is rejected.
- [ ] Implement terminal-only delete with one SQLite delete transaction.
- [ ] Verify focused store tests pass.

### Task 2: API and artifact cleanup

**Files:**
- Modify: `tests/test_control_plane_web.py`
- Modify: `src/aiops_k8s_agents/control_plane_web.py`

**Interfaces:**
- Produces `DELETE /api/experiments/{experiment_id}` returning `{deleted, experiment_id, artifacts_deleted}`.

- [ ] Add failing API tests for 200, 404, 409, valid artifact cleanup, and path-boundary safety.
- [ ] Implement server-owned artifact discovery and safe deletion.
- [ ] Delete artifacts before removing the DB job so cleanup failures cannot silently lose DB provenance.
- [ ] Verify focused API tests pass.

### Task 3: UI delete controls

**Files:**
- Modify: `tests/test_complete_research_console_ui.py`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `ui/control_plane_static/index.html` only if a static status region is needed.

**Interfaces:**
- Consumes `DELETE /api/experiments/{experiment_id}`.

- [ ] Add failing UI contract tests for list delete, detail delete, confirmation, refresh, and no MutationObserver.
- [ ] Add a `삭제` button next to `상세 보기` for terminal rows.
- [ ] Add a destructive `실험 삭제` button to the detail header.
- [ ] Confirm with a Korean permanent-delete warning before calling the API.
- [ ] On success reload experiment history, recompute summaries/pagination, and return detail deletion to `#analysis`.
- [ ] Show 409 as `실행 중인 실험은 삭제할 수 없습니다.`.
- [ ] Verify JavaScript syntax and UI contract tests.

### Task 4: Full verification

- [ ] Run full Python unit tests.
- [ ] Run Go guard tests and CLI check through CI.
- [ ] Confirm UI Redesign Check passes including browser screenshot capture.
- [ ] Report the new commit to the user; do not merge the draft PR without explicit approval.
