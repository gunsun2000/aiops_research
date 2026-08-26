from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator_agent.federated_coordination_adapter import (
    FederatedCoordinationPlanV04,
    participant_context_from_fca_snapshot,
)
from orchestrator_agent.web import create_app


ROOT = Path(__file__).resolve().parents[1]


class FakeScheduler:
    endpoint = "http://scheduler.test/api/v1/scheduler/plans"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit(self, payload, *, request_id):
        self.calls.append(deepcopy(dict(payload)))
        return {"status": "accepted"}


def test_live_endpoint_forwards_each_new_plan_revision_once(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    app = create_app(
        artifact_root=tmp_path / "artifacts",
        scheduler_client=scheduler,
        handoff_output_path=tmp_path / "scheduler-latest.json",
    )
    client = TestClient(app)
    payload = json.loads(
        (ROOT / "config/examples/federated_coordination_fl_v04.json").read_text()
    )
    payload["workload_binding"] = {"app_version_id": "app-version-test"}

    first = client.post("/api/v1/orchestrator/plans", json=payload)
    duplicate = client.post("/api/v1/orchestrator/plans", json=payload)
    replacement = deepcopy(payload)
    replacement["round_plan_id"] = "round-plan-fl-reconcile-2"
    replacement["attempt"] = 2
    second = client.post("/api/v1/orchestrator/plans", json=replacement)

    assert first.status_code == duplicate.status_code == second.status_code == 202
    assert first.headers["x-scheduling-delivery"] == "accepted"
    assert first.json() == duplicate.json()
    assert len(scheduler.calls) == 2
    assert scheduler.calls[-1]["partition_execution_plan"]["attempt"] == 2
    assert json.loads((tmp_path / "scheduler-latest.json").read_text()) == (
        scheduler.calls[-1]
    )


def test_fca_prometheus_snapshot_becomes_current_participant_context() -> None:
    payload = json.loads(
        (ROOT / "config/examples/federated_coordination_fl_v04.json").read_text()
    )
    participant_ids = [
        item["client_id"] for item in payload["candidate_participants"]
    ]
    payload["system_snapshot"] = {
        "state_snapshot_id": "prometheus-live-2",
        "generated_at": "2026-08-25T10:00:00Z",
        "source": "prometheus",
        "clients": [
            {"client_id": node_id, "status": "online"}
            for node_id in participant_ids
        ],
        "resource_summary": {
            "nodes": {
                node_id: {
                    "memory_total_bytes": 32 * 1024**3,
                    "memory_allocatable_bytes": 24 * 1024**3,
                    "gpu_memory_allocatable_bytes": 20 * 1024**3,
                    "gpu_memory_total_bytes": 24 * 1024**3,
                    "gpu_utilization_ratio": 0.2,
                    "dcgm_available": True,
                }
                for node_id in participant_ids
            }
        },
        "network_summary": {
            "peers": {
                node_id: {
                    "rtt_seconds": 0.002,
                    "available_bandwidth_bytes_per_second": 125_000_000,
                    "assessment": "GOOD",
                }
                for node_id in participant_ids
            }
        },
    }

    context = participant_context_from_fca_snapshot(
        FederatedCoordinationPlanV04.from_dict(payload)
    )

    assert context.snapshot_id == "prometheus-live-2"
    assert {item.device_id for item in context.devices} == set(participant_ids)
    assert all(item.memory_available_bytes == 20 * 1024**3 for item in context.devices)
    assert len(context.network_links) == 2
