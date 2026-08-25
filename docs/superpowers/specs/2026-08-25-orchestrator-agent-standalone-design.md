# Orchestrator-Agent Standalone Design

## 1. Purpose

`Orchestrator-Agent` is a standalone laboratory integration module that converts an approved training or inference coordination plan into a validated, versioned `PartitionExecutionPlan`. It is extracted from the existing AIOps research repository without including the four recovery Agents, recovery experiments, AIOpsLab, AutoGen, Chaos Mesh, or Kubernetes recovery control.

The project is delivered as an independent VS Code folder that can be copied to the laboratory server `aiops/` directory and integrated through documented JSON contracts, CLI commands, or HTTP APIs.

## 2. Naming

| Item | Name |
| --- | --- |
| Project and UI | `Orchestrator-Agent` |
| Python package | `orchestrator_agent` |
| CLI | `orchestrator-agent` |
| API launcher | `orchestrator-agent-api` |
| Default local URL | `http://127.0.0.1:18200` |
| Main output contract | `PartitionExecutionPlan` |

## 3. Scope

### Included

- Federated Coordination schema `0.4` input adaptation
- Approved FL training plan processing
- Approved SL training plan processing
- Approved distributed inference plan processing
- Participant, model, resource, and network context enrichment
- Deterministic partition candidate generation
- Training and inference execution graph construction
- Resource and communication demand estimation
- Hard feasibility filtering
- Candidate evaluation and deterministic selection
- Optional shadow and guarded learned ranking
- Independent partition plan validation
- Versioned artifact persistence and plan history
- Scheduling handoff contract generation
- Runtime feedback analysis and bounded repartition planning
- Standalone CLI, FastAPI, browser UI, tests, examples, and integration documentation

### Excluded

- HA, Application, Infrastructure, and Cost recovery Agents
- Recovery Coordinator, mutual supervision, veto, and recovery reward logic
- AIOpsLab benchmark runtime
- AutoGen GroupChat
- Chaos Mesh fault injection
- Kubernetes recovery action execution
- Scheduling Agent implementation
- Actual FL, SL, or inference runtime execution

## 4. System Boundary

```text
Federated Coordination Agent
  + Shared State / Prometheus / Model Registry context
                         |
                         v
                 Orchestrator-Agent
  intake -> normalize -> enrich -> analyze -> generate candidates
         -> estimate -> hard-filter -> rank -> validate -> persist
                         |
                         v
              PartitionExecutionPlan
                         |
                         v
             External Scheduling Agent
```

The Orchestrator consumes an already approved execution mode. It does not choose between FL, SL, and distributed inference. The Scheduling Agent remains external and receives only a validated handoff contract.

## 5. Inputs

### 5.1 Coordination plan

Supported schema `0.4` inputs are:

- `task_type=federated_training` with `learning_mode.selected=FL`
- `task_type=federated_training` with `learning_mode.selected=SL`
- `task_type=distributed_inference` with `inference_mode.selected=PARTITIONED`

Every request must include stable job, session, plan, model, and participant identifiers. Approval provenance and the selected mode are treated as immutable upstream decisions.

### 5.2 Context

Participant IDs in the coordination plan are resolved against a versioned context snapshot containing:

- participant resources and availability
- network bandwidth and latency evidence
- model structure and approved version
- snapshot identifier and collection timestamp

The first standalone release uses a JSON-backed provider contract. A Prometheus or Shared State adapter may generate the same context document without changing the planning core.

## 6. Processing Pipeline

1. Validate schema version, task type, identifiers, and selected mode.
2. Resolve participant and model context.
3. Normalize the coordination plan into an internal partition request.
4. Select the matching FL, SL, or inference partition strategy.
5. Generate deterministic feasible candidates and execution graphs.
6. Estimate memory, compute, communication, latency, and throughput demands.
7. Reject candidates that violate hard constraints.
8. Rank feasible candidates using deterministic policy; optional AI rankers may only reorder feasible candidates.
9. Validate the selected plan independently.
10. Persist the signed or hashed artifact and produce a scheduling handoff.
11. Accept runtime feedback and create a bounded replacement plan when policy permits.

## 7. Outputs

The `PartitionExecutionPlan` includes:

- plan ID, version, parent plan, policy version, and input signature
- plan type and approved execution mode
- logical partitions and model boundaries
- execution graph and communication edges
- participant assignments or eligible participant set
- compute, memory, communication, latency, and throughput demands
- assumptions, warnings, confidence, and rejection evidence
- external Scheduling Agent handoff metadata

A blocked request returns a stable error code and evidence. It never fabricates an executable plan when context or feasibility evidence is missing.

## 8. Project Structure

```text
Orchestrator-Agent/
  src/orchestrator_agent/
    contracts and context providers
    partition strategies and candidate pipeline
    validator, evaluator, repository, feedback, and ranking
    CLI and FastAPI entry points
  config/
    model_partition_policy.json
    examples/
  ui/
    orchestration-only browser workspace
  tests/
  docs/
    DESIGN.md
    INTEGRATION.md
  pyproject.toml
  README.md
```

## 9. Interfaces

### CLI

- `orchestrator-agent plan-coordination`
- `orchestrator-agent plan`
- `orchestrator-agent feedback`
- `orchestrator-agent build-ranking-dataset`
- `orchestrator-agent train-ranker`
- `orchestrator-agent evaluate-ranker`

### HTTP API

- `GET /healthz`
- `GET /api/examples`
- `POST /api/plans`
- `POST /api/coordination-plans`
- `GET /api/plans/{plan_id}`
- `GET /api/plans/{plan_id}/history`
- `POST /api/plans/{plan_id}/feedback`
- `GET /api/strategies`
- `GET /api/rankers`

## 10. Error and Safety Rules

- Missing participant, model, bandwidth, or approval context fails closed.
- Unknown task or execution modes are rejected.
- The selected upstream mode cannot be silently changed.
- AI ranking never bypasses the deterministic hard feasibility filter.
- Learned ranking falls back to deterministic ranking when the model, schema, quality gate, or integrity check fails.
- Runtime feedback can only trigger bounded, versioned replanning.
- No endpoint executes a Scheduler, Kubernetes mutation, training runtime, or inference runtime.

## 11. Verification

The standalone package must pass:

- unit tests for contracts, strategies, estimation, validation, persistence, feedback, and ranking
- FL, SL, and distributed inference end-to-end planning tests
- blocked-plan tests for missing bandwidth and invalid context
- CLI smoke tests
- FastAPI route and browser UI tests
- import scan proving no dependency on recovery Agent or AIOpsLab modules

The source repository remains unchanged. The standalone project is the only folder delivered to the laboratory server.
