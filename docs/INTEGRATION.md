# Integration Guide

## 1. Upstream input

Federated Coordination Agent는 다음 세 계약 중 하나를 전달합니다.

- `task_type=federated_training`, `learning_mode.selected=FL`
- `task_type=federated_training`, `learning_mode.selected=SL`
- `task_type=distributed_inference`, `inference_mode.selected=PARTITIONED|REPLICATED`

완전한 예제는 `config/examples/federated_coordination_*_v04.json`에 있습니다.

## 2. Context input

`config/examples/federated_coordination_context_v04.json` 형식으로 다음 정보를 제공합니다.

- participant device capacity and availability
- directional network bandwidth and latency
- approved model version and model block profile
- optional workload forecast
- snapshot ID, version, source, collected timestamp

현재 구현은 JSON provider입니다. Prometheus나 Shared State를 연동할 때는 동일한 필드를 채우는 adapter를 추가하고 planning core는 변경하지 않습니다.

## 3. HTTP request

```http
POST /api/coordination-plans
Content-Type: application/json

{
  "coordination_plan": { "...": "v0.4 plan" },
  "context": { "...": "versioned context snapshot" },
  "selection_mode": "deterministic"
}
```

## 4. Downstream output

핵심 결과는 응답의 `plan`과 `scheduling_handoff`입니다.

```json
{
  "status": "planned",
  "plan": {
    "plan_id": "partition-plan-...",
    "plan_version": 1,
    "plan_type": "training",
    "strategy_id": "training-partition-v1",
    "selected_candidate": {
      "partitions": [],
      "graph_nodes": [],
      "graph_edges": [],
      "total_transfer_bytes": 0,
      "maximum_memory_pressure": 0.0
    },
    "assumptions": [],
    "warnings": [],
    "confidence": 0.95
  },
  "validation": { "valid": true, "errors": [] },
  "scheduling_handoff": {
    "status": "ready",
    "scheduler_ref": null
  }
}
```

`status=blocked`, `validation.valid=false`, 또는 `scheduling_handoff.status=blocked`인 계획은 외부 Scheduler로 전달하면 안 됩니다.

## 5. Feedback and bounded repartition

Scheduler/runtime이 latency, memory, placement failure 등을 관측하면 저장된 `plan_id`에 feedback을 전달합니다.

```http
POST /api/plans/{plan_id}/feedback
Content-Type: application/json

{
  "signal": "latency_slo_violation",
  "source": "runtime-monitor",
  "reason": "observed latency exceeded the approved SLO",
  "received_at": "2026-08-25T00:00:00Z",
  "plan_id": "partition-plan-...",
  "plan_version": 1
}
```

새 계획은 `parent_plan_id`와 증가된 `plan_version`을 가지며 lineage에서 조회할 수 있습니다.

