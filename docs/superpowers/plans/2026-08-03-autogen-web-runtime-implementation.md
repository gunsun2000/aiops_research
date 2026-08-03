# AutoGen Web Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing structured AutoGen 4-Agent controller to the persistent experiment Job, SSE, and research console without weakening the deterministic or Kubernetes safety paths.

**Architecture:** `ExperimentRuntimeRequest` gains an explicit controller provenance field. The existing runtime factory selects either the registered deterministic adapter set or the registered AutoGen adapter set, while the same Evidence, Validator, executor, recovery monitor, operation lock, timeout, and cleanup lifecycle remain authoritative. The web API performs credential/dependency preflight before creating an AutoGen Job, and the UI enables AutoGen only when that preflight is ready.

**Tech Stack:** Python 3.11+, FastAPI, SQLite Job store, SSE, AutoGen AgentChat, existing JavaScript/CSS UI, pytest

## Global Constraints

- Existing requests without a controller remain deterministic.
- AutoGen never emits or executes free-form shell commands; only structured `RecoveryAction` values reach the Validator.
- AutoGen dependency or credential failure must occur before Chaos injection or Kubernetes mutation.
- The same namespace/deployment allowlist, replica bounds, operation lock, timeout, cancellation, and cleanup rules apply to both controllers.
- Tests must use a deterministic fake decision provider and require no API key.
- AutoGen model name and controller provenance must be stored in Job results and displayed separately from deterministic evidence.

---

### Task 1: Persist Controller Provenance

**Files:**
- Modify: `src/aiops_k8s_agents/experiment_runtime_models.py`
- Modify: `src/aiops_k8s_agents/experiment_jobs.py`
- Test: `tests/test_experiment_runtime_models.py`
- Test: `tests/test_experiment_jobs.py`

**Interfaces:**
- Produces: `ExperimentRuntimeRequest.controller: Literal["deterministic", "autogen"]`
- Preserves: existing serialized requests default to `deterministic`

- [ ] Write failing tests proving explicit AutoGen provenance round-trips through JSON and SQLite while missing legacy values load as deterministic.
- [ ] Run the focused tests and confirm the failures are caused by the missing controller field.
- [ ] Add normalized controller validation, serialization, and backward-compatible deserialization.
- [ ] Run the focused tests and commit `feat: persist experiment controller provenance`.

### Task 2: Select the Registered AutoGen Adapter Runtime

**Files:**
- Modify: `src/aiops_k8s_agents/experiment_runtime_factory.py`
- Modify: `src/aiops_k8s_agents/experiment_runtime.py`
- Test: `tests/test_experiment_runtime_factory.py`
- Test: `tests/test_experiment_runtime.py`

**Interfaces:**
- Consumes: `ExperimentRuntimeRequest.controller`
- Produces: `build_experiment_runtime(..., autogen_decision_provider_factory=None, autogen_model_client_factory=None, autogen_model=None)`

- [ ] Write failing tests showing deterministic remains the default, AutoGen uses `four-agent-autogen-v1`, and an unavailable provider blocks before fault injection.
- [ ] Run the focused tests and confirm RED.
- [ ] Build the exact registered AutoGen adapter registry only for AutoGen requests and extend admission checks to whitelist that exact adapter set.
- [ ] Add controller/model provenance to the runtime report and ensure malformed or unsafe AutoGen output is rejected by the existing Validator.
- [ ] Run the focused tests and commit `feat: connect autogen controller to bounded runtime`.

### Task 3: Expose AutoGen Through the Persistent Web Job API

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Test: `tests/test_control_plane_web.py`

**Interfaces:**
- Extends: `POST /api/experiments` with `controller` and optional `model`
- Extends: `GET /api/connections` with concrete AutoGen dependency/credential readiness

- [ ] Write failing API tests for AutoGen profile resolution, missing credential rejection, fake-provider Job completion, and sanitized model errors.
- [ ] Run the focused API tests and confirm RED.
- [ ] Validate controller/profile combinations and require AutoGen readiness for AutoGen requests in every execution mode.
- [ ] Pass the selected model/provider into the runtime factory without logging credentials.
- [ ] Run the focused tests and commit `feat: expose autogen experiment jobs`.

### Task 4: Display AutoGen State, Provenance, and Transcript

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: `/api/connections`, persistent Job result, SSE runtime events
- Displays: controller readiness, selected model, transcript/review evidence, and failure boundary

- [ ] Write failing source-contract tests for enabled/disabled AutoGen selection, controller payload, model provenance, and transcript rendering.
- [ ] Run the focused UI tests and confirm RED.
- [ ] Enable AutoGen only when ready, automatically select the AutoGen protocol profile, and render provenance/transcript in the existing inspector rather than adding another dashboard.
- [ ] Run UI tests and commit `feat: show autogen jobs in research console`.

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/submission/control_plane_ui_guide.md`
- Modify: `docs/experiments/platform_real_runtime_guide.md`

**Interfaces:**
- Documents: deterministic versus AutoGen boundaries and Ubuntu execution prerequisites

- [ ] Document the AutoGen web Job flow, model/key prerequisites, mock/dry-run/real distinction, and safe failure behavior.
- [ ] Run `python -m pytest` and require zero failures.
- [ ] Run `cd go/aiops-guard && go test ./...` and require zero failures.
- [ ] Start the web server, run one fake-provider AutoGen Job, verify SSE replay and refresh restoration, and inspect desktop/mobile layouts.
- [ ] Commit `docs: document autogen web runtime` and merge only after verification.

