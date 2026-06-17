from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class InferenceOptimizationError(ValueError):
    """Raised when an inference optimization plan is invalid."""


@dataclass(frozen=True)
class OptimizationWeights:
    latency: float
    throughput: float
    cost: float
    capacity: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizationWeights:
        return cls(
            latency=float(data.get("latency", 0.35)),
            throughput=float(data.get("throughput", 0.30)),
            cost=float(data.get("cost", 0.20)),
            capacity=float(data.get("capacity", 0.15)),
        )


@dataclass(frozen=True)
class InferenceResourceProfile:
    id: str
    accelerator: str
    cpu_cores: int
    memory_gb: float
    gpu_memory_gb: float
    expected_latency_ms: float
    expected_throughput_rps: float
    cost_per_hour: float
    available_replicas: int
    supported_model_types: tuple[str, ...]
    node_selector: dict[str, str]
    resource_limits: dict[str, str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InferenceResourceProfile:
        resource_id = str(data.get("id", "")).strip()
        if not resource_id:
            raise InferenceOptimizationError("resource id is required")
        supported = tuple(str(item) for item in data.get("supported_model_types", []))
        if not supported:
            raise InferenceOptimizationError(
                f"resource {resource_id} must define supported_model_types"
            )
        return cls(
            id=resource_id,
            accelerator=str(data.get("accelerator", "cpu")),
            cpu_cores=int(data.get("cpu_cores", 0)),
            memory_gb=float(data.get("memory_gb", 0)),
            gpu_memory_gb=float(data.get("gpu_memory_gb", 0)),
            expected_latency_ms=float(data.get("expected_latency_ms", 0)),
            expected_throughput_rps=float(data.get("expected_throughput_rps", 0)),
            cost_per_hour=float(data.get("cost_per_hour", 0)),
            available_replicas=int(data.get("available_replicas", 0)),
            supported_model_types=supported,
            node_selector={
                str(key): str(value)
                for key, value in dict(data.get("node_selector", {})).items()
            },
            resource_limits={
                str(key): str(value)
                for key, value in dict(data.get("resource_limits", {})).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["supported_model_types"] = list(self.supported_model_types)
        return data


@dataclass(frozen=True)
class InferenceWorkload:
    id: str
    model_type: str
    requires_accelerator: bool
    estimated_vram_gb: float
    latency_slo_ms: float
    min_throughput_rps: float
    batch_size: int
    service_name: str
    namespace: str
    container_image: str
    replicas: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InferenceWorkload:
        workload_id = str(data.get("id", "")).strip()
        if not workload_id:
            raise InferenceOptimizationError("workload id is required")
        return cls(
            id=workload_id,
            model_type=str(data.get("model_type", "")),
            requires_accelerator=bool(data.get("requires_accelerator", False)),
            estimated_vram_gb=float(data.get("estimated_vram_gb", 0)),
            latency_slo_ms=float(data.get("latency_slo_ms", 0)),
            min_throughput_rps=float(data.get("min_throughput_rps", 0)),
            batch_size=int(data.get("batch_size", 1)),
            service_name=str(data.get("service_name", workload_id)),
            namespace=str(data.get("namespace", "ai-inference")),
            container_image=str(
                data.get(
                    "container_image",
                    "ghcr.io/example/ai-inference:latest",
                )
            ),
            replicas=int(data.get("replicas", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InferenceOptimizationConfig:
    version: str
    weights: OptimizationWeights
    resources: dict[str, InferenceResourceProfile]
    workloads: dict[str, InferenceWorkload]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InferenceOptimizationConfig:
        resources: dict[str, InferenceResourceProfile] = {}
        for raw_resource in data.get("resources", []):
            resource = InferenceResourceProfile.from_dict(dict(raw_resource))
            if resource.id in resources:
                raise InferenceOptimizationError(f"duplicate resource: {resource.id}")
            resources[resource.id] = resource

        workloads: dict[str, InferenceWorkload] = {}
        for raw_workload in data.get("workloads", []):
            workload = InferenceWorkload.from_dict(dict(raw_workload))
            if workload.id in workloads:
                raise InferenceOptimizationError(f"duplicate workload: {workload.id}")
            workloads[workload.id] = workload

        if not resources:
            raise InferenceOptimizationError("at least one resource is required")
        if not workloads:
            raise InferenceOptimizationError("at least one workload is required")

        return cls(
            version=str(data.get("version", "1")),
            weights=OptimizationWeights.from_dict(dict(data.get("weights", {}))),
            resources=resources,
            workloads=workloads,
        )

    def get_workload(self, workload_id: str) -> InferenceWorkload:
        try:
            return self.workloads[workload_id]
        except KeyError as exc:
            raise InferenceOptimizationError(
                f"unknown inference workload: {workload_id}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "weights": asdict(self.weights),
            "resources": [
                self.resources[resource_id].to_dict()
                for resource_id in sorted(self.resources)
            ],
            "workloads": [
                self.workloads[workload_id].to_dict()
                for workload_id in sorted(self.workloads)
            ],
        }


@dataclass(frozen=True)
class InferencePlacementDecision:
    valid: bool
    workload: str
    selected_resource: str
    action: str
    score: float
    latency_ms: float
    throughput_rps: float
    cost_per_hour: float
    slo_satisfied: bool
    reason: str
    rejected_resources: dict[str, str]
    ranked_candidates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InferenceDeploymentPlan:
    valid: bool
    workload: str
    selected_resource: str
    action: str
    score: float
    reason: str
    deployment_plan: dict[str, Any]
    rejected_resources: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_inference_optimization_config(
    path: str | Path,
) -> InferenceOptimizationConfig:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return InferenceOptimizationConfig.from_dict(data)


def recommend_inference_placement(
    config: InferenceOptimizationConfig,
    workload_id: str,
) -> InferencePlacementDecision:
    workload = config.get_workload(workload_id)
    rejected: dict[str, str] = {}
    eligible = []

    for resource in config.resources.values():
        rejection = _rejection_reason(resource, workload)
        if rejection:
            rejected[resource.id] = rejection
            continue
        eligible.append(resource)

    if not eligible:
        return InferencePlacementDecision(
            valid=False,
            workload=workload.id,
            selected_resource="",
            action="",
            score=0.0,
            latency_ms=0.0,
            throughput_rps=0.0,
            cost_per_hour=0.0,
            slo_satisfied=False,
            reason="no eligible CPU/GPU VM resource satisfied the workload constraints",
            rejected_resources=rejected,
            ranked_candidates=[],
        )

    min_cost = min(resource.cost_per_hour for resource in eligible)
    max_capacity = max(resource.available_replicas for resource in eligible) or 1
    ranked = []
    for resource in eligible:
        score = _score_resource(config.weights, resource, workload, min_cost, max_capacity)
        ranked.append(
            {
                "resource": resource.id,
                "accelerator": resource.accelerator,
                "score": round(score, 6),
                "latency_ms": resource.expected_latency_ms,
                "throughput_rps": resource.expected_throughput_rps,
                "cost_per_hour": resource.cost_per_hour,
                "available_replicas": resource.available_replicas,
                "action": _action_for_resource(resource),
            }
        )

    ranked.sort(
        key=lambda item: (
            -float(item["score"]),
            float(item["cost_per_hour"]),
            str(item["resource"]),
        )
    )
    best = ranked[0]

    return InferencePlacementDecision(
        valid=True,
        workload=workload.id,
        selected_resource=str(best["resource"]),
        action=str(best["action"]),
        score=float(best["score"]),
        latency_ms=float(best["latency_ms"]),
        throughput_rps=float(best["throughput_rps"]),
        cost_per_hour=float(best["cost_per_hour"]),
        slo_satisfied=True,
        reason=(
            "selected resource satisfies latency, throughput, accelerator, "
            "and capacity constraints"
        ),
        rejected_resources=rejected,
        ranked_candidates=ranked,
    )


def build_inference_deployment_plan(
    config: InferenceOptimizationConfig,
    workload_id: str,
) -> InferenceDeploymentPlan:
    workload = config.get_workload(workload_id)
    decision = recommend_inference_placement(config, workload_id)
    if not decision.valid:
        return InferenceDeploymentPlan(
            valid=False,
            workload=workload.id,
            selected_resource="",
            action="",
            score=0.0,
            reason=decision.reason,
            deployment_plan={},
            rejected_resources=decision.rejected_resources,
        )

    resource = config.resources[decision.selected_resource]
    deployment_plan = {
        "service_name": workload.service_name,
        "container_image": workload.container_image,
        "target_resource": resource.id,
        "target_accelerator": resource.accelerator,
        "kubernetes": {
            "namespace": workload.namespace,
            "deployment": workload.service_name,
            "replicas": workload.replicas,
            "node_selector": resource.node_selector
            or {"aiops.resource/accelerator": resource.accelerator},
            "resources": _kubernetes_resource_spec(resource, workload),
        },
        "control_actions": [
            decision.action,
            "scale_replicas",
            "monitor_latency",
            "rollback_on_slo_violation",
        ],
        "monitoring_metrics": [
            "inference_latency_ms",
            "inference_throughput_rps",
            "gpu_memory_utilization",
            "cost_per_hour",
        ],
        "slo": {
            "latency_ms": workload.latency_slo_ms,
            "min_throughput_rps": workload.min_throughput_rps,
        },
    }
    return InferenceDeploymentPlan(
        valid=True,
        workload=workload.id,
        selected_resource=resource.id,
        action=decision.action,
        score=decision.score,
        reason=decision.reason,
        deployment_plan=deployment_plan,
        rejected_resources=decision.rejected_resources,
    )


def _rejection_reason(
    resource: InferenceResourceProfile,
    workload: InferenceWorkload,
) -> str:
    if workload.requires_accelerator and resource.accelerator == "cpu":
        return "accelerator required but resource is CPU-only"
    if workload.model_type not in resource.supported_model_types:
        return f"model type {workload.model_type} is not supported"
    if (
        resource.accelerator != "cpu"
        and workload.estimated_vram_gb > resource.gpu_memory_gb
    ):
        return (
            f"estimated VRAM {workload.estimated_vram_gb:g}GB exceeds "
            f"resource GPU memory {resource.gpu_memory_gb:g}GB"
        )
    if resource.expected_latency_ms > workload.latency_slo_ms:
        return (
            f"latency {resource.expected_latency_ms:g}ms exceeds "
            f"SLO {workload.latency_slo_ms:g}ms"
        )
    if resource.expected_throughput_rps < workload.min_throughput_rps:
        return (
            f"throughput {resource.expected_throughput_rps:g}rps is below "
            f"required {workload.min_throughput_rps:g}rps"
        )
    if resource.available_replicas <= 0:
        return "no available VM capacity"
    return ""


def _score_resource(
    weights: OptimizationWeights,
    resource: InferenceResourceProfile,
    workload: InferenceWorkload,
    min_cost: float,
    max_capacity: int,
) -> float:
    latency_score = min(workload.latency_slo_ms / resource.expected_latency_ms, 1.0)
    throughput_score = min(
        resource.expected_throughput_rps / workload.min_throughput_rps,
        1.0,
    )
    cost_score = min_cost / resource.cost_per_hour if resource.cost_per_hour else 0.0
    capacity_score = resource.available_replicas / max_capacity
    return (
        weights.latency * latency_score
        + weights.throughput * throughput_score
        + weights.cost * cost_score
        + weights.capacity * capacity_score
    )


def _action_for_resource(resource: InferenceResourceProfile) -> str:
    if resource.accelerator == "gpu":
        return "deploy_on_gpu_vm"
    if resource.accelerator == "npu":
        return "deploy_on_npu_vm"
    return "deploy_on_cpu_vm"


def _kubernetes_resource_spec(
    resource: InferenceResourceProfile,
    workload: InferenceWorkload,
) -> dict[str, dict[str, str]]:
    requests = {
        "cpu": str(max(1, min(resource.cpu_cores, 8))),
        "memory": f"{max(1, min(int(resource.memory_gb), 32))}Gi",
    }
    limits = dict(resource.resource_limits)
    if resource.accelerator == "gpu" and "nvidia.com/gpu" not in limits:
        limits["nvidia.com/gpu"] = "1"
    if resource.accelerator == "npu" and "aiops.dev/npu" not in limits:
        limits["aiops.dev/npu"] = "1"
    if workload.estimated_vram_gb > 0 and resource.accelerator != "cpu":
        limits.setdefault("aiops.dev/vram-gb", str(int(workload.estimated_vram_gb)))
    return {"requests": requests, "limits": limits}
