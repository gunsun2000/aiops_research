# Federated Coordination 0.4 Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept Federated Coordination Agent schema 0.4 FL, SL, and partitioned-inference plans as first-class Model Partition Orchestrator inputs.

**Architecture:** Add a focused adapter and provider boundary before the existing V2 planning request. The adapter preserves the upstream payload, enriches participant and model identifiers through injected providers, then delegates to the existing strategy, validation, evaluation, repository, and handoff pipeline.

**Tech Stack:** Python 3.13, dataclasses, FastAPI, vanilla JavaScript, pytest

**Spec:** `docs/superpowers/specs/2026-08-21-federated-coordination-v04-adapter-design.md`

## Global Constraints

- Preserve existing V2 and legacy partition APIs.
- Do not select or change the upstream FL, SL, or inference mode.
- Missing required context must fail closed.
- Do not add Kubernetes mutation, GPU execution, or Scheduling execution.
- Keep generated reports deterministic for identical payload and context.

---

### Task 1: Schema 0.4 Contracts and Adapter

**Files:**
- Create: `src/aiops_k8s_agents/federated_coordination_adapter.py`
- Test: `tests/test_federated_coordination_adapter.py`

**Interfaces:**
- Produces: `FederatedCoordinationPlanV04.from_dict(payload)`
- Produces: `FederatedCoordinationV04Adapter.adapt(plan, participant_context, model_context) -> PartitionPlanningRequest`
- Produces: `ParticipantContextProvider` and `ModelContextProvider` protocols plus deterministic mapping providers.

- [ ] Write failing tests for FL, SL, PARTITIONED, unknown mode, missing model context, and missing SL bandwidth.
- [ ] Run `python -m pytest tests/test_federated_coordination_adapter.py -q` and verify failure.
- [ ] Implement strict schema parsing, provider contracts, provenance mapping, and V2 request conversion.
- [ ] Run the focused tests and verify they pass.
- [ ] Commit adapter and tests.

### Task 2: FL Full-Model Strategy

**Files:**
- Modify: `src/aiops_k8s_agents/partition_strategies.py`
- Modify: `src/aiops_k8s_agents/model_partition_agent.py`
- Modify: `config/model_partition_policy.json`
- Test: `tests/test_federated_full_model_strategy.py`

**Interfaces:**
- Produces: strategy ID `federated-full-model-v1` for `training/federated_learning`.
- Produces: one full-model partition per participant plus aggregation graph edges.

- [ ] Write failing tests for full model coverage, aggregation graph, memory rejection, and deterministic selection.
- [ ] Run the focused tests and verify failure.
- [ ] Add the FL strategy intent and a dedicated full-model candidate builder selected by the Agent facade.
- [ ] Run strategy, Agent, and validator tests.
- [ ] Commit FL strategy support.

### Task 3: Shared Service and Artifact Integration

**Files:**
- Modify: `src/aiops_k8s_agents/partition_service.py`
- Modify: `src/aiops_k8s_agents/partition_artifacts.py`
- Test: `tests/test_federated_coordination_service.py`

**Interfaces:**
- Produces: `run_federated_coordination_planning(payload, ..., participant_provider, model_provider) -> dict[str, Any]`.
- Preserves: `run_partition_planning(...)`.

- [ ] Write failing service tests for planned SL, planned inference, planned FL, blocked enrichment, and original payload persistence.
- [ ] Run the focused tests and verify failure.
- [ ] Implement the service by adapting into V2 and delegating to the shared planning pipeline.
- [ ] Store `upstream_coordination` and `context_enrichment` in the report without changing existing report keys.
- [ ] Run focused and existing partition service tests.
- [ ] Commit service integration.

### Task 4: Control Plane API

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Test: `tests/test_model_partition_api.py`

**Interfaces:**
- Produces: `POST /api/model-partition/coordination-plan`.
- Consumes: injected context providers from `ControlPlaneState`.

- [ ] Write failing API tests for successful plans and stable 422 blocked responses.
- [ ] Run the focused API tests and verify failure.
- [ ] Add provider injection, endpoint routing, and stable contract error translation.
- [ ] Run API and Control Plane tests.
- [ ] Commit API integration.

### Task 5: Research Console Input Source

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Adds input source `Federated Coordination 0.4`.
- Displays source plan ID, selected mode, participants, enrichment state, and existing plan/validation/reward/handoff results.

- [ ] Write failing UI contract tests for source selection and enrichment status containers.
- [ ] Run the focused UI tests and verify failure.
- [ ] Add a compact source selector, JSON input panel, and render mapping that reuses the four existing orchestration stages.
- [ ] Run UI tests and manually verify existing examples still work.
- [ ] Commit UI integration.

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/experiments/model_partition_orchestrator_experiment_guide.md`

**Interfaces:**
- Documents the upstream/downstream boundary and exact API example.

- [ ] Add the schema 0.4 flow, provider requirements, and fail-closed bandwidth behavior.
- [ ] Run `python -m pytest`.
- [ ] Run `go test ./...` from `go/aiops-guard`.
- [ ] Run a local API smoke test for FL, SL, and PARTITIONED examples.
- [ ] Review `git diff --check` and repository status.
- [ ] Commit documentation and verification evidence.

