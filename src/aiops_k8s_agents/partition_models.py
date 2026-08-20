from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence


class PartitionContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PartitionContractError("invalid_contract", f"{field} must be an object")
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PartitionContractError("invalid_contract", f"{field} must be an array")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PartitionContractError("invalid_contract", f"{field} is required")
    return text


def _float(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise PartitionContractError("invalid_contract", f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_contract", f"{field} must be numeric"
        ) from exc
    if not isfinite(number) or number < minimum:
        raise PartitionContractError(
            "invalid_contract", f"{field} must be at least {minimum}"
        )
    return number


def _int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PartitionContractError("invalid_contract", f"{field} must be an integer")
    if value < minimum:
        raise PartitionContractError(
            "invalid_contract", f"{field} must be at least {minimum}"
        )
    return value


@dataclass(frozen=True)
class ApprovedExecutionMode:
    name: str
    approved: bool
    approved_by: str
    approval_ref: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ApprovedExecutionMode:
        name = _text(payload.get("name"), "execution_mode.name")
        if payload.get("approved") is not True:
            raise PartitionContractError(
                "approved_mode_required",
                "execution mode must be approved by the upstream coordinator",
            )
        approved_by = str(payload.get("approved_by") or "").strip()
        approval_ref = str(payload.get("approval_ref") or "").strip()
        if not approved_by or not approval_ref:
            raise PartitionContractError(
                "approval_provenance_required",
                "approved_by and approval_ref are required",
            )
        return cls(name, True, approved_by, approval_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "approved": self.approved,
            "approved_by": self.approved_by,
            "approval_ref": self.approval_ref,
        }


@dataclass(frozen=True)
class ModelLayer:
    name: str
    compute_units: float
    parameter_bytes: int
    activation_bytes: int
    working_memory_bytes: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModelLayer:
        return cls(
            name=_text(payload.get("name"), "layers.name"),
            compute_units=_float(
                payload.get("compute_units"), "layers.compute_units", minimum=0.000001
            ),
            parameter_bytes=_int(payload.get("parameter_bytes"), "layers.parameter_bytes"),
            activation_bytes=_int(
                payload.get("activation_bytes"), "layers.activation_bytes"
            ),
            working_memory_bytes=_int(
                payload.get("working_memory_bytes"), "layers.working_memory_bytes"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "compute_units": self.compute_units,
            "parameter_bytes": self.parameter_bytes,
            "activation_bytes": self.activation_bytes,
            "working_memory_bytes": self.working_memory_bytes,
        }


@dataclass(frozen=True)
class ResourceDevice:
    device_id: str
    device_type: str
    compute_units_per_second: float
    memory_capacity_bytes: int
    memory_available_bytes: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResourceDevice:
        device = cls(
            device_id=_text(payload.get("device_id"), "devices.device_id"),
            device_type=_text(payload.get("device_type"), "devices.device_type"),
            compute_units_per_second=_float(
                payload.get("compute_units_per_second"),
                "devices.compute_units_per_second",
                minimum=0.000001,
            ),
            memory_capacity_bytes=_int(
                payload.get("memory_capacity_bytes"),
                "devices.memory_capacity_bytes",
                minimum=1,
            ),
            memory_available_bytes=_int(
                payload.get("memory_available_bytes"),
                "devices.memory_available_bytes",
            ),
        )
        if device.memory_available_bytes > device.memory_capacity_bytes:
            raise PartitionContractError(
                "invalid_memory_snapshot",
                f"available memory exceeds capacity for {device.device_id}",
            )
        return device

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "compute_units_per_second": self.compute_units_per_second,
            "memory_capacity_bytes": self.memory_capacity_bytes,
            "memory_available_bytes": self.memory_available_bytes,
        }


@dataclass(frozen=True)
class NetworkLink:
    source_device: str
    target_device: str
    bandwidth_bytes_per_second: float
    latency_ms: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> NetworkLink:
        return cls(
            source_device=_text(
                payload.get("source_device"), "network_links.source_device"
            ),
            target_device=_text(
                payload.get("target_device"), "network_links.target_device"
            ),
            bandwidth_bytes_per_second=_float(
                payload.get("bandwidth_bytes_per_second"),
                "network_links.bandwidth_bytes_per_second",
                minimum=0.000001,
            ),
            latency_ms=_float(payload.get("latency_ms"), "network_links.latency_ms"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_device": self.source_device,
            "target_device": self.target_device,
            "bandwidth_bytes_per_second": self.bandwidth_bytes_per_second,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class PartitionConstraints:
    max_end_to_end_latency_ms: float | None
    max_transfer_bytes: int | None
    minimum_memory_headroom_ratio: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionConstraints:
        latency_value = payload.get("max_end_to_end_latency_ms")
        transfer_value = payload.get("max_transfer_bytes")
        headroom = _float(
            payload.get("minimum_memory_headroom_ratio", 0.0),
            "constraints.minimum_memory_headroom_ratio",
        )
        if headroom >= 1.0:
            raise PartitionContractError(
                "invalid_contract",
                "minimum_memory_headroom_ratio must be below 1.0",
            )
        return cls(
            max_end_to_end_latency_ms=(
                None
                if latency_value is None
                else _float(
                    latency_value,
                    "constraints.max_end_to_end_latency_ms",
                    minimum=0.000001,
                )
            ),
            max_transfer_bytes=(
                None
                if transfer_value is None
                else _int(
                    transfer_value,
                    "constraints.max_transfer_bytes",
                    minimum=1,
                )
            ),
            minimum_memory_headroom_ratio=headroom,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_end_to_end_latency_ms": self.max_end_to_end_latency_ms,
            "max_transfer_bytes": self.max_transfer_bytes,
            "minimum_memory_headroom_ratio": self.minimum_memory_headroom_ratio,
        }


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FederatedRoundPlan:
        payload = _mapping(payload, "round_plan")
        layers = tuple(
            ModelLayer.from_dict(_mapping(item, "layers[]"))
            for item in _sequence(payload.get("layers"), "layers")
        )
        participants = tuple(
            _text(item, "participants[]")
            for item in _sequence(payload.get("participants"), "participants")
        )
        devices = tuple(
            ResourceDevice.from_dict(_mapping(item, "devices[]"))
            for item in _sequence(payload.get("devices"), "devices")
        )
        links = tuple(
            NetworkLink.from_dict(_mapping(item, "network_links[]"))
            for item in _sequence(payload.get("network_links"), "network_links")
        )
        if len(layers) < 2:
            raise PartitionContractError(
                "insufficient_layers", "at least two ordered layers are required"
            )
        if len(participants) < 2:
            raise PartitionContractError(
                "insufficient_participants", "at least two participants are required"
            )
        if len(layers) < len(participants):
            raise PartitionContractError(
                "insufficient_layers", "each participant requires a non-empty partition"
            )
        _require_unique((layer.name for layer in layers), "duplicate_layer")
        _require_unique(participants, "duplicate_participant")
        _require_unique((device.device_id for device in devices), "duplicate_device")
        _require_unique(
            ((link.source_device, link.target_device) for link in links),
            "duplicate_network_link",
        )
        device_ids = {device.device_id for device in devices}
        for participant in participants:
            if participant not in device_ids:
                raise PartitionContractError(
                    "unknown_participant", f"participant {participant} has no device snapshot"
                )
        for link in links:
            if link.source_device not in device_ids or link.target_device not in device_ids:
                raise PartitionContractError(
                    "unknown_network_device",
                    f"link {link.source_device}->{link.target_device} references an unknown device",
                )
        link_pairs = {(link.source_device, link.target_device) for link in links}
        for source, target in zip(participants, participants[1:]):
            if (source, target) not in link_pairs:
                raise PartitionContractError(
                    "missing_network_link", f"missing link {source}->{target}"
                )
        return cls(
            job_id=_text(payload.get("job_id"), "job_id"),
            model_id=_text(payload.get("model_id"), "model_id"),
            execution_mode=ApprovedExecutionMode.from_dict(
                _mapping(payload.get("execution_mode"), "execution_mode")
            ),
            layers=layers,
            participants=participants,
            devices=devices,
            network_links=links,
            constraints=PartitionConstraints.from_dict(
                _mapping(payload.get("constraints", {}), "constraints")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "model_id": self.model_id,
            "execution_mode": self.execution_mode.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "participants": list(self.participants),
            "devices": [device.to_dict() for device in self.devices],
            "network_links": [link.to_dict() for link in self.network_links],
            "constraints": self.constraints.to_dict(),
        }


def _require_unique(values: Any, code: str) -> None:
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            raise PartitionContractError(code, f"duplicate value: {value}")
        seen.add(value)


@dataclass(frozen=True)
class LogicalPartition:
    partition_id: str
    device_id: str
    layer_names: tuple[str, ...]
    compute_units: float
    memory_demand_bytes: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LogicalPartition:
        return cls(
            partition_id=_text(payload.get("partition_id"), "partition_id"),
            device_id=_text(payload.get("device_id"), "device_id"),
            layer_names=tuple(
                _text(item, "layer_names[]")
                for item in _sequence(payload.get("layer_names"), "layer_names")
            ),
            compute_units=_float(payload.get("compute_units"), "compute_units"),
            memory_demand_bytes=_int(
                payload.get("memory_demand_bytes"), "memory_demand_bytes"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "device_id": self.device_id,
            "layer_names": list(self.layer_names),
            "compute_units": self.compute_units,
            "memory_demand_bytes": self.memory_demand_bytes,
        }


@dataclass(frozen=True)
class ExecutionGraphNode:
    partition_id: str
    device_id: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionGraphNode:
        return cls(
            _text(payload.get("partition_id"), "partition_id"),
            _text(payload.get("device_id"), "device_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"partition_id": self.partition_id, "device_id": self.device_id}


@dataclass(frozen=True)
class ExecutionGraphEdge:
    source_partition: str
    target_partition: str
    transfer_bytes: int
    estimated_transfer_ms: float
    edge_type: str = "forward"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExecutionGraphEdge:
        edge_type = _text(payload.get("edge_type", "forward"), "edge_type")
        if edge_type not in {"forward", "backward", "gradient", "aggregation"}:
            raise PartitionContractError(
                "invalid_contract", "edge_type must be forward, backward, gradient, or aggregation"
            )
        return cls(
            source_partition=_text(
                payload.get("source_partition"), "source_partition"
            ),
            target_partition=_text(
                payload.get("target_partition"), "target_partition"
            ),
            transfer_bytes=_int(payload.get("transfer_bytes"), "transfer_bytes"),
            estimated_transfer_ms=_float(
                payload.get("estimated_transfer_ms"), "estimated_transfer_ms"
            ),
            edge_type=edge_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_partition": self.source_partition,
            "target_partition": self.target_partition,
            "transfer_bytes": self.transfer_bytes,
            "estimated_transfer_ms": self.estimated_transfer_ms,
            "edge_type": self.edge_type,
        }


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
    estimated_step_time_ms: float = 0.0
    gradient_transfer_bytes: int = 0
    maximum_load_imbalance: float = 0.0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionCandidate:
        return cls(
            split_points=tuple(
                _int(item, "split_points[]", minimum=1)
                for item in _sequence(payload.get("split_points"), "split_points")
            ),
            partitions=tuple(
                LogicalPartition.from_dict(_mapping(item, "partitions[]"))
                for item in _sequence(payload.get("partitions"), "partitions")
            ),
            graph_nodes=tuple(
                ExecutionGraphNode.from_dict(_mapping(item, "graph_nodes[]"))
                for item in _sequence(payload.get("graph_nodes"), "graph_nodes")
            ),
            graph_edges=tuple(
                ExecutionGraphEdge.from_dict(_mapping(item, "graph_edges[]"))
                for item in _sequence(payload.get("graph_edges"), "graph_edges")
            ),
            estimated_compute_ms=_float(
                payload.get("estimated_compute_ms"), "estimated_compute_ms"
            ),
            estimated_transfer_ms=_float(
                payload.get("estimated_transfer_ms"), "estimated_transfer_ms"
            ),
            estimated_total_latency_ms=_float(
                payload.get("estimated_total_latency_ms"),
                "estimated_total_latency_ms",
            ),
            total_transfer_bytes=_int(
                payload.get("total_transfer_bytes"), "total_transfer_bytes"
            ),
            maximum_memory_pressure=_float(
                payload.get("maximum_memory_pressure"), "maximum_memory_pressure"
            ),
            valid=bool(payload.get("valid")),
            rejection_reasons=tuple(
                str(item)
                for item in _sequence(
                    payload.get("rejection_reasons", []), "rejection_reasons"
                )
            ),
            score=_float(payload.get("score"), "score"),
            estimated_step_time_ms=_float(
                payload.get("estimated_step_time_ms", 0.0), "estimated_step_time_ms"
            ),
            gradient_transfer_bytes=_int(
                payload.get("gradient_transfer_bytes", 0), "gradient_transfer_bytes"
            ),
            maximum_load_imbalance=_float(
                payload.get("maximum_load_imbalance", 0.0), "maximum_load_imbalance"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_points": list(self.split_points),
            "partitions": [partition.to_dict() for partition in self.partitions],
            "graph_nodes": [node.to_dict() for node in self.graph_nodes],
            "graph_edges": [edge.to_dict() for edge in self.graph_edges],
            "estimated_compute_ms": self.estimated_compute_ms,
            "estimated_transfer_ms": self.estimated_transfer_ms,
            "estimated_total_latency_ms": self.estimated_total_latency_ms,
            "total_transfer_bytes": self.total_transfer_bytes,
            "maximum_memory_pressure": self.maximum_memory_pressure,
            "valid": self.valid,
            "rejection_reasons": list(self.rejection_reasons),
            "score": self.score,
            "estimated_step_time_ms": self.estimated_step_time_ms,
            "gradient_transfer_bytes": self.gradient_transfer_bytes,
            "maximum_load_imbalance": self.maximum_load_imbalance,
        }


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionExecutionPlan:
        selected = payload.get("selected_candidate")
        return cls(
            plan_id=_text(payload.get("plan_id"), "plan_id"),
            job_id=_text(payload.get("job_id"), "job_id"),
            model_id=_text(payload.get("model_id"), "model_id"),
            approved_execution_mode=_text(
                payload.get("approved_execution_mode"), "approved_execution_mode"
            ),
            policy_version=_text(payload.get("policy_version"), "policy_version"),
            selected_candidate=(
                None
                if selected is None
                else PartitionCandidate.from_dict(
                    _mapping(selected, "selected_candidate")
                )
            ),
            alternative_candidates=tuple(
                PartitionCandidate.from_dict(
                    _mapping(item, "alternative_candidates[]")
                )
                for item in _sequence(
                    payload.get("alternative_candidates", []),
                    "alternative_candidates",
                )
            ),
            rationale=str(payload.get("rationale") or ""),
            valid=bool(payload.get("valid")),
            human_review_required=bool(payload.get("human_review_required")),
            errors=tuple(
                str(item)
                for item in _sequence(payload.get("errors", []), "errors")
            ),
            plan_version=_int(payload.get("plan_version", 1), "plan_version", minimum=1),
            parent_plan_id=(
                None
                if payload.get("parent_plan_id") is None
                else str(payload.get("parent_plan_id") or "").strip() or None
            ),
            plan_type=str(payload.get("plan_type") or "inference"),
            approved_model_version=str(payload.get("approved_model_version") or "legacy"),
            strategy_id=str(payload.get("strategy_id") or "legacy-partition-v1"),
            strategy_version=str(payload.get("strategy_version") or "1.0"),
            input_snapshot_id=str(payload.get("input_snapshot_id") or "legacy-snapshot"),
            input_snapshot_hash=str(payload.get("input_snapshot_hash") or ""),
            assumptions=tuple(
                str(item)
                for item in _sequence(payload.get("assumptions", []), "assumptions")
            ),
            warnings=tuple(
                str(item)
                for item in _sequence(payload.get("warnings", []), "warnings")
            ),
            confidence=_float(payload.get("confidence", 0.0), "confidence"),
            deterministic_signature=str(payload.get("deterministic_signature") or ""),
            handoff_status=str(payload.get("handoff_status") or "not_ready"),
        )

    @classmethod
    def safe_failure(
        cls,
        *,
        plan_id: str,
        job_id: str,
        model_id: str,
        approved_execution_mode: str,
        policy_version: str,
        errors: tuple[str, ...],
        alternative_candidates: tuple[PartitionCandidate, ...] = (),
    ) -> PartitionExecutionPlan:
        return cls(
            plan_id=plan_id,
            job_id=job_id,
            model_id=model_id,
            approved_execution_mode=approved_execution_mode,
            policy_version=policy_version,
            selected_candidate=None,
            alternative_candidates=alternative_candidates,
            rationale="No feasible partition plan; human review is required.",
            valid=False,
            human_review_required=True,
            errors=errors,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "job_id": self.job_id,
            "model_id": self.model_id,
            "approved_execution_mode": self.approved_execution_mode,
            "policy_version": self.policy_version,
            "selected_candidate": (
                None
                if self.selected_candidate is None
                else self.selected_candidate.to_dict()
            ),
            "alternative_candidates": [
                candidate.to_dict() for candidate in self.alternative_candidates
            ],
            "rationale": self.rationale,
            "valid": self.valid,
            "human_review_required": self.human_review_required,
            "errors": list(self.errors),
            "plan_version": self.plan_version,
            "parent_plan_id": self.parent_plan_id,
            "plan_type": self.plan_type,
            "approved_model_version": self.approved_model_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "input_snapshot_id": self.input_snapshot_id,
            "input_snapshot_hash": self.input_snapshot_hash,
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
            "confidence": self.confidence,
            "deterministic_signature": self.deterministic_signature,
            "handoff_status": self.handoff_status,
        }


PARTITION_FAILURE_SIGNALS = frozenset(
    {
        "device_unavailable",
        "memory_exceeded",
        "latency_slo_violation",
        "transfer_failure",
    }
)


@dataclass(frozen=True)
class PartitionFailure:
    signal: str
    device_id: str = ""
    source_device: str = ""
    target_device: str = ""
    details: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionFailure:
        signal = _text(payload.get("signal"), "failure.signal")
        if signal not in PARTITION_FAILURE_SIGNALS:
            raise PartitionContractError(
                "unsupported_failure_signal", f"unsupported failure signal: {signal}"
            )
        failure = cls(
            signal=signal,
            device_id=str(payload.get("device_id") or "").strip(),
            source_device=str(payload.get("source_device") or "").strip(),
            target_device=str(payload.get("target_device") or "").strip(),
            details=str(payload.get("details") or "").strip(),
        )
        if signal in {"device_unavailable", "memory_exceeded"} and not failure.device_id:
            raise PartitionContractError(
                "failure_context_required", f"{signal} requires device_id"
            )
        if signal == "transfer_failure" and (
            not failure.source_device or not failure.target_device
        ):
            raise PartitionContractError(
                "failure_context_required",
                "transfer_failure requires source_device and target_device",
            )
        return failure

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "device_id": self.device_id,
            "source_device": self.source_device,
            "target_device": self.target_device,
            "details": self.details,
        }
