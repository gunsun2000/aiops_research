# Model Partition Orchestration Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible Model Partition Orchestration Agent that consumes an approved upstream round plan, generates and validates logical model partitions, evaluates predicted outcomes, and exposes identical results through CLI and the research web platform.

**Architecture:** The partition subsystem is a second domain runtime beside the existing recovery runtime. Typed partition contracts, a deterministic planner, an independent validator, and an evaluator are composed by one service function used by both CLI and FastAPI. Existing recovery actions, AIOpsLab, AutoGen, and Kubernetes command guards remain unchanged.

**Tech Stack:** Python 3.11+, dataclasses, standard-library JSON/path utilities, argparse, FastAPI, vanilla HTML/CSS/JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-model-partition-orchestration-agent-design.md`

## Global Constraints

- Do not select or semantically validate FL, SL, or inference mode; only require upstream approval metadata.
- Do not convert `PartitionExecutionPlan` into `RecoveryAction`.
- Do not add the partition Agent to an existing recovery protocol profile.
- Predicted metrics and reward must be labeled as estimates.
- Do not add a third-party runtime dependency.
- Preserve every existing CLI command, API route, recovery artifact, AIOpsLab path, and AutoGen path.
- Do not commit or push without an explicit user request.

---

### Task 1: Partition Domain Contracts and Input Parsing

**Files:**
- Create: `src/aiops_k8s_agents/partition_models.py`
- Create: `tests/test_partition_models.py`
- Create: `config/examples/model_partition_job.json`

**Interfaces:**
- Produces: `ApprovedExecutionMode`, `ModelLayer`, `ResourceDevice`, `NetworkLink`, `PartitionConstraints`, `FederatedRoundPlan`, `LogicalPartition`, `ExecutionGraphNode`, `ExecutionGraphEdge`, `PartitionCandidate`, `PartitionExecutionPlan`, `PartitionFailure`, and `PartitionContractError`.
- Produces: `FederatedRoundPlan.from_dict(payload)`, `PartitionExecutionPlan.to_dict()`, and canonical JSON-safe dictionaries for later CLI/API use.

- [ ] **Step 1: Write failing contract tests**

```python
def test_round_plan_requires_upstream_mode_approval():
    payload = example_payload()
    payload["execution_mode"]["approved"] = False
    with pytest.raises(PartitionContractError, match="approved_mode_required"):
        FederatedRoundPlan.from_dict(payload)

def test_round_plan_rejects_unknown_participant_device():
    payload = example_payload()
    payload["participants"] = ["edge-a", "missing-device"]
    with pytest.raises(PartitionContractError, match="unknown_participant"):
        FederatedRoundPlan.from_dict(payload)
```

- [ ] **Step 2: Run `python -m pytest tests/test_partition_models.py -q` and confirm failure because the module does not exist**
- [ ] **Step 3: Implement immutable dataclasses, strict numeric checks, unique IDs, participant/device/link validation, and JSON conversion**
- [ ] **Step 4: Add an executable example with six ordered layers, two devices, a bidirectional link snapshot, approved mode provenance, and explicit SLO/headroom constraints**
- [ ] **Step 5: Run `python -m pytest tests/test_partition_models.py -q` and confirm all contract tests pass**

### Task 2: Deterministic Planning and Bounded Replanning

**Files:**
- Create: `src/aiops_k8s_agents/model_partition_agent.py`
- Create: `tests/test_model_partition_agent.py`
- Create: `config/model_partition_policy.json`
- Create: `config/examples/model_partition_failure.json`

**Interfaces:**
- Consumes: `FederatedRoundPlan`, `PartitionFailure`, optional previous `PartitionExecutionPlan`.
- Produces: `ModelPartitionPolicy.from_path(path)`.
- Produces: `ModelPartitionOrchestrationAgent.plan(round_plan) -> PartitionExecutionPlan`; safe failures use `selected_candidate=None`, stable `errors`, and `human_review_required=True`.
- Produces: `ModelPartitionOrchestrationAgent.replan(round_plan, previous_plan, failure, attempt) -> PartitionExecutionPlan`.

- [ ] **Step 1: Write failing planner tests**

```python
def test_planner_selects_lowest_scored_feasible_split(example_round_plan):
    plan = ModelPartitionOrchestrationAgent(example_policy()).plan(example_round_plan)
    assert plan.valid is True
    assert plan.selected_candidate.split_points == (3,)
    assert tuple(layer for part in plan.selected_candidate.partitions for layer in part.layer_names) == tuple(
        layer.name for layer in example_round_plan.layers
    )

def test_planner_rejects_memory_overflow_candidate(memory_constrained_round_plan):
    plan = ModelPartitionOrchestrationAgent(example_policy()).plan(memory_constrained_round_plan)
    assert any("memory_capacity_exceeded" in reason for candidate in plan.alternative_candidates for reason in candidate.rejection_reasons)
```

- [ ] **Step 2: Run `python -m pytest tests/test_model_partition_agent.py -q` and confirm missing implementation failure**
- [ ] **Step 3: Implement contiguous split enumeration, partition construction, compute/memory/transfer estimates, candidate rejection, normalized scoring, and lexicographic tie-breaking**
- [ ] **Step 4: Add failing replanning tests for unavailable devices, memory overflow, latency violation, failed links, and exhausted attempts**
- [ ] **Step 5: Implement the explicit signal-to-exclusion mapping and return `human_review_required: true` when no bounded candidate remains**
- [ ] **Step 6: Run planner tests and confirm deterministic selected split and bounded failure behavior**

### Task 3: Independent Validation, Evaluation, and Artifacts

**Files:**
- Create: `src/aiops_k8s_agents/partition_validator.py`
- Create: `src/aiops_k8s_agents/partition_evaluator.py`
- Create: `src/aiops_k8s_agents/partition_artifacts.py`
- Create: `src/aiops_k8s_agents/partition_service.py`
- Create: `tests/test_partition_validator.py`
- Create: `tests/test_partition_evaluator.py`
- Create: `tests/test_partition_service.py`

**Interfaces:**
- Produces: `PartitionPlanValidator.validate(round_plan, plan) -> PartitionValidationResult`.
- Produces: `PartitionPlanEvaluator.evaluate(plan, validation, observed=None) -> PartitionEvaluation`.
- Produces: `run_partition_planning(payload, policy_path, artifact_root, observed=None) -> dict[str, Any]`.
- Produces: `write_partition_report(report, artifact_root) -> Path`.

- [ ] **Step 1: Write failing validator tests for missing layers, duplicate layers, order changes, unknown devices, graph cycles, missing network links, and SLO violations**
- [ ] **Step 2: Run validator tests and confirm failure before implementation**
- [ ] **Step 3: Implement independent checks without importing private planner helpers**
- [ ] **Step 4: Write failing evaluator tests**

```python
def test_predicted_reward_is_bounded_and_labeled(valid_plan, valid_validation):
    result = PartitionPlanEvaluator(example_policy()).evaluate(valid_plan, valid_validation)
    assert -1.0 <= result.reward <= 1.0
    assert result.evidence_level == "predicted"

def test_invalid_plan_cannot_receive_positive_reward(invalid_plan, invalid_validation):
    result = PartitionPlanEvaluator(example_policy()).evaluate(invalid_plan, invalid_validation)
    assert result.reward <= 0.0
```

- [ ] **Step 5: Implement versioned component calculations, observed-evidence substitution, reward clamping, and explicit estimated/observed labels**
- [ ] **Step 6: Write a failing service test requiring the persisted report and returned report to contain identical selected split, validation, evaluation, and policy version**
- [ ] **Step 7: Implement the shared orchestration service and atomic JSON artifact writing under `runs/model-partition/<plan-id>/report.json`**
- [ ] **Step 8: Run all Task 3 tests**

### Task 4: Agent Registry and CLI Integration

**Files:**
- Modify: `config/agent_registry.json`
- Modify: `src/aiops_k8s_agents/cli.py`
- Create: `tests/test_model_partition_cli.py`
- Modify: `tests/test_agent_registry.py` if the existing registry suite is present; otherwise extend `tests/test_agents.py`.

**Interfaces:**
- Produces registry profile `ModelPartitionOrchestrationAgent` with implementation ID `deterministic-model-partition`.
- Produces CLI commands `plan-model-partition` and `replan-model-partition`.

- [ ] **Step 1: Write a failing registry test that the new Agent is enabled, has only partition capabilities, and is absent from every recovery protocol profile**
- [ ] **Step 2: Run the registry test and confirm the profile is missing**
- [ ] **Step 3: Add bounded operations `partition_generate_candidates`, `partition_select_split`, `partition_build_execution_graph`, `partition_estimate_resource_demand`, and `partition_replan`**
- [ ] **Step 4: Write failing CLI tests that execute the example input, persist a report, reject unapproved mode input with non-zero exit, and produce a different plan or safe failure during replanning**
- [ ] **Step 5: Add argparse definitions and dispatch functions that call `run_partition_planning` rather than duplicating planner logic**
- [ ] **Step 6: Run `python -m pytest tests/test_model_partition_cli.py tests/test_agents.py -q` plus the registry test file**

### Task 5: FastAPI Model Partition API

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Create: `tests/test_model_partition_web.py`

**Interfaces:**
- Produces: `GET /api/model-partition/examples`.
- Produces: `POST /api/model-partition/plans`.
- Extends `create_app(..., model_partition_service=None, model_partition_artifact_root=None)` for deterministic tests.

- [ ] **Step 1: Write failing API tests for example discovery, successful planning, CLI/API selected-split parity, stable 422 errors, and report artifact creation**
- [ ] **Step 2: Run `python -m pytest tests/test_model_partition_web.py -q` and confirm 404 responses**
- [ ] **Step 3: Add an injectable API service, load the repository example, map `PartitionContractError` and no-feasible-plan errors to stable HTTP 422 details, and avoid exposing tracebacks**
- [ ] **Step 4: Run the API tests and the existing `tests/test_control_plane_web.py` suite**

### Task 6: AI Workload Orchestration Workspace

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `tests/test_control_plane_ui.py`
- Create: `tests/test_model_partition_ui.py`
- Modify: `README.md`

**Interfaces:**
- Adds primary workspace navigation ID `orchestration` without removing the four existing views.
- Consumes only `GET /api/model-partition/examples` and `POST /api/model-partition/plans`.

- [ ] **Step 1: Write failing UI contract tests requiring the new navigation item, approved-mode provenance, model/participant/resource summary, candidate table, partition graph, validation result, estimated reward label, artifact path, and API calls**
- [ ] **Step 2: Run the UI tests and confirm the new workspace markers are absent**
- [ ] **Step 3: Add a restrained orchestration workspace with sections `Input`, `Candidate Analysis`, `Selected Plan`, and `Validation & Evaluation`; keep detailed alternatives collapsed by default**
- [ ] **Step 4: Implement example loading, planning submission, structured errors, selected split rendering, accessible graph nodes/edges, and JSON report download**
- [ ] **Step 5: Add responsive layout constraints and no decorative gradients/orbs; preserve the current research-console palette and typography**
- [ ] **Step 6: Update README with the architectural boundary, one CLI example, one web startup path, and predicted-versus-observed evidence wording**
- [ ] **Step 7: Run all UI and documentation tests**

### Task 7: Full Regression and Manual Platform Verification

**Files:**
- Modify only files required by failures introduced by this feature.

**Interfaces:**
- Verifies the complete repository behavior and browser-visible workflow.

- [ ] **Step 1: Run `python -m pytest` and resolve only feature-related regressions**
- [ ] **Step 2: Run `go test ./...` from `go/aiops-guard` if that directory exists; record that it remains independent from partition validation**
- [ ] **Step 3: Start the control plane on a free local port and verify `/healthz`, `/api/model-partition/examples`, and one successful `POST /api/model-partition/plans`**
- [ ] **Step 4: Open the orchestration workspace in a browser, verify desktop and mobile layouts, execute the sample plan, and confirm no overlap, clipping, stale mock labels, or console errors**
- [ ] **Step 5: Compare the implementation against all 11 acceptance criteria in the design spec and report any remaining gap explicitly**
