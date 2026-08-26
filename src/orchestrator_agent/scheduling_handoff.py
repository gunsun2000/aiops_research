from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import ceil
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from orchestrator_agent.partition_models import PartitionContractError


SCHEDULER_PATH = "/api/v1/scheduler/plans"


class SchedulingDeliveryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class SchedulingAgentClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Scheduling Agent URL must be an http(s) URL")
        self.base_url = normalized
        self.endpoint = normalized + SCHEDULER_PATH
        self.timeout_seconds = float(timeout_seconds)

    def submit(self, payload: Mapping[str, Any], *, request_id: str) -> Mapping[str, Any]:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "X-Request-ID": request_id,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = response.status
                raw = response.read(10 * 1024 * 1024 + 1)
        except HTTPError as exc:
            raw = exc.read(10 * 1024 * 1024)
            raise SchedulingDeliveryError(
                _error_message(raw, f"Scheduling Agent rejected HTTP {exc.code}"),
                retryable=exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SchedulingDeliveryError(
                "Scheduling Agent could not be reached", retryable=True
            ) from exc
        if status != 202 or len(raw) > 10 * 1024 * 1024:
            raise SchedulingDeliveryError(
                f"Scheduling Agent returned unexpected HTTP {status}"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchedulingDeliveryError(
                "Scheduling Agent returned invalid JSON"
            ) from exc
        if not isinstance(value, Mapping):
            raise SchedulingDeliveryError("Scheduling Agent response must be an object")
        return dict(value)


def to_scheduling_request(
    report: Mapping[str, Any],
    coordination: Mapping[str, Any],
    *,
    clock: Callable[[], datetime] | None = None,
    ttl_seconds: float = 30.0,
) -> dict[str, Any]:
    if report.get("status") != "planned":
        raise PartitionContractError(
            "partition_plan_blocked", "only a validated partition plan can be scheduled"
        )
    plan = _mapping(report.get("plan"), "report.plan")
    candidate = _mapping(plan.get("selected_candidate"), "plan.selected_candidate")
    context = _mapping(
        _mapping(report.get("planning_request"), "planning_request").get(
            "system_context"
        ),
        "planning_request.system_context",
    )
    nodes = [
        _mapping(item, "selected_candidate.graph_nodes[]")
        for item in candidate.get("graph_nodes", [])
    ]
    if not nodes:
        raise PartitionContractError(
            "empty_execution_graph", "partition plan has no graph nodes"
        )
    edges = [
        _mapping(item, "selected_candidate.graph_edges[]")
        for item in candidate.get("graph_edges", [])
    ]
    dependencies: dict[str, list[str]] = {
        str(node["partition_id"]): [] for node in nodes
    }
    for edge in edges:
        source = str(edge.get("source_partition") or "")
        target = str(edge.get("target_partition") or "")
        if source in dependencies and target in dependencies:
            dependencies[target].append(source)

    partition_details = {
        str(item.get("partition_id")): item
        for item in candidate.get("partitions", [])
        if isinstance(item, Mapping)
    }
    device_details = {
        str(item.get("device_id")): item
        for item in context.get("devices", [])
        if isinstance(item, Mapping)
    }
    now = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    task_type = str(coordination.get("task_type"))
    selected_mode = _selected_mode(coordination)
    role_mapping: dict[str, str] = {}
    tasks: list[dict[str, Any]] = []
    duration = max(
        1,
        int(float(candidate.get("estimated_total_latency_ms") or 1000) / len(nodes)),
    )
    for node in nodes:
        partition_id = str(node.get("partition_id") or "").strip()
        device_id = str(node.get("device_id") or "").strip()
        if not partition_id or device_id not in device_details:
            raise PartitionContractError(
                "invalid_execution_graph", "graph node has no matching resource device"
            )
        role = _role(task_type, selected_mode, partition_id)
        role_mapping[partition_id] = role
        detail = partition_details.get(partition_id, {})
        memory_bytes = int(detail.get("memory_demand_bytes") or 256 * 1024**2)
        device = device_details[device_id]
        gpu = (
            1
            if str(device.get("device_type", "")).lower() == "gpu"
            and "aggregation" not in partition_id.lower()
            else 0
        )
        tasks.append(
            {
                "partition_id": partition_id,
                "role": role,
                "participant_id": device_id,
                "depends_on": sorted(set(dependencies[partition_id])),
                "resource_requirements": {
                    "cpu_milli": 1000,
                    "memory_mib": max(1, ceil(memory_bytes / 1024**2)),
                    "gpu_count": gpu,
                    "gpu_memory_mib": 0,
                },
                "estimated_duration_ms": duration,
                "constraints": {"allowed_device_ids": [device_id]},
            }
        )

    binding = coordination.get("workload_binding")
    if not isinstance(binding, Mapping):
        raise PartitionContractError(
            "workload_binding_missing",
            "FCA plan must include raw_workload.workload_binding with app_version_id",
        )
    app_version_id = str(binding.get("app_version_id") or "").strip()
    if not app_version_id:
        raise PartitionContractError(
            "workload_binding_missing", "workload_binding.app_version_id is required"
        )
    devices = []
    for device_id, device in device_details.items():
        memory_available = int(device.get("memory_available_bytes") or 0)
        device_type = str(device.get("device_type") or "cpu").lower()
        devices.append(
            {
                "device_id": device_id,
                "status": "READY",
                "available_in_ms": 0,
                "failure_domain": device_id,
                "labels": {"device_type": device_type},
                "allocatable": {
                    "cpu_milli": 64000,
                    "memory_mib": max(1, memory_available // 1024**2),
                    "gpu_count": 1 if device_type == "gpu" else 0,
                    "gpu_memory_mib": 0,
                },
            }
        )
    links = context.get("network_links", [])
    penalties = []
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, Mapping):
            continue
        penalties.append(
            {
                "source_device_id": str(link.get("source_device")),
                "target_device_id": str(link.get("target_device")),
                "penalty": min(
                    1.0, max(0.0, float(link.get("latency_ms") or 0) / 100.0)
                ),
            }
        )
    partition_plan_id = str(plan.get("plan_id"))
    round_plan_id = str(
        coordination.get("inference_plan_id")
        or coordination.get("round_plan_id")
        or ""
    )
    model_ref = dict(_mapping(coordination.get("model_ref"), "model_ref"))
    model_ref["version"] = str(model_ref.get("version"))
    context_ref = coordination.get("context_ref")
    context_ref = context_ref if isinstance(context_ref, Mapping) else {}
    payload = {
        "schema_version": "scheduler-input.khu.ai/v0alpha1",
        "request_id": f"scheduler-request-{partition_plan_id}",
        "correlation_id": f"{coordination.get('job_id')}:{round_plan_id}",
        "created_at": _time(now),
        "expires_at": _time(expires),
        "partition_execution_plan": {
            "partition_plan_id": partition_plan_id,
            "job_id": str(coordination.get("job_id")),
            "task_type": task_type,
            "session_id": str(coordination.get("session_id")),
            "round_id": int(coordination.get("round_id") or 0),
            "attempt": int(coordination.get("attempt") or 0),
            "round_plan_id": round_plan_id,
            "state_snapshot_id": str(
                context_ref.get("state_snapshot_id") or context.get("snapshot_id")
            ),
            "model_ref": model_ref,
            "graph_hash": "sha256:"
            + sha256(
                json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True).encode()
            ).hexdigest(),
            "partitions": tasks,
        },
        "scheduling_context": {
            "queue_entered_at": _time(now),
            "importance": float(binding.get("importance", 0.5)),
        },
        "system_snapshot": {
            "snapshot_id": str(context.get("snapshot_id")),
            "version": max(1, int(coordination.get("attempt") or 1)),
            "observed_at": _time(now),
            "valid_until": _time(expires),
            "devices": devices,
        },
        "workload_binding": {
            "app_version_id": app_version_id,
            "mode": (
                "INFERENCE"
                if task_type == "distributed_inference"
                else selected_mode
            ),
            "requested_by": str(
                binding.get("requested_by") or "orchestrator-agent"
            ),
            "role_mapping": role_mapping,
            "parameters": {
                **(
                    dict(binding.get("parameters"))
                    if isinstance(binding.get("parameters"), Mapping)
                    else {}
                ),
                "model_ref": model_ref,
                "coordination_plan_id": round_plan_id,
            },
        },
    }
    if penalties:
        payload["network_assessment"] = {
            "assessment_id": f"network-{context.get('snapshot_id')}",
            "penalties": penalties,
        }
    return payload


def _selected_mode(coordination: Mapping[str, Any]) -> str:
    field = (
        "inference_mode"
        if coordination.get("task_type") == "distributed_inference"
        else "learning_mode"
    )
    return str(_mapping(coordination.get(field), field).get("selected") or "").upper()


def _role(task_type: str, mode: str, partition_id: str) -> str:
    lowered = partition_id.lower()
    if task_type == "distributed_inference":
        return "INFERENCE_REPLICA" if mode == "REPLICATED" else "INFERENCE_STAGE"
    if mode == "FL":
        return "FL_SERVER" if "aggregation" in lowered else "FL_CLIENT"
    return (
        "SL_CLIENT"
        if "client" in lowered or partition_id.endswith("1")
        else "SL_SERVER"
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PartitionContractError(
            "invalid_scheduling_handoff", f"{field} must be an object"
        )
    return value


def _time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _error_message(raw: bytes, fallback: str) -> str:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return fallback
    error = value.get("error") if isinstance(value, Mapping) else None
    message = error.get("message") if isinstance(error, Mapping) else None
    return str(message) if isinstance(message, str) and message else fallback
