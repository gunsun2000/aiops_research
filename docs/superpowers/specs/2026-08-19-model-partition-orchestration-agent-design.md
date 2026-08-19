# Model Partition Orchestration Agent Design

## 1. Purpose

This design adds a Model Partition Orchestration Agent to the existing AIOps research platform. The agent consumes an already-approved execution mode and a federated round plan, generates feasible model partition candidates, selects a split plan, builds a logical execution graph, estimates resource demand, validates the selected plan, and records an evaluator reward.

The existing Kubernetes recovery experiment remains unchanged and continues to serve as the baseline demonstration of multi-agent supervision, safety validation, execution, and post-run evaluation.

## 2. Architectural Position

The agent occupies one stage of the integrated AI workload pipeline:

```text
Job Request + Workload Prediction + Shared State
                         |
                         v
Federated Coordination Agent
                         |
                         | FederatedRoundPlan
                         v
Model Partition Orchestration Agent
  - split candidate generation
  - logical partition construction
  - execution graph construction
  - resource demand estimation
  - partition plan selection and replanning
                         |
                         | PartitionExecutionPlan
                         v
Scheduling Agent <-> Network Optimization Agent
                         |
                         v
AI Workload Execution Controller
```

The Model Partition Orchestration Agent does not select or semantically validate FL, SL, or inference execution modes. That responsibility belongs to the upstream component. It only performs a fail-closed contract check that the received mode was approved and carries an approval reference.

## 3. Scope

### 3.1 Included

- Consume an approved `FederatedRoundPlan`.
- Represent an ordered model graph and resource/network snapshot.
- Generate valid split-point combinations for the participating devices.
- Build contiguous logical partitions without missing or duplicated model layers.
- Build a directed acyclic execution graph between logical partitions.
- Estimate compute time, memory demand, communication volume, and transfer time.
- Reject candidates that exceed device memory or job constraints.
- Rank feasible candidates using a deterministic, versioned policy.
- Produce a structured `PartitionExecutionPlan` with alternatives and rationale.
- Replan while excluding failed split points or unavailable devices.
- Validate the final plan independently from the planner.
- Evaluate predicted or observed results and calculate bounded reward.
- Register the Agent and expose a CLI and web workspace.
- Save JSON experiment artifacts under a dedicated model-partition run directory.

### 3.2 Excluded

- Selecting FL, SL, or inference mode.
- Validating the semantic correctness of the selected mode.
- Selecting federated participants or aggregation policy.
- Final device placement, queueing, and dispatch scheduling.
- Network route and bandwidth optimization.
- Starting, stopping, or cancelling an actual training/inference runtime.
- Parsing arbitrary PyTorch or ONNX models in the first implementation.
- Claiming real GPU performance from mock or dry-run estimates.
- Replacing or deleting the existing recovery experiment.

## 4. Chosen Integration Approach

The partition subsystem is added as a second domain runtime inside the same research platform. It reuses the project package, Agent Registry conventions, configuration layout, CLI, web control plane, artifact conventions, and test suite, but does not force partition plans into the recovery-specific `RecoveryAction` contract.

Two alternatives were rejected:

1. Adding the partition agent as a fifth recovery reviewer would expose it in the UI but would not let it produce a real `PartitionExecutionPlan`.
2. Immediately converting every recovery model and job table to a fully generic workflow engine would create a broad migration risk unrelated to the first partition experiment.

The selected approach keeps current behavior stable while introducing typed boundaries that can later become common contracts for additional orchestration agents.

## 5. Domain Contracts

### 5.1 ApprovedExecutionMode

```python
@dataclass(frozen=True)
class ApprovedExecutionMode:
    name: str
    approved: bool
    approved_by: str
    approval_ref: str
```

The partition runtime rejects input when `approved` is false or the approval metadata is missing. It does not decide whether the mode itself is correct.

### 5.2 ModelLayer

```python
@dataclass(frozen=True)
class ModelLayer:
    name: str
    compute_units: float
    parameter_bytes: int
    activation_bytes: int
    working_memory_bytes: int
```

Layers are ordered. A valid plan assigns every layer exactly once and preserves this order.

### 5.3 ResourceDevice

```python
@dataclass(frozen=True)
class ResourceDevice:
    device_id: str
    device_type: str
    compute_units_per_second: float
    memory_capacity_bytes: int
    memory_available_bytes: int
```

### 5.4 NetworkLink

```python
@dataclass(frozen=True)
class NetworkLink:
    source_device: str
    target_device: str
    bandwidth_bytes_per_second: float
    latency_ms: float
```

### 5.5 PartitionConstraints

```python
@dataclass(frozen=True)
class PartitionConstraints:
    max_end_to_end_latency_ms: float | None
    max_transfer_bytes: int | None
    minimum_memory_headroom_ratio: float
```

### 5.6 FederatedRoundPlan

```python
@dataclass(frozen=True)
class FederatedRoundPlan:
    job_id: str
    model_id: str
    execution_mode: ApprovedExecutionMode
    layers: tuple[ModelLayer, ...]
    participants: tuple[str, ...]
    devices: tuple[ResourceDevice, ...]
    network_links: tuple[NetworkLink, ...]
    constraints: PartitionConstraints
```

The first implementation requires at least two layers and two participants. Each participant must reference one available device.

### 5.7 LogicalPartition

```python
@dataclass(frozen=True)
class LogicalPartition:
    partition_id: str
    device_id: str
    layer_names: tuple[str, ...]
    compute_units: float
    memory_demand_bytes: int
```

### 5.8 ExecutionGraph

```python
@dataclass(frozen=True)
class ExecutionGraphNode:
    partition_id: str
    device_id: str

@dataclass(frozen=True)
class ExecutionGraphEdge:
    source_partition: str
    target_partition: str
    transfer_bytes: int
    estimated_transfer_ms: float
```

### 5.9 PartitionCandidate

```python
@dataclass(frozen=True)
class PartitionCandidate:
    split_points: tuple[int, ...]
    partitions: tuple[LogicalPartition, ...]
    graph_nodes: tuple[ExecutionGraphNode, ...]
    graph_edges: tuple[ExecutionGraphEdge, ...]
    estimated_compute_ms: float
    estimated_transfer_ms: float
    estimated_total_latency_ms: float
    total_transfer_bytes: int
    maximum_memory_pressure: float
    valid: bool
    rejection_reasons: tuple[str, ...]
    score: float
```

### 5.10 PartitionExecutionPlan

```python
@dataclass(frozen=True)
class PartitionExecutionPlan:
    plan_id: str
    job_id: str
    model_id: str
    approved_execution_mode: str
    policy_version: str
    selected_candidate: PartitionCandidate | None
    alternative_candidates: tuple[PartitionCandidate, ...]
    rationale: str
    valid: bool
    human_review_required: bool
    errors: tuple[str, ...]
```

When `valid` is true, `selected_candidate` must exist and `human_review_required` must be false. A bounded planning failure uses `selected_candidate=None`, records stable error codes, and sets `human_review_required=true`. The output is a plan for the Scheduling Agent. It is not an execution command.

## 6. Deterministic Planning Policy

The first policy is deterministic and reproducible.

1. Generate all contiguous split-point combinations required for the number of participants.
2. Assign contiguous layer ranges to participants in the order provided by the upstream plan.
3. Calculate partition compute time as the sum of layer compute units divided by device throughput.
4. Calculate memory demand as parameters, working memory, and the largest boundary activation required by the partition.
5. Calculate transfer time as link latency plus activation bytes divided by link bandwidth.
6. Reject a candidate when a device exceeds available memory after applying the required headroom.
7. Reject a candidate when transfer volume or predicted latency exceeds an explicit job constraint.
8. Rank feasible candidates by normalized predicted latency, memory pressure, and communication volume.
9. Use lexicographic split-point order as the final deterministic tie breaker.

Default score weights are versioned configuration values:

```json
{
  "latency": 0.5,
  "memory_pressure": 0.3,
  "communication": 0.2
}
```

No learned policy is claimed in this implementation.

## 7. Replanning

Replanning receives the original `FederatedRoundPlan`, the previous `PartitionExecutionPlan`, and a bounded failure description.

Supported failure signals are:

- `device_unavailable`
- `memory_exceeded`
- `latency_slo_violation`
- `transfer_failure`

The failure signal determines the exclusion rule:

- `device_unavailable`: remove the failed device and its participant from the candidate pool;
- `memory_exceeded`: reject the previous device/partition assignment and require a lower memory demand on that device;
- `latency_slo_violation`: exclude the previous split-point combination;
- `transfer_failure`: exclude candidates that use the failed source/target network link.

The replanner then reruns the deterministic planner and returns the next feasible plan. When fewer than two usable participants remain or no candidate satisfies the updated constraints, it returns a safe failure with `human_review_required: true`. `max_replan_attempts` is read from versioned policy configuration, defaults to `2`, and prevents an unbounded loop.

## 8. Independent Validation

`PartitionPlanValidator` validates the planner output without calling planner internals. It checks:

- execution mode approval metadata exists;
- plan and input job/model identifiers match;
- every model layer appears exactly once;
- layer order is preserved;
- partitions are non-empty and reference known participants;
- estimated memory demand fits the target device;
- graph nodes match partitions;
- graph edges reference known nodes and form a DAG;
- transfer edges use existing network links;
- selected candidate satisfies explicit constraints.

Validation failure prevents downstream handoff and produces a structured error list.

## 9. Evaluation and Reward

`PartitionPlanEvaluator` supports two evidence levels:

- `predicted`: evaluates validated plan estimates only;
- `observed`: compares actual runtime measurements with the selected plan.

The bounded reward range is `[-1.0, 1.0]`.

```text
reward =
    0.40 * constraint_satisfaction
  + 0.25 * latency_efficiency
  + 0.20 * memory_safety
  + 0.15 * communication_efficiency
```

The components are deterministic and bounded:

- `constraint_satisfaction`: `1.0` only when independent validation passes, otherwise `-1.0`;
- `latency_efficiency`: `clamp(1 - estimated_latency / max_latency, 0, 1)` when an explicit latency SLO exists, otherwise `1 / (1 + estimated_latency_ms / latency_reference_ms)`;
- `memory_safety`: `clamp(1 - maximum_memory_pressure, 0, 1)`;
- `communication_efficiency`: `1 / (1 + total_transfer_bytes / transfer_reference_bytes)`.

`latency_reference_ms` and `transfer_reference_bytes` are versioned policy values rather than hidden constants. Observed evaluation substitutes measured latency, peak memory pressure, and transferred bytes for predicted values while preserving the same formula and policy version. An invalid plan cannot receive a positive reward. Predicted reward is labeled as estimated and is never presented as real runtime performance.

## 10. Agent Registration

The Agent Registry gains `ModelPartitionOrchestrationAgent` with implementation ID `deterministic-model-partition` and bounded operations:

- `partition_generate_candidates`
- `partition_select_split`
- `partition_build_execution_graph`
- `partition_estimate_resource_demand`
- `partition_replan`

The agent is not added to existing recovery protocol profiles. Recovery profiles remain reproducible and unchanged.

## 11. CLI

The CLI adds:

```bash
aiops-k8s-agents plan-model-partition \
  --input config/examples/model_partition_job.json \
  --output runs/model-partition/latest/partition_plan.json
```

Optional replanning is invoked with a previous plan and failure file:

```bash
aiops-k8s-agents replan-model-partition \
  --input config/examples/model_partition_job.json \
  --previous-plan runs/model-partition/latest/partition_plan.json \
  --failure config/examples/model_partition_failure.json
```

The command returns non-zero on invalid input, no feasible partition, or validation failure.

## 12. Web Platform

The existing console gains an `AI Workload Orchestration` workspace. The first supported stage is `Model Partition`.

The workspace contains:

- approved mode and approval provenance, shown read-only;
- model and participant summary;
- resource and network snapshot;
- planning policy version;
- candidate comparison table;
- selected logical partitions;
- execution graph;
- resource demand and predicted metrics;
- validation status;
- estimated evaluator reward;
- JSON artifact download.

The web API accepts the same JSON contract as the CLI and executes the same planner, validator, and evaluator. The UI does not independently calculate planning results.

The first web endpoint is synchronous because deterministic planning is bounded and does not mutate infrastructure:

```text
POST /api/model-partition/plans
GET  /api/model-partition/examples
```

Generated reports are saved under `runs/model-partition/<plan-id>/report.json` and returned to the browser. A future real runtime adapter may use background jobs and SSE, but that is outside this implementation.

## 13. Error Handling

- Missing or unapproved mode: reject with `approved_mode_required`.
- Unknown participant or missing network link: reject with contract errors.
- No feasible split: return `no_feasible_partition` with candidate rejection reasons.
- Invalid selected plan: return `partition_validation_failed` and do not hand off.
- Replanning exhausted: return `human_review_required: true`.
- Web input errors: return HTTP 422 with stable machine-readable error codes.
- Internal planner errors: return a safe failure without exposing stack traces in the UI.

## 14. Planned File Boundaries

- `src/aiops_k8s_agents/partition_models.py`: immutable domain contracts and JSON conversion.
- `src/aiops_k8s_agents/model_partition_agent.py`: candidate generation, estimation, ranking, and replanning.
- `src/aiops_k8s_agents/partition_validator.py`: independent plan validation.
- `src/aiops_k8s_agents/partition_evaluator.py`: predicted and observed reward calculation.
- `src/aiops_k8s_agents/partition_artifacts.py`: report persistence.
- `config/model_partition_policy.json`: versioned deterministic score policy.
- `config/examples/model_partition_job.json`: executable example input.
- `config/examples/model_partition_failure.json`: bounded replanning example.
- `src/aiops_k8s_agents/cli.py`: planning and replanning commands.
- `src/aiops_k8s_agents/control_plane_web.py`: model-partition API routes.
- `ui/control_plane_static/index.html`: orchestration workspace structure.
- `ui/control_plane_static/app.js`: API calls and rendering.
- `ui/control_plane_static/styles.css`: workspace layout styles.
- `tests/test_partition_models.py`: contract validation and serialization.
- `tests/test_model_partition_agent.py`: candidate generation, ranking, and replanning.
- `tests/test_partition_validator.py`: independent safety checks.
- `tests/test_partition_evaluator.py`: reward boundaries and evidence labels.
- `tests/test_model_partition_cli.py`: CLI behavior and artifacts.
- `tests/test_model_partition_web.py`: API behavior and UI contract.

## 15. Compatibility

- Existing recovery CLI commands, APIs, protocol profiles, and result files remain unchanged.
- Existing AIOpsLab and AutoGen paths remain separate from partition planning.
- The first partition implementation has no new third-party runtime dependency.
- Existing `python -m pytest` must pass after the change.
- Go Guard remains limited to Kubernetes command validation and is not used to validate a partition plan.

## 16. Acceptance Criteria

1. The example job produces at least one feasible candidate and a deterministic selected plan.
2. Repeated planning with identical input produces byte-equivalent canonical plan content except for generated identifiers and timestamps.
3. An unapproved execution mode is rejected without semantic mode selection.
4. Memory-overflow candidates are rejected with explicit reasons.
5. Every selected plan contains complete logical partitions, a valid execution graph, and per-device resource demand.
6. Replanning excludes the failed plan or device and either selects a different candidate or returns a bounded safe failure.
7. The validator independently detects layer gaps, duplicates, unknown devices, cycles, and constraint violations.
8. Predicted reward is clearly labeled and remains within `[-1.0, 1.0]`.
9. CLI and web API return the same selected split and score for the same input.
10. The web workspace displays the input provenance, candidates, selected plan, validation, and estimated reward.
11. Existing recovery, AIOpsLab, AutoGen, and control-plane tests remain green.
