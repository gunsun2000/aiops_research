from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from orchestrator_agent.partition_context import (
    ModelRegistryContext,
    ModelStructureProfile,
    PartitionSystemContext,
    WorkloadForecast,
)
from orchestrator_agent.partition_coordination import (
    CoordinationPlanEnvelope,
    InferenceCoordinationPlan,
    PartitionPlanningRequest,
    TrainingCoordinationPlan,
)
from orchestrator_agent.partition_models import (
    ApprovedExecutionMode,
    NetworkLink,
    PartitionConstraints,
    PartitionContractError,
    ResourceDevice,
)


SUPPORTED_SCHEMA_VERSION = "0.4"
MODE_MAPPING = {
    ("federated_training", "FL"): ("training", "federated_learning"),
    ("federated_training", "SL"): ("training", "split_learning"),
    ("distributed_inference", "PARTITIONED"): ("inference", "split_inference"),
}


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PartitionContractError(
            "invalid_federated_coordination_plan", f"{field} must be an object"
        )
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PartitionContractError(
            "invalid_federated_coordination_plan", f"{field} must be an array"
        )
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PartitionContractError(
            "invalid_federated_coordination_plan", f"{field} is required"
        )
    return text


def _version(value: Any, field: str) -> str:
    if isinstance(value, bool):
        raise PartitionContractError(
            "invalid_federated_coordination_plan", f"{field} is invalid"
        )
    return _text(value, field)


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PartitionContractError(
            "invalid_federated_coordination_plan",
            f"{field} must be an integer of at least {minimum}",
        )
    return value


def _number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise PartitionContractError(
            "invalid_federated_coordination_plan", f"{field} must be numeric"
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_federated_coordination_plan", f"{field} must be numeric"
        ) from exc
    if not isfinite(number) or number < minimum:
        raise PartitionContractError(
            "invalid_federated_coordination_plan",
            f"{field} must be at least {minimum}",
        )
    return number


@dataclass(frozen=True)
class FederatedParticipantV04:
    client_id: str
    priority: int


@dataclass(frozen=True)
class FederatedCoordinationPlanV04:
    schema_version: str
    task_type: str
    plan_id: str
    job_id: str
    session_id: str
    model_id: str
    model_version: str
    selected_mode: str
    fallback_order: tuple[str, ...]
    participants: tuple[FederatedParticipantV04, ...]
    coordination_mode: Mapping[str, Any]
    federated_strategy: Mapping[str, Any]
    participation_policy: Mapping[str, Any]
    serving_policy: Mapping[str, Any]
    original_payload: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FederatedCoordinationPlanV04:
        payload = _mapping(payload, "coordination_plan")
        schema_version = _text(payload.get("schema_version"), "schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise PartitionContractError(
                "unsupported_coordination_schema",
                f"schema_version must be {SUPPORTED_SCHEMA_VERSION}",
            )
        task_type = _text(payload.get("task_type"), "task_type")
        mode_field = (
            "learning_mode" if task_type == "federated_training" else "inference_mode"
        )
        if task_type not in {"federated_training", "distributed_inference"}:
            raise PartitionContractError(
                "unsupported_coordination_task",
                f"unsupported task_type: {task_type}",
            )
        mode_payload = _mapping(payload.get(mode_field), mode_field)
        selected_mode = _text(mode_payload.get("selected"), f"{mode_field}.selected").upper()
        if (task_type, selected_mode) not in MODE_MAPPING:
            raise PartitionContractError(
                "unsupported_coordination_mode",
                f"unsupported selected mode: {task_type}/{selected_mode}",
            )
        fallback_order = tuple(
            _text(item, f"{mode_field}.fallback_order[]").upper()
            for item in _sequence(mode_payload.get("fallback_order", []), f"{mode_field}.fallback_order")
        )

        participant_payloads = _sequence(
            payload.get("candidate_participants"), "candidate_participants"
        )
        participants = tuple(
            FederatedParticipantV04(
                client_id=_text(
                    _mapping(item, "candidate_participants[]").get("client_id"),
                    "candidate_participants[].client_id",
                ),
                priority=_integer(
                    _mapping(item, "candidate_participants[]").get("priority"),
                    "candidate_participants[].priority",
                    minimum=1,
                ),
            )
            for item in participant_payloads
        )
        if len(participants) < 2:
            raise PartitionContractError(
                "insufficient_participants",
                "at least two candidate participants are required",
            )
        client_ids = [participant.client_id for participant in participants]
        priorities = [participant.priority for participant in participants]
        if len(set(client_ids)) != len(client_ids) or len(set(priorities)) != len(priorities):
            raise PartitionContractError(
                "invalid_federated_coordination_plan",
                "candidate participant IDs and priorities must be unique",
            )
        participants = tuple(sorted(participants, key=lambda item: (item.priority, item.client_id)))

        model_ref = _mapping(payload.get("model_ref"), "model_ref")
        plan_id = _text(
            payload.get("inference_plan_id") or payload.get("round_plan_id"),
            "round_plan_id or inference_plan_id",
        )
        return cls(
            schema_version=schema_version,
            task_type=task_type,
            plan_id=plan_id,
            job_id=_text(payload.get("job_id"), "job_id"),
            session_id=_text(payload.get("session_id"), "session_id"),
            model_id=_text(model_ref.get("model_id"), "model_ref.model_id"),
            model_version=_version(model_ref.get("version"), "model_ref.version"),
            selected_mode=selected_mode,
            fallback_order=fallback_order,
            participants=participants,
            coordination_mode=dict(
                _mapping(payload.get("coordination_mode", {}), "coordination_mode")
            ),
            federated_strategy=dict(
                _mapping(payload.get("federated_strategy", {}), "federated_strategy")
            ),
            participation_policy=dict(
                _mapping(payload.get("participation_policy", {}), "participation_policy")
            ),
            serving_policy=dict(
                _mapping(payload.get("serving_policy", {}), "serving_policy")
            ),
            original_payload=deepcopy(dict(payload)),
        )

    @property
    def participant_ids(self) -> tuple[str, ...]:
        return tuple(participant.client_id for participant in self.participants)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self.original_payload))


@dataclass(frozen=True)
class ParticipantContext:
    snapshot_id: str
    snapshot_version: str
    collected_at: str
    devices: tuple[ResourceDevice, ...]
    network_links: tuple[NetworkLink, ...]
    workload_forecast: WorkloadForecast | None
    source: str


@dataclass(frozen=True)
class ModelContext:
    profile: ModelStructureProfile
    registry: ModelRegistryContext
    source: str


class ParticipantContextProvider(Protocol):
    def resolve(self, participant_ids: tuple[str, ...]) -> ParticipantContext: ...


class ModelContextProvider(Protocol):
    def resolve(self, model_id: str, model_version: str) -> ModelContext: ...


@dataclass(frozen=True)
class MappingParticipantContextProvider:
    context: ParticipantContext

    def resolve(self, participant_ids: tuple[str, ...]) -> ParticipantContext:
        requested = set(participant_ids)
        devices = tuple(
            device for device in self.context.devices if device.device_id in requested
        )
        if {device.device_id for device in devices} != requested:
            raise PartitionContractError(
                "participant_context_missing",
                "resource context is missing for one or more candidate participants",
            )
        links = tuple(
            link
            for link in self.context.network_links
            if link.source_device in requested and link.target_device in requested
        )
        return ParticipantContext(
            snapshot_id=self.context.snapshot_id,
            snapshot_version=self.context.snapshot_version,
            collected_at=self.context.collected_at,
            devices=devices,
            network_links=links,
            workload_forecast=self.context.workload_forecast,
            source=self.context.source,
        )


def participant_context_from_fca_snapshot(
    plan: FederatedCoordinationPlanV04,
) -> ParticipantContext:
    """Build the partition resource context from the exact FCA snapshot."""
    snapshot = _mapping(
        plan.original_payload.get("system_snapshot"), "system_snapshot"
    )
    resources = _mapping(
        snapshot.get("resource_summary", {}), "system_snapshot.resource_summary"
    )
    nodes = _mapping(
        resources.get("nodes", {}), "system_snapshot.resource_summary.nodes"
    )
    network = _mapping(
        snapshot.get("network_summary", {}), "system_snapshot.network_summary"
    )
    peers = _mapping(
        network.get("peers", {}), "system_snapshot.network_summary.peers"
    )
    clients = {
        _text(
            _mapping(item, "system_snapshot.clients[]").get("client_id"),
            "client_id",
        ): _mapping(item, "system_snapshot.clients[]")
        for item in _sequence(snapshot.get("clients", []), "system_snapshot.clients")
    }
    devices: list[ResourceDevice] = []
    for participant_id in plan.participant_ids:
        client = clients.get(participant_id)
        node = nodes.get(participant_id)
        if client is None or not isinstance(node, Mapping):
            raise PartitionContractError(
                "participant_context_missing",
                f"Prometheus resource context is missing for {participant_id}",
            )
        if str(client.get("status", "")).lower() != "online":
            raise PartitionContractError(
                "participant_context_stale",
                f"selected participant is no longer online: {participant_id}",
            )
        gpu_memory_available = int(node.get("gpu_memory_allocatable_bytes") or 0)
        has_gpu = bool(node.get("dcgm_available") or gpu_memory_available > 0)
        memory_available = (
            gpu_memory_available
            if has_gpu and gpu_memory_available > 0
            else int(node.get("memory_allocatable_bytes") or 0)
        )
        memory_capacity = (
            int(node.get("gpu_memory_total_bytes") or memory_available)
            if has_gpu
            else int(node.get("memory_total_bytes") or memory_available)
        )
        memory_capacity = max(memory_capacity, memory_available, 1)
        utilization = node.get("gpu_utilization_ratio")
        utilization_ratio = (
            min(max(float(utilization), 0.0), 1.0)
            if isinstance(utilization, (int, float))
            else 0.0
        )
        devices.append(
            ResourceDevice(
                participant_id,
                "gpu" if has_gpu else "cpu",
                max(1.0, 1_000_000_000_000.0 * (1.0 - utilization_ratio)),
                memory_capacity,
                memory_available,
            )
        )

    links: list[NetworkLink] = []
    for source_id in plan.participant_ids:
        for target_id in plan.participant_ids:
            if source_id == target_id:
                continue
            peer = peers.get(target_id, {})
            if not isinstance(peer, Mapping):
                continue
            bandwidth = float(
                peer.get("available_bandwidth_bytes_per_second") or 0
            )
            latency_seconds = peer.get("rtt_seconds")
            if bandwidth <= 0 or not isinstance(latency_seconds, (int, float)):
                continue
            links.append(
                NetworkLink(
                    source_id,
                    target_id,
                    bandwidth,
                    max(0.0, float(latency_seconds) * 1000.0),
                )
            )
    generated_at = str(snapshot.get("generated_at") or "").strip()
    if not generated_at:
        generated_at = datetime.now(timezone.utc).isoformat()
    return ParticipantContext(
        snapshot_id=_text(
            snapshot.get("state_snapshot_id"), "system_snapshot.state_snapshot_id"
        ),
        snapshot_version=_text(
            snapshot.get("state_snapshot_id"), "system_snapshot.state_snapshot_id"
        ),
        collected_at=generated_at,
        devices=tuple(devices),
        network_links=tuple(links),
        workload_forecast=None,
        source=str(snapshot.get("source") or "prometheus"),
    )


@dataclass(frozen=True)
class MappingModelContextProvider:
    contexts: Mapping[tuple[str, str], ModelContext]

    def resolve(self, model_id: str, model_version: str) -> ModelContext:
        context = self.contexts.get((model_id, model_version))
        if context is None:
            raise PartitionContractError(
                "model_context_missing",
                f"model context is unavailable for {model_id}:{model_version}",
            )
        return context


def load_mapping_context_providers(
    path: str | Path,
) -> tuple[MappingParticipantContextProvider, MappingModelContextProvider]:
    config_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PartitionContractError(
            "invalid_context_provider_config",
            f"failed to load federated context configuration: {config_path}",
        ) from exc
    root = _mapping(payload, "federated_context")
    participant_payload = _mapping(
        root.get("participant_context"), "participant_context"
    )
    forecast_payload = participant_payload.get("workload_forecast")
    participant_context = ParticipantContext(
        snapshot_id=_text(
            participant_payload.get("snapshot_id"), "participant_context.snapshot_id"
        ),
        snapshot_version=_text(
            participant_payload.get("snapshot_version"),
            "participant_context.snapshot_version",
        ),
        collected_at=_text(
            participant_payload.get("collected_at"),
            "participant_context.collected_at",
        ),
        devices=tuple(
            ResourceDevice.from_dict(_mapping(item, "participant_context.devices[]"))
            for item in _sequence(
                participant_payload.get("devices"), "participant_context.devices"
            )
        ),
        network_links=tuple(
            NetworkLink.from_dict(
                _mapping(item, "participant_context.network_links[]")
            )
            for item in _sequence(
                participant_payload.get("network_links", []),
                "participant_context.network_links",
            )
        ),
        workload_forecast=(
            None
            if forecast_payload is None
            else WorkloadForecast.from_dict(
                _mapping(forecast_payload, "participant_context.workload_forecast")
            )
        ),
        source=_text(
            participant_payload.get("source"), "participant_context.source"
        ),
    )
    contexts: dict[tuple[str, str], ModelContext] = {}
    for item in _sequence(root.get("model_contexts"), "model_contexts"):
        model_payload = _mapping(item, "model_contexts[]")
        model_id = _text(model_payload.get("model_id"), "model_contexts[].model_id")
        model_version = _version(
            model_payload.get("model_version"), "model_contexts[].model_version"
        )
        key = (model_id, model_version)
        if key in contexts:
            raise PartitionContractError(
                "invalid_context_provider_config",
                f"duplicate model context: {model_id}:{model_version}",
            )
        contexts[key] = ModelContext(
            profile=ModelStructureProfile.from_dict(
                _mapping(model_payload.get("profile"), "model_contexts[].profile")
            ),
            registry=ModelRegistryContext.from_dict(
                _mapping(model_payload.get("registry"), "model_contexts[].registry")
            ),
            source=_text(model_payload.get("source"), "model_contexts[].source"),
        )
    if not participant_context.devices or not contexts:
        raise PartitionContractError(
            "invalid_context_provider_config",
            "participant devices and model contexts are required",
        )
    return (
        MappingParticipantContextProvider(participant_context),
        MappingModelContextProvider(contexts),
    )


class FederatedCoordinationV04Adapter:
    def adapt(
        self,
        plan: FederatedCoordinationPlanV04,
        participant_context: ParticipantContext,
        model_context: ModelContext,
    ) -> PartitionPlanningRequest:
        self._validate_model_context(plan, model_context)
        self._validate_participant_context(plan, participant_context)
        plan_type, execution_mode = MODE_MAPPING[(plan.task_type, plan.selected_mode)]
        constraints = self._constraints(plan)
        v2_plan = (
            TrainingCoordinationPlan(
                model_id=plan.model_id,
                approved_model_version=plan.model_version,
                coordination_mode=str(plan.coordination_mode.get("selected") or "SYNC"),
                participants=plan.participant_ids,
                round_policy=dict(plan.participation_policy),
                aggregation_policy=dict(plan.federated_strategy),
                synchronization_policy=dict(plan.coordination_mode),
                training_objective=f"{plan.task_type}:{plan.selected_mode}",
                resource_budget={},
                constraints=constraints,
            )
            if plan_type == "training"
            else InferenceCoordinationPlan(
                model_id=plan.model_id,
                approved_model_version=plan.model_version,
                service_objective=f"distributed inference for {plan.model_id}",
                latency_slo_ms=self._required_serving_number(
                    plan, "target_latency_ms", minimum=0.000001
                ),
                minimum_throughput_rps=self._minimum_throughput(plan),
                availability_target=_number(
                    plan.serving_policy.get("availability_target", 0.0),
                    "serving_policy.availability_target",
                ),
                traffic_policy=dict(plan.serving_policy),
                concurrency_policy={
                    **dict(plan.serving_policy),
                    "max_requests": _integer(
                        plan.serving_policy.get("max_concurrent_requests"),
                        "serving_policy.max_concurrent_requests",
                        minimum=1,
                    ),
                },
                participants=plan.participant_ids,
                resource_budget={},
                constraints=constraints,
            )
        )
        return PartitionPlanningRequest(
            envelope=CoordinationPlanEnvelope(
                plan_type=plan_type,
                plan_id=plan.plan_id,
                job_id=plan.job_id,
                approved_by="FederatedCoordinationAgent",
                approval_ref=plan.plan_id,
                approved_at=participant_context.collected_at,
                schema_version=plan.schema_version,
            ),
            plan=v2_plan,
            context=PartitionSystemContext(
                snapshot_id=participant_context.snapshot_id,
                snapshot_version=participant_context.snapshot_version,
                collected_at=participant_context.collected_at,
                model_structure_profile=model_context.profile,
                model_registry_context=model_context.registry,
                devices=participant_context.devices,
                network_links=participant_context.network_links,
                workload_forecast=participant_context.workload_forecast,
            ),
            approved_execution_mode=ApprovedExecutionMode(
                name=execution_mode,
                approved=True,
                approved_by="FederatedCoordinationAgent",
                approval_ref=plan.plan_id,
            ),
        )

    @staticmethod
    def _validate_model_context(
        plan: FederatedCoordinationPlanV04, context: ModelContext
    ) -> None:
        if (
            context.profile.model_id != plan.model_id
            or context.profile.model_version != plan.model_version
            or context.registry.model_id != plan.model_id
            or context.registry.approved_model_version != plan.model_version
        ):
            raise PartitionContractError(
                "model_context_missing",
                "model_ref does not match the approved model registry context",
            )

    @staticmethod
    def _validate_participant_context(
        plan: FederatedCoordinationPlanV04, context: ParticipantContext
    ) -> None:
        device_ids = {device.device_id for device in context.devices}
        if any(participant not in device_ids for participant in plan.participant_ids):
            raise PartitionContractError(
                "participant_context_missing",
                "resource context is missing for one or more candidate participants",
            )
        links = {
            (link.source_device, link.target_device) for link in context.network_links
        }
        if plan.selected_mode == "FL":
            aggregator = plan.participant_ids[0]
            required_links = {
                (participant, aggregator)
                for participant in plan.participant_ids[1:]
                if participant != aggregator
            }
        else:
            required_links = set(zip(plan.participant_ids, plan.participant_ids[1:]))
        if not required_links.issubset(links):
            raise PartitionContractError(
                "network_evidence_missing",
                "required participant bandwidth evidence is unavailable",
            )

    @staticmethod
    def _required_serving_number(
        plan: FederatedCoordinationPlanV04, field: str, *, minimum: float
    ) -> float:
        return _number(
            plan.serving_policy.get(field), f"serving_policy.{field}", minimum=minimum
        )

    def _minimum_throughput(self, plan: FederatedCoordinationPlanV04) -> float:
        explicit = plan.serving_policy.get("minimum_throughput_rps")
        if explicit is not None:
            return _number(
                explicit, "serving_policy.minimum_throughput_rps", minimum=0.000001
            )
        concurrency = _integer(
            plan.serving_policy.get("max_concurrent_requests"),
            "serving_policy.max_concurrent_requests",
            minimum=1,
        )
        timeout = self._required_serving_number(
            plan, "request_timeout_sec", minimum=0.000001
        )
        return concurrency / timeout

    def _constraints(self, plan: FederatedCoordinationPlanV04) -> PartitionConstraints:
        return PartitionConstraints(
            max_end_to_end_latency_ms=(
                self._required_serving_number(
                    plan, "target_latency_ms", minimum=0.000001
                )
                if plan.task_type == "distributed_inference"
                else None
            ),
            max_transfer_bytes=None,
            minimum_memory_headroom_ratio=0.1,
        )


def partition_planning_request_to_dict(
    request: PartitionPlanningRequest,
) -> dict[str, Any]:
    plan = request.plan
    if isinstance(plan, TrainingCoordinationPlan):
        plan_payload: dict[str, Any] = {
            "model_id": plan.model_id,
            "approved_model_version": plan.approved_model_version,
            "coordination_mode": plan.coordination_mode,
            "participants": list(plan.participants),
            "round_policy": dict(plan.round_policy),
            "aggregation_policy": dict(plan.aggregation_policy),
            "synchronization_policy": dict(plan.synchronization_policy),
            "training_objective": plan.training_objective,
            "resource_budget": dict(plan.resource_budget),
            "constraints": plan.constraints.to_dict(),
        }
    else:
        plan_payload = {
            "model_id": plan.model_id,
            "approved_model_version": plan.approved_model_version,
            "service_objective": plan.service_objective,
            "latency_slo_ms": plan.latency_slo_ms,
            "minimum_throughput_rps": plan.minimum_throughput_rps,
            "availability_target": plan.availability_target,
            "traffic_policy": dict(plan.traffic_policy),
            "concurrency_policy": dict(plan.concurrency_policy),
            "participants": list(plan.participants),
            "resource_budget": dict(plan.resource_budget),
            "constraints": plan.constraints.to_dict(),
        }
    mode = request.approved_execution_mode
    if mode is None:
        raise PartitionContractError(
            "approved_mode_required", "approved execution mode is required"
        )
    return {
        "coordination_plan": {
            "plan_type": request.envelope.plan_type,
            "plan_id": request.envelope.plan_id,
            "job_id": request.envelope.job_id,
            "approved": True,
            "approved_by": request.envelope.approved_by,
            "approval_ref": request.envelope.approval_ref,
            "approved_at": request.envelope.approved_at,
            "schema_version": request.envelope.schema_version,
            "payload": plan_payload,
        },
        "system_context": request.context.to_dict(),
        "approved_execution_mode": mode.to_dict(),
    }

