# Model Partition Orchestrator Agent V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the current deterministic model partition planner into a versioned Training/Inference Model Partition Orchestrator Agent with common input processing, strategy plugins, scheduling handoff, bounded feedback replanning, and a staged research UI.

**Architecture:** Preserve the existing recovery profile and legacy partition API. Add a V2 planning request boundary that normalizes approved coordination plans and immutable system context, routes them through Training or Inference strategies, reuses the deterministic candidate pipeline, persists versioned plans, and accepts bounded scheduling/runtime feedback. The web workspace exposes Intake, Strategy, Candidate Analysis, and Handoff/Feedback without claiming actual runtime execution.

**Tech Stack:** Python 3.13, dataclasses, FastAPI/Pydantic, JSON configuration and artifacts, vanilla HTML/CSS/JavaScript, pytest, existing Go Guard regression suite.

**Spec:** `docs/superpowers/specs/2026-08-20-model-partition-orchestrator-agent-v2-design.md`

## Global Constraints

- Existing Recovery Profile, recovery CLI, recovery API, and recovery UI behavior must remain unchanged.
- Existing `plan-model-partition`, `replan-model-partition`, `GET /api/model-partition/examples`, and `POST /api/model-partition/plans` contracts must remain compatible.
- The orchestrator consumes approved execution modes; it never selects FL, SL, or inference modes.
- The external Scheduling Agent and actual training/inference runtime are not implemented in this repository.
- Predicted metrics and rewards must never be labeled as observed runtime results.
- Unknown plan types, missing approval provenance, invalid model versions, and infeasible plans fail closed.
- Replanning is bounded by versioned policy and terminates with human review when exhausted.
- Identical normalized input, context snapshot, strategy, and policy versions produce the same deterministic signature.
- Python tests and `cd go/aiops-guard && go test ./...` must pass before completion.

---

## File Structure

### New domain modules

- `src/aiops_k8s_agents/partition_coordination.py`: V2 coordination envelopes, Training/Inference payloads, normalized planning request, and legacy adapter.
- `src/aiops_k8s_agents/partition_context.py`: model profile, workload forecast, immutable system context, canonical serialization, and snapshot hashing.
- `src/aiops_k8s_agents/partition_strategies.py`: strategy protocol, `PartitionIntent`, Inference strategy, and Training strategy.
- `src/aiops_k8s_agents/partition_repository.py`: atomic versioned plan and feedback persistence.
- `src/aiops_k8s_agents/partition_feedback.py`: feedback contracts, classification, and bounded replan request generation.

### Existing modules to modify

- `src/aiops_k8s_agents/partition_models.py`: add V2 plan metadata, explanation, warning, confidence, handoff, and deterministic signature fields while preserving legacy deserialization.
- `src/aiops_k8s_agents/model_partition_agent.py`: become the orchestration facade over common processing, strategy selection, and deterministic candidate planning.
- `src/aiops_k8s_agents/partition_validator.py`: validate V2 provenance, version, strategy, graph, and signature invariants.
- `src/aiops_k8s_agents/partition_evaluator.py`: strategy-specific predicted/observed components and explicit evidence labels.
- `src/aiops_k8s_agents/partition_service.py`: accept legacy or V2 requests, persist versions, create handoff, and process feedback.
- `src/aiops_k8s_agents/partition_artifacts.py`: persist normalized input, intent, plan, handoff, feedback, and history artifacts atomically.
- `src/aiops_k8s_agents/control_plane_web.py`: expose strategy, plan detail, feedback, and history APIs.
- `src/aiops_k8s_agents/cli.py`: add V2 input and feedback commands without removing legacy commands.
- `config/model_partition_policy.json`: add strategy policies, confidence, versioning, and feedback limits.
- `config/examples/model_partition_job.json`: retain legacy example.
- `config/examples/model_partition_inference_v2.json`: add approved inference example.
- `config/examples/model_partition_training_v2.json`: add approved training example.
- `ui/control_plane_static/index.html`: stage the orchestration workspace into four sections.
- `ui/control_plane_static/app.js`: load V2 inputs, render stage outputs, submit feedback, and show history.
- `ui/control_plane_static/styles.css`: responsive staged workspace and graph/history presentation.

### New and modified tests

- `tests/test_partition_coordination.py`
- `tests/test_partition_context.py`
- `tests/test_partition_strategies.py`
- `tests/test_partition_repository.py`
- `tests/test_partition_feedback.py`
- `tests/test_partition_models.py`
- `tests/test_model_partition_agent.py`
- `tests/test_partition_validator.py`
- `tests/test_partition_evaluator.py`
- `tests/test_partition_service.py`
- `tests/test_model_partition_api.py`
- `tests/test_model_partition_cli.py`
- `tests/test_control_plane_ui.py`

---

### Task 1: V2 Coordination and Immutable Context Contracts

**Files:**
- Create: `src/aiops_k8s_agents/partition_coordination.py`
- Create: `src/aiops_k8s_agents/partition_context.py`
- Create: `tests/test_partition_coordination.py`
- Create: `tests/test_partition_context.py`
- Modify: `config/examples/model_partition_inference_v2.json`
- Modify: `config/examples/model_partition_training_v2.json`

**Interfaces:**
- Produces: `CoordinationPlanEnvelope.from_dict(payload)`
- Produces: `TrainingCoordinationPlan.from_dict(payload)`
- Produces: `InferenceCoordinationPlan.from_dict(payload)`
- Produces: `PartitionSystemContext.from_dict(payload)`
- Produces: `PartitionPlanningRequest.from_dict(payload)`
- Produces: `PartitionSystemContext.deterministic_hash() -> str`
- Consumes: Existing `PartitionContractError`, `ResourceDevice`, `NetworkLink`, and `PartitionConstraints`.

- [ ] **Step 1: Write failing approval and routing contract tests**

```python
def test_v2_request_requires_approved_plan_provenance(inference_payload):
    inference_payload["coordination_plan"]["approved_by"] = ""
    with pytest.raises(PartitionContractError) as error:
        PartitionPlanningRequest.from_dict(inference_payload)
    assert error.value.code == "approval_provenance_required"


def test_v2_request_routes_inference_payload(inference_payload):
    request = PartitionPlanningRequest.from_dict(inference_payload)
    assert request.envelope.plan_type == "inference"
    assert isinstance(request.plan, InferenceCoordinationPlan)
    assert request.plan.approved_model_version == "transformer-v3"
```

- [ ] **Step 2: Run contract tests and verify missing modules fail**

Run: `python -m pytest tests/test_partition_coordination.py -q`

Expected: FAIL because `partition_coordination` is not defined.

- [ ] **Step 3: Implement strict coordination contracts**

```python
@dataclass(frozen=True)
class CoordinationPlanEnvelope:
    plan_type: str
    plan_id: str
    job_id: str
    approved_by: str
    approval_ref: str
    approved_at: str
    schema_version: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CoordinationPlanEnvelope":
        if payload.get("approved") is not True:
            raise PartitionContractError("approved_plan_required", "coordination plan must be approved")
        plan_type = _text(payload.get("plan_type"), "coordination_plan.plan_type")
        if plan_type not in {"training", "inference"}:
            raise PartitionContractError("unsupported_plan_type", f"unsupported plan type: {plan_type}")
        approved_by = str(payload.get("approved_by") or "").strip()
        approval_ref = str(payload.get("approval_ref") or "").strip()
        if not approved_by or not approval_ref:
            raise PartitionContractError("approval_provenance_required", "approved_by and approval_ref are required")
        return cls(
            plan_type=plan_type,
            plan_id=_text(payload.get("plan_id"), "coordination_plan.plan_id"),
            job_id=_text(payload.get("job_id"), "coordination_plan.job_id"),
            approved_by=approved_by,
            approval_ref=approval_ref,
            approved_at=_text(payload.get("approved_at"), "coordination_plan.approved_at"),
            schema_version=_text(payload.get("schema_version"), "coordination_plan.schema_version"),
        )
```

- [ ] **Step 4: Write failing immutable snapshot and hash tests**

```python
def test_context_hash_is_stable_for_key_order(context_payload):
    first = PartitionSystemContext.from_dict(context_payload)
    reordered = json.loads(json.dumps(context_payload, sort_keys=True))
    second = PartitionSystemContext.from_dict(reordered)
    assert first.deterministic_hash() == second.deterministic_hash()


def test_model_version_mismatch_fails_closed(inference_payload):
    inference_payload["system_context"]["model_registry_context"]["approved_model_version"] = "transformer-v2"
    with pytest.raises(PartitionContractError) as error:
        PartitionPlanningRequest.from_dict(inference_payload)
    assert error.value.code == "model_version_mismatch"
```

- [ ] **Step 5: Implement canonical context serialization and hashing**

```python
def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class PartitionSystemContext:
    snapshot_id: str
    snapshot_version: str
    collected_at: str
    model_structure_profile: ModelStructureProfile
    model_registry_context: ModelRegistryContext
    devices: tuple[ResourceDevice, ...]
    network_links: tuple[NetworkLink, ...]
    workload_forecast: WorkloadForecast | None

    def deterministic_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Add complete inference and training V2 examples**

The examples must contain approved provenance, model version, model blocks, devices, network links, constraints, and a versioned snapshot. The inference example uses `plan_type=inference`; the training example uses `plan_type=training` with an approved `pipeline_parallel` coordination mode.

- [ ] **Step 7: Run contract tests**

Run: `python -m pytest tests/test_partition_coordination.py tests/test_partition_context.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/aiops_k8s_agents/partition_coordination.py src/aiops_k8s_agents/partition_context.py tests/test_partition_coordination.py tests/test_partition_context.py config/examples/model_partition_inference_v2.json config/examples/model_partition_training_v2.json
git commit -m "Add versioned partition coordination contracts"
```

### Task 2: Legacy Adapter and Common Processing Core

**Files:**
- Modify: `src/aiops_k8s_agents/partition_coordination.py`
- Create: `src/aiops_k8s_agents/partition_common.py`
- Modify: `tests/test_partition_coordination.py`
- Create: `tests/test_partition_common.py`

**Interfaces:**
- Consumes: `PartitionPlanningRequest`, existing `FederatedRoundPlan` payload.
- Produces: `LegacyFederatedRoundPlanAdapter.adapt(payload) -> PartitionPlanningRequest`
- Produces: `PartitionCommonProcessor.process(request) -> NormalizedPartitionRequest`
- Produces: stable `input_signature` from normalized input and context hash.

- [ ] **Step 1: Write failing legacy compatibility test**

```python
def test_legacy_adapter_preserves_existing_job_and_candidate_inputs(legacy_payload):
    request = LegacyFederatedRoundPlanAdapter().adapt(legacy_payload)
    normalized = PartitionCommonProcessor().process(request)
    assert normalized.job_id == legacy_payload["job_id"]
    assert normalized.model_id == legacy_payload["model_id"]
    assert normalized.plan_type == "inference"
    assert normalized.legacy_input is True
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m pytest tests/test_partition_common.py::test_legacy_adapter_preserves_existing_job_and_candidate_inputs -q`

Expected: FAIL because adapter and processor are missing.

- [ ] **Step 3: Implement the legacy adapter**

The adapter maps the current approved execution mode, ordered layers, participants, devices, links, and constraints into a synthetic versioned inference request. It records `legacy_input=true`, `schema_version=legacy-1.0`, and derives a deterministic model version from the legacy `model_id`. It does not invent observed runtime data.

- [ ] **Step 4: Write failing early-feasibility tests**

```python
def test_common_processor_rejects_missing_model_profile(inference_request):
    request = replace(inference_request, context=replace(inference_request.context, model_structure_profile=None))
    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)
    assert error.value.code == "model_profile_missing"


def test_common_processor_rejects_missing_participant_device(inference_request):
    request = request_without_participant_device(inference_request, "gpu-worker-01")
    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)
    assert error.value.code == "early_feasibility_failed"
```

- [ ] **Step 5: Implement normalization, routing metadata, and early checks**

```python
@dataclass(frozen=True)
class NormalizedPartitionRequest:
    plan_type: str
    job_id: str
    model_id: str
    approved_model_version: str
    approved_execution_mode: ApprovedExecutionMode
    participants: tuple[str, ...]
    layers: tuple[ModelLayer, ...]
    devices: tuple[ResourceDevice, ...]
    network_links: tuple[NetworkLink, ...]
    constraints: PartitionConstraints
    context_snapshot_id: str
    context_snapshot_hash: str
    input_signature: str
    legacy_input: bool
```

- [ ] **Step 6: Run new tests plus current model tests**

Run: `python -m pytest tests/test_partition_coordination.py tests/test_partition_context.py tests/test_partition_common.py tests/test_partition_models.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/aiops_k8s_agents/partition_coordination.py src/aiops_k8s_agents/partition_common.py tests/test_partition_coordination.py tests/test_partition_common.py
git commit -m "Add partition common processing and legacy adapter"
```

### Task 3: Strategy Protocol and Inference Strategy

**Files:**
- Create: `src/aiops_k8s_agents/partition_strategies.py`
- Create: `tests/test_partition_strategies.py`
- Modify: `config/model_partition_policy.json`

**Interfaces:**
- Consumes: `NormalizedPartitionRequest`.
- Produces: `PartitionStrategy.build_partition_intent(request) -> PartitionIntent`.
- Produces: `PartitionStrategyRegistry.resolve(plan_type, mode) -> PartitionStrategy`.
- Produces: `InferencePartitionStrategy` with explicit split, graph, memory, and objective rules.

- [ ] **Step 1: Write failing strategy routing tests**

```python
def test_registry_routes_inference_request(normalized_inference_request):
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized_inference_request.plan_type,
        normalized_inference_request.approved_execution_mode.name,
    )
    assert strategy.strategy_id == "inference-partition-v1"


def test_registry_fails_closed_for_unknown_mode(normalized_inference_request):
    with pytest.raises(PartitionContractError) as error:
        PartitionStrategyRegistry.default().resolve("inference", "unknown-mode")
    assert error.value.code == "strategy_not_supported"
```

- [ ] **Step 2: Run the strategy tests and verify failure**

Run: `python -m pytest tests/test_partition_strategies.py -q`

Expected: FAIL because the strategy module is missing.

- [ ] **Step 3: Implement immutable intent and strategy registry**

```python
@dataclass(frozen=True)
class PartitionIntent:
    strategy_id: str
    strategy_version: str
    allowed_partition_methods: tuple[str, ...]
    allowed_split_boundaries: tuple[int, ...]
    forbidden_split_boundaries: tuple[int, ...]
    graph_requirements: tuple[str, ...]
    memory_rules: tuple[str, ...]
    communication_rules: tuple[str, ...]
    optimization_objectives: tuple[str, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
```

- [ ] **Step 4: Implement inference strategy rules**

The first inference strategy supports approved `split_inference`, `pipeline_parallel`, and the legacy approved mode. It produces a forward-only graph requirement, activation-transfer communication rule, parameter/working-memory/activation memory rule, and latency/memory/communication objectives. Missing forecasts add a warning and reduce later confidence without invalidating the request.

- [ ] **Step 5: Extend policy configuration**

```json
{
  "strategy_policies": {
    "inference-partition-v1": {
      "supported_modes": ["split_inference", "pipeline_parallel", "legacy_approved_mode"],
      "objectives": {
        "latency": 0.5,
        "memory_pressure": 0.3,
        "communication": 0.2
      }
    }
  },
  "confidence": {
    "base": 0.95,
    "missing_forecast_penalty": 0.15,
    "legacy_input_penalty": 0.10
  }
}
```

- [ ] **Step 6: Run strategy and policy regression tests**

Run: `python -m pytest tests/test_partition_strategies.py tests/test_model_partition_agent.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/aiops_k8s_agents/partition_strategies.py tests/test_partition_strategies.py config/model_partition_policy.json
git commit -m "Add inference partition strategy routing"
```

### Task 4: Refactor the Orchestrator Facade and V2 Plan Metadata

**Files:**
- Modify: `src/aiops_k8s_agents/partition_models.py`
- Modify: `src/aiops_k8s_agents/model_partition_agent.py`
- Modify: `tests/test_partition_models.py`
- Modify: `tests/test_model_partition_agent.py`

**Interfaces:**
- Consumes: `NormalizedPartitionRequest`, `PartitionIntent`, existing `ModelPartitionPolicy`.
- Produces: `ModelPartitionOrchestrationAgent.plan_request(request) -> PartitionExecutionPlan`.
- Preserves: `ModelPartitionOrchestrationAgent.plan(FederatedRoundPlan)`.
- Extends: `PartitionExecutionPlan` with versions, snapshot hash, explanations, warnings, confidence, and deterministic signature.

- [ ] **Step 1: Write failing V2 plan metadata tests**

```python
def test_v2_plan_records_strategy_snapshot_and_signature(orchestrator, inference_request):
    plan = orchestrator.plan_request(inference_request)
    assert plan.plan_version == 1
    assert plan.parent_plan_id is None
    assert plan.plan_type == "inference"
    assert plan.strategy_id == "inference-partition-v1"
    assert len(plan.input_snapshot_hash) == 64
    assert len(plan.deterministic_signature) == 64
    assert 0.0 <= plan.confidence <= 1.0
```

- [ ] **Step 2: Run test and verify missing fields fail**

Run: `python -m pytest tests/test_model_partition_agent.py::test_v2_plan_records_strategy_snapshot_and_signature -q`

Expected: FAIL because V2 fields are not defined.

- [ ] **Step 3: Extend `PartitionExecutionPlan` with backward-compatible defaults**

New fields must have defaults in `from_dict` so legacy artifacts remain readable:

```python
plan_version: int = 1
parent_plan_id: str | None = None
plan_type: str = "inference"
approved_model_version: str = "legacy"
strategy_id: str = "legacy-partition-v1"
strategy_version: str = "1.0"
input_snapshot_id: str = "legacy-snapshot"
input_snapshot_hash: str = ""
assumptions: tuple[str, ...] = ()
warnings: tuple[str, ...] = ()
confidence: float = 0.0
deterministic_signature: str = ""
handoff_status: str = "not_ready"
```

- [ ] **Step 4: Refactor planning into V2 facade without changing candidate math**

`plan_request()` runs common processing and strategy selection, then invokes the existing deterministic candidate construction. The legacy `plan()` path uses `LegacyFederatedRoundPlanAdapter` and must preserve the current selected split `(3,)`, candidate count, scores, and estimates.

- [ ] **Step 5: Calculate deterministic signature excluding generated IDs and timestamps**

```python
signature_payload = {
    "input_signature": normalized.input_signature,
    "strategy_id": intent.strategy_id,
    "strategy_version": intent.strategy_version,
    "policy_version": self.policy.version,
    "selected_candidate": selected.to_dict() if selected else None,
}
deterministic_signature = hashlib.sha256(canonical_json(signature_payload).encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Run current and V2 planner tests**

Run: `python -m pytest tests/test_partition_models.py tests/test_model_partition_agent.py -q`

Expected: PASS, including existing numerical assertions.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/aiops_k8s_agents/partition_models.py src/aiops_k8s_agents/model_partition_agent.py tests/test_partition_models.py tests/test_model_partition_agent.py
git commit -m "Refactor partition planner into V2 orchestrator facade"
```

### Task 5: Training Partition Strategy and Training Graphs

**Files:**
- Modify: `src/aiops_k8s_agents/partition_strategies.py`
- Modify: `src/aiops_k8s_agents/model_partition_agent.py`
- Modify: `src/aiops_k8s_agents/partition_models.py`
- Modify: `tests/test_partition_strategies.py`
- Create: `tests/test_training_partition_strategy.py`
- Modify: `config/model_partition_policy.json`

**Interfaces:**
- Produces: `TrainingPartitionStrategy`.
- Extends: graph edges with `edge_type` values `forward`, `backward`, `gradient`, `aggregation`.
- Produces: training estimates `estimated_step_time_ms`, `gradient_transfer_bytes`, and `maximum_load_imbalance`.

- [ ] **Step 1: Write failing Training strategy tests**

```python
def test_training_strategy_builds_forward_and_backward_graph(training_request, orchestrator):
    plan = orchestrator.plan_request(training_request)
    selected = plan.selected_candidate
    assert selected is not None
    edge_types = {edge.edge_type for edge in selected.graph_edges}
    assert {"forward", "backward"}.issubset(edge_types)
    assert selected.estimated_step_time_ms > 0


def test_training_strategy_rejects_forbidden_split_boundary(training_request, orchestrator):
    plan = orchestrator.plan_request(training_request)
    assert all(
        2 not in candidate.split_points
        for candidate in (plan.selected_candidate, *plan.alternative_candidates)
        if candidate is not None
    )
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_training_partition_strategy.py -q`

Expected: FAIL because Training strategy and typed graph edges are missing.

- [ ] **Step 3: Implement Training strategy intent**

Support approved `pipeline_parallel`, `split_learning`, and `hybrid_partition` modes. Generate forward/backward requirements, gradient communication, checkpoint boundaries, and step-time/load-balance objectives from the approved plan and model profile.

- [ ] **Step 4: Extend candidate graph and estimates**

Maintain legacy forward edges as `edge_type=forward`. Training candidates add reverse backward edges and gradient/aggregation edges only when required by the approved coordination plan. Validator cycle logic must operate on dependency phase ordering rather than treating the intentional backward phase as an invalid structural cycle.

- [ ] **Step 5: Add Training policy weights**

```json
"training-partition-v1": {
  "supported_modes": ["pipeline_parallel", "split_learning", "hybrid_partition"],
  "objectives": {
    "step_time": 0.35,
    "load_balance": 0.20,
    "memory_pressure": 0.20,
    "communication": 0.15,
    "resilience": 0.10
  }
}
```

- [ ] **Step 6: Run Training and inference regression tests**

Run: `python -m pytest tests/test_training_partition_strategy.py tests/test_partition_strategies.py tests/test_model_partition_agent.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/aiops_k8s_agents/partition_strategies.py src/aiops_k8s_agents/model_partition_agent.py src/aiops_k8s_agents/partition_models.py tests/test_partition_strategies.py tests/test_training_partition_strategy.py config/model_partition_policy.json
git commit -m "Add training model partition strategy"
```

### Task 6: Independent V2 Validation and Strategy-Specific Evaluation

**Files:**
- Modify: `src/aiops_k8s_agents/partition_validator.py`
- Modify: `src/aiops_k8s_agents/partition_evaluator.py`
- Modify: `tests/test_partition_validator.py`
- Modify: `tests/test_partition_evaluator.py`

**Interfaces:**
- Extends: `PartitionPlanValidator.validate(request, plan)` while preserving legacy `validate(round_plan, plan)`.
- Extends: `PartitionEvaluation` with `confidence`, `strategy_id`, and explicit `predicted`/`observed` labels.
- Produces: Training and inference evaluation components from policy.

- [ ] **Step 1: Write failing provenance and signature validation tests**

```python
def test_validator_rejects_snapshot_hash_mismatch(v2_request, valid_v2_plan):
    tampered = replace(valid_v2_plan, input_snapshot_hash="0" * 64)
    result = PartitionPlanValidator().validate(v2_request, tampered)
    assert result.valid is False
    assert "input_snapshot_hash_mismatch" in result.errors


def test_validator_rejects_strategy_plan_type_mismatch(training_request, inference_plan):
    result = PartitionPlanValidator().validate(training_request, inference_plan)
    assert "strategy_plan_type_mismatch" in result.errors
```

- [ ] **Step 2: Run validation tests and verify failure**

Run: `python -m pytest tests/test_partition_validator.py -q`

Expected: FAIL because V2 invariants are unchecked.

- [ ] **Step 3: Implement V2 validation dispatch**

Add rules for approval provenance, model version, plan type, strategy version, snapshot hash, deterministic signature, Training phase graph, inference forward graph, memory, network links, and explicit SLA constraints. Do not duplicate planner scoring logic.

- [ ] **Step 4: Write failing evidence-label and strategy component tests**

```python
def test_inference_evaluation_is_explicitly_predicted(v2_request, valid_v2_plan, validation, policy):
    result = PartitionPlanEvaluator(policy).evaluate(v2_request, valid_v2_plan, validation)
    assert result.evidence_level == "predicted"
    assert result.estimated is True
    assert "latency_efficiency" in result.components
    assert result.confidence == valid_v2_plan.confidence


def test_training_evaluation_uses_step_time_and_balance(training_request, training_plan, validation, policy):
    result = PartitionPlanEvaluator(policy).evaluate(training_request, training_plan, validation)
    assert "step_time_efficiency" in result.components
    assert "load_balance" in result.components
```

- [ ] **Step 5: Implement strategy-specific evaluator components**

Observed metrics only switch `evidence_level` to `observed` when the caller provides runtime evidence with a source and timestamp. Predicted results remain labeled `Estimated reward (predicted evidence)`.

- [ ] **Step 6: Run validator and evaluator suites**

Run: `python -m pytest tests/test_partition_validator.py tests/test_partition_evaluator.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/aiops_k8s_agents/partition_validator.py src/aiops_k8s_agents/partition_evaluator.py tests/test_partition_validator.py tests/test_partition_evaluator.py
git commit -m "Validate and evaluate V2 partition plans"
```

### Task 7: Versioned Plan Repository and Scheduling Handoff

**Files:**
- Create: `src/aiops_k8s_agents/partition_repository.py`
- Modify: `src/aiops_k8s_agents/partition_artifacts.py`
- Create: `tests/test_partition_repository.py`
- Modify: `tests/test_partition_service.py`

**Interfaces:**
- Produces: `PartitionPlanRepository.save(report) -> Path`
- Produces: `PartitionPlanRepository.get(plan_id, version=None) -> dict`
- Produces: `PartitionPlanRepository.history(plan_id) -> tuple[dict, ...]`
- Produces: `SchedulingHandoff.create(plan) -> SchedulingHandoff`

- [ ] **Step 1: Write failing atomic version repository tests**

```python
def test_repository_saves_versioned_plan_and_latest_pointer(tmp_path, report_v1):
    repository = PartitionPlanRepository(tmp_path)
    repository.save(report_v1)
    assert repository.get(report_v1["plan"]["plan_id"])["plan"]["plan_version"] == 1
    assert repository.history(report_v1["plan"]["plan_id"])[0]["plan"]["plan_version"] == 1


def test_repository_rejects_duplicate_version_with_different_signature(tmp_path, report_v1):
    repository = PartitionPlanRepository(tmp_path)
    repository.save(report_v1)
    tampered = copy.deepcopy(report_v1)
    tampered["plan"]["deterministic_signature"] = "0" * 64
    with pytest.raises(PartitionContractError) as error:
        repository.save(tampered)
    assert error.value.code == "plan_version_conflict"
```

- [ ] **Step 2: Run repository tests and verify failure**

Run: `python -m pytest tests/test_partition_repository.py -q`

Expected: FAIL because repository is missing.

- [ ] **Step 3: Implement atomic plan persistence**

Store each version at `<root>/<plan_id>/versions/<version>/report.json`, write through a temporary file, and atomically replace `<root>/<plan_id>/latest.json`. Maintain `history.json` with plan ID, version, parent, signature, status, and created timestamp.

- [ ] **Step 4: Implement Scheduling Handoff contract**

```python
@dataclass(frozen=True)
class SchedulingHandoff:
    handoff_id: str
    partition_plan_id: str
    partition_plan_version: int
    created_at: str
    status: str
    scheduler_ref: str | None

    @classmethod
    def create(cls, plan: PartitionExecutionPlan, *, id_factory, clock):
        status = "ready" if plan.valid and plan.handoff_status == "ready" else "blocked"
        return cls(id_factory(), plan.plan_id, plan.plan_version, clock(), status, None)
```

- [ ] **Step 5: Extend Artifact output**

Persist `normalized_request.json`, `partition_intent.json`, `report.json`, and `scheduling_handoff.json`. Legacy `report.json` location remains readable.

- [ ] **Step 6: Run repository and service tests**

Run: `python -m pytest tests/test_partition_repository.py tests/test_partition_service.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```bash
git add src/aiops_k8s_agents/partition_repository.py src/aiops_k8s_agents/partition_artifacts.py tests/test_partition_repository.py tests/test_partition_service.py
git commit -m "Persist versioned partition plans and handoffs"
```

### Task 8: Feedback Analysis and Bounded Repartition

**Files:**
- Create: `src/aiops_k8s_agents/partition_feedback.py`
- Modify: `src/aiops_k8s_agents/partition_service.py`
- Modify: `src/aiops_k8s_agents/model_partition_agent.py`
- Create: `tests/test_partition_feedback.py`
- Modify: `tests/test_partition_service.py`

**Interfaces:**
- Produces: `PartitionRuntimeFeedback.from_dict(payload)`.
- Produces: `PartitionFeedbackAnalyzer.analyze(feedback, previous_plan) -> RepartitionDirective`.
- Produces: `run_partition_feedback(plan_id, feedback, repository, policy_path) -> dict`.
- Preserves: existing `PartitionFailure` replanning API through an adapter.

- [ ] **Step 1: Write failing feedback classification tests**

```python
@pytest.mark.parametrize(
    ("signal", "expected_exclusion"),
    [
        ("device_unavailable", "device"),
        ("transfer_failure", "link"),
        ("latency_slo_violation", "split"),
        ("placement_rejected", "candidate"),
    ],
)
def test_feedback_maps_to_bounded_exclusion(feedback_payload, previous_plan, signal, expected_exclusion):
    feedback_payload["signal"] = signal
    directive = PartitionFeedbackAnalyzer().analyze(
        PartitionRuntimeFeedback.from_dict(feedback_payload), previous_plan
    )
    assert directive.exclusion_type == expected_exclusion
```

- [ ] **Step 2: Run feedback tests and verify failure**

Run: `python -m pytest tests/test_partition_feedback.py -q`

Expected: FAIL because feedback contracts are missing.

- [ ] **Step 3: Implement feedback contract and analyzer**

Reject unknown signals with `unsupported_feedback_signal`. Require source, reason, received timestamp, plan ID, and plan version. Signal-specific device or link identifiers are mandatory.

- [ ] **Step 4: Write failing plan lineage and exhaustion tests**

```python
def test_feedback_replan_increments_version_and_links_parent(service, report_v1, latency_feedback):
    report_v2 = service.process_feedback(report_v1["plan"]["plan_id"], latency_feedback)
    assert report_v2["plan"]["plan_version"] == 2
    assert report_v2["plan"]["parent_plan_id"] == report_v1["plan"]["plan_id"]
    assert report_v2["replanning"]["reason"] == "latency_slo_violation"


def test_feedback_replan_exhaustion_requires_human_review(service, exhausted_plan, feedback):
    result = service.process_feedback(exhausted_plan.plan_id, feedback)
    assert result["status"] == "blocked"
    assert result["plan"]["human_review_required"] is True
    assert "replan_attempts_exhausted" in result["plan"]["errors"]
```

- [ ] **Step 5: Implement bounded versioned replanning service**

Load the latest report, verify feedback plan/version matches, create a directive, call the orchestrator with bounded exclusions, increment version, link the parent, validate, evaluate, create a new handoff, and persist feedback plus the new version. Never expand participants or relax hard constraints automatically.

- [ ] **Step 6: Run feedback and legacy replan tests**

Run: `python -m pytest tests/test_partition_feedback.py tests/test_partition_service.py tests/test_model_partition_agent.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 8**

```bash
git add src/aiops_k8s_agents/partition_feedback.py src/aiops_k8s_agents/partition_service.py src/aiops_k8s_agents/model_partition_agent.py tests/test_partition_feedback.py tests/test_partition_service.py
git commit -m "Add bounded partition feedback replanning"
```

### Task 9: Control Plane API and CLI Integration

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Modify: `src/aiops_k8s_agents/cli.py`
- Modify: `tests/test_model_partition_api.py`
- Modify: `tests/test_model_partition_cli.py`

**Interfaces:**
- Adds: `GET /api/model-partition/strategies`.
- Adds: `GET /api/model-partition/plans/{plan_id}`.
- Adds: `GET /api/model-partition/plans/{plan_id}/history`.
- Adds: `POST /api/model-partition/plans/{plan_id}/feedback`.
- Adds CLI: `plan-model-partition-v2` and `feedback-model-partition`.
- Preserves existing endpoints and commands.

- [ ] **Step 1: Write failing V2 API tests**

```python
def test_v2_plan_api_returns_versioned_handoff(client, inference_payload):
    response = client.post("/api/model-partition/plans", json={"request": inference_payload})
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["plan_version"] == 1
    assert body["scheduling_handoff"]["status"] == "ready"


def test_feedback_api_returns_replanned_version(client, stored_plan, latency_feedback):
    response = client.post(
        f"/api/model-partition/plans/{stored_plan['plan']['plan_id']}/feedback",
        json=latency_feedback,
    )
    assert response.status_code == 200
    assert response.json()["plan"]["plan_version"] == 2
```

- [ ] **Step 2: Run API tests and verify failure**

Run: `python -m pytest tests/test_model_partition_api.py -q`

Expected: FAIL for missing V2 route behavior.

- [ ] **Step 3: Add request models and API routes**

Map `PartitionContractError` to HTTP 400 with `{error_code, message}`. Missing plan is HTTP 404. Version conflict is HTTP 409. Unexpected exceptions remain server-side and return a stable generic 500 message with plan/job ID when available.

- [ ] **Step 4: Write failing CLI tests**

```python
def test_plan_model_partition_v2_cli_emits_versioned_plan(cli_runner, inference_file):
    result = cli_runner("plan-model-partition-v2", "--input", str(inference_file))
    assert result["plan"]["plan_version"] == 1
    assert result["scheduling_handoff"]["status"] == "ready"


def test_feedback_model_partition_cli_emits_child_plan(cli_runner, feedback_file, plan_id):
    result = cli_runner("feedback-model-partition", "--plan-id", plan_id, "--feedback", str(feedback_file))
    assert result["plan"]["parent_plan_id"] == plan_id
```

- [ ] **Step 5: Implement CLI commands using the same service functions**

Do not duplicate parsing or planning logic inside `cli.py`. CLI prints the same report schema as the API and returns non-zero only for invalid requests or infrastructure errors; safe planning failure remains a structured report.

- [ ] **Step 6: Run API, CLI, and web regression tests**

Run: `python -m pytest tests/test_model_partition_api.py tests/test_model_partition_cli.py tests/test_control_plane_web.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 9**

```bash
git add src/aiops_k8s_agents/control_plane_web.py src/aiops_k8s_agents/cli.py tests/test_model_partition_api.py tests/test_model_partition_cli.py
git commit -m "Expose V2 partition planning and feedback APIs"
```

### Task 10: Four-Stage Orchestration Workspace

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: V2 examples, plan report, strategy catalog, feedback and history APIs.
- Produces: visible `Plan Intake`, `Partition Strategy`, `Candidate Analysis`, and `Handoff & Feedback` stages.
- Preserves: recovery, AIOpsLab, Agent, and result views.

- [ ] **Step 1: Write failing static UI contract tests**

```python
def test_orchestration_workspace_has_four_research_stages(index_html):
    for label in ("Plan Intake", "Partition Strategy", "Candidate Analysis", "Handoff & Feedback"):
        assert label in index_html


def test_orchestration_workspace_marks_predicted_results(index_html):
    assert "실행 전 예측" in index_html
    assert "실제 Runtime 결과가 아닙니다" in index_html
```

- [ ] **Step 2: Run UI tests and verify failure**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: FAIL because staged labels and controls are absent.

- [ ] **Step 3: Replace the current partition workspace with a staged layout**

The header offers explicit `Inference 샘플`, `Training 샘플`, and `계획 생성`. The main surface contains a horizontal four-stage progress indicator. Only the selected stage displays full details; the other stages display one-line summaries. Do not nest cards inside cards.

- [ ] **Step 4: Implement Plan Intake and Strategy rendering**

Render plan type, provenance, model/version, snapshot/version, participants, forecast, strategy/version, split boundaries, graph requirements, objectives, assumptions, and warnings. The plan button is disabled until the input is valid.

- [ ] **Step 5: Implement Candidate Analysis rendering**

Render candidate validity, strategy-specific performance metric, memory, communication, score, hard-rejection reason, selected partitions, and execution graph. Keep stable dimensions so candidate count does not shift the layout.

- [ ] **Step 6: Implement Handoff, feedback, and plan history rendering**

Render Validator result, predicted reward, confidence, plan version, snapshot hash prefix, handoff status, and version timeline. Provide bounded feedback controls for supported signals. Clearly label feedback simulation when no external Scheduler exists.

- [ ] **Step 7: Add responsive styling and accessibility**

Use the existing navy/white research console palette, 4px to 6px radius, visible focus states, buttons with existing icon conventions, no decorative gradients, and no viewport-scaled fonts. At widths below 900px, stack stage content without horizontal page overflow.

- [ ] **Step 8: Run UI and API tests**

Run: `python -m pytest tests/test_control_plane_ui.py tests/test_model_partition_api.py -q`

Expected: PASS.

- [ ] **Step 9: Start local server and perform browser QA**

Run:

```powershell
$env:PORT='18190'
$env:AIOPS_BIND_ADDRESS='127.0.0.1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m aiops_k8s_agents.control_plane_web
```

Verify in a browser at `http://127.0.0.1:18190/#orchestration`:

- Inference sample loads and plans.
- Training sample loads and plans.
- Invalid provenance is blocked.
- Candidate and graph content does not overlap at 1440x900 and 390x844.
- Feedback creates a new visible version or safe failure.
- Predicted values are never labeled observed.

- [ ] **Step 10: Commit Task 10**

```bash
git add ui/control_plane_static/index.html ui/control_plane_static/app.js ui/control_plane_static/styles.css tests/test_control_plane_ui.py
git commit -m "Build staged model partition research workspace"
```

### Task 11: Documentation, Full Verification, and Branch Review

**Files:**
- Modify: `README.md`
- Modify: `docs/submission/execution_code_guide.md`
- Modify: `docs/submission/test_guide.md`
- Modify: `docs/superpowers/specs/2026-08-20-model-partition-orchestrator-agent-v2-design.md` only if implementation reveals a factual mismatch.

**Interfaces:**
- Documents: exact boundary between planning, scheduling handoff, and actual execution.
- Documents: legacy and V2 CLI/API examples.
- Documents: deterministic reproduction and feedback experiment commands.

- [ ] **Step 1: Add concise README workflow**

```text
Approved Coordination Plan
→ Common Processing Core
→ Training/Inference Partition Strategy
→ Deterministic Candidate Planning
→ Independent Validation
→ Versioned PartitionExecutionPlan
→ Scheduling Handoff
→ Bounded Feedback Repartition
```

State that Scheduling and actual AI runtime execution are external and that web rewards are predicted unless observed evidence is explicitly supplied.

- [ ] **Step 2: Add runnable CLI and API examples**

Include commands for inference planning, training planning, plan history, feedback replanning, and legacy compatibility. Every command must reference an example file committed to the repository.

- [ ] **Step 3: Add the experiment test matrix**

Document deterministic repeatability, Training/Inference strategy comparison, infeasible candidate rejection, forecast/no-forecast comparison, scheduling feedback replanning, and exhaustion-to-human-review tests.

- [ ] **Step 4: Run the complete Python test suite**

Run: `python -m pytest`

Expected: all tests pass.

- [ ] **Step 5: Run Go Guard regression tests**

Run: `cd go/aiops-guard && go test ./...`

Expected: all Go tests pass.

- [ ] **Step 6: Run formatting and repository checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional files are modified.

- [ ] **Step 7: Perform final browser screenshots and overflow checks**

Capture desktop and mobile screenshots of Plan Intake, Candidate Analysis, and Handoff/Feedback. Verify nonblank content, no clipping, and correct prediction/runtime labels.

- [ ] **Step 8: Commit Task 11**

```bash
git add README.md docs/submission/execution_code_guide.md docs/submission/test_guide.md
git commit -m "Document model partition orchestrator experiments"
```

- [ ] **Step 9: Review branch history and changes**

Run:

```bash
git log --oneline --decorate -15
git diff --stat origin/codex/model-partition-orchestration...HEAD
```

Expected: one focused commit per task, no unrelated untracked files added, and all V2 work confined to partition orchestration plus shared Control Plane surfaces required by the feature.

