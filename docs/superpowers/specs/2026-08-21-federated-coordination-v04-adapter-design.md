# Federated Coordination 0.4 Input Adapter Design

## Goal

Connect the Federated Coordination Agent's `schema_version: 0.4` output to the
existing Model Partition Orchestrator without replacing the validated V2
planning core. The integration must accept federated learning, split learning,
and partitioned inference plans, enrich participant identifiers with trusted
resource context, and preserve fail-closed validation, reward evaluation,
versioned artifacts, and Scheduling handoff boundaries.

## Architectural Boundary

The Federated Coordination Agent remains responsible for selecting the
learning or inference mode and the candidate participants. The Model Partition
Orchestrator does not override that decision. It translates the approved plan
into a logical execution plan:

```text
Federated Coordination schema 0.4
    -> CoordinationPlanV04Adapter
    -> ParticipantContextProvider + ModelContextProvider
    -> PartitionPlanningRequest V2
    -> ModelPartitionOrchestrationAgent
    -> Validator + Evaluator + Repository
    -> SchedulingHandoff
```

The current V2 request and legacy request APIs remain supported.

## Accepted Inputs

### Federated learning

- `task_type`: `federated_training`
- `learning_mode.selected`: `FL`
- Produces a full-model replica for each selected participant and an
  aggregation graph.
- Preserves the upstream federated strategy and participation policy as
  strategy metadata.

### Split learning

- `task_type`: `federated_training`
- `learning_mode.selected`: `SL`
- Produces client/server layer split candidates and forward/backward transfer
  edges.
- Missing bandwidth evidence blocks planning instead of fabricating a value.

### Partitioned inference

- `task_type`: `distributed_inference`
- `inference_mode.selected`: `PARTITIONED`
- Produces contiguous layer partitions and a forward-only execution graph.
- Serving policy values become latency, batching, concurrency, and throughput
  planning constraints.

Unsupported selected modes are rejected with a stable contract error. A
`fallback_order` is recorded as upstream metadata and is not selected by the
partition Agent.

## Context Enrichment

The coordination payload intentionally contains participant identifiers rather
than resource telemetry. The adapter resolves the remaining planning context
through explicit provider interfaces:

- `ParticipantContextProvider`: devices, availability, memory and compute
  capacity, and directed network links for the candidate participants.
- `ModelContextProvider`: approved model version and ordered model structure
  profile for `model_ref`.

Production providers may read Prometheus and a model registry. Tests and mock
workflows use deterministic in-memory providers. Provider failure or missing
required SL network evidence returns a blocked result.

## Approval Provenance

The adapter treats `round_plan_id` or `inference_plan_id` as the upstream
approval reference only when the request enters through the trusted
Federated-Coordination endpoint. It records:

- `approved_by`: `FederatedCoordinationAgent`
- `approval_ref`: upstream plan identifier
- original schema version, session ID, participant priorities, selected mode,
  fallback order, strategy, and participation/serving policy

The original payload is retained in the report for reproducibility.

## Strategy Integration

Add three registered strategy mappings:

| Upstream selection | Internal plan type | Strategy |
| --- | --- | --- |
| `FL` | `training` | `federated-full-model-v1` |
| `SL` | `training` | `training-partition-v1` |
| `PARTITIONED` | `inference` | `inference-partition-v1` |

FL requires a dedicated full-model candidate generator because it is replica
coordination, not a layer split. SL and partitioned inference reuse the current
candidate generation and validation core after conversion to V2 contracts.

## API and UI

Add a focused endpoint:

```text
POST /api/model-partition/coordination-plan
```

The response uses the existing orchestration report contract and includes the
upstream plan ID, enrichment summary, selected strategy, plan, validation,
evaluation, artifact path, and Scheduling handoff.

The orchestration workspace gains a `Federated Coordination 0.4` input source.
It shows the received mode and participants, enrichment status, final logical
plan, validation result, estimated reward, and handoff readiness. Existing
training and inference examples remain available.

## Safety and Failure Semantics

- Unknown schema, task type, or selected mode: reject.
- Missing model profile or participant resource context: block.
- Missing required SL bandwidth evidence: block.
- Model version mismatch: reject.
- Insufficient participants or infeasible memory/SLA: block.
- No automatic fallback mode switch.
- No Kubernetes mutation, GPU placement, or runtime execution is added.

## Verification

- Unit tests for all three input variants and stable rejection cases.
- Contract tests proving the original V2 and legacy inputs still work.
- API tests for successful and blocked enrichment.
- UI contract tests for the new input source and enrichment status.
- Full Python test suite and Go Guard test suite remain passing.
