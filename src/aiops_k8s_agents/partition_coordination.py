from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from aiops_k8s_agents.partition_context import (
    ModelBlock,
    ModelRegistryContext,
    ModelStructureProfile,
    PartitionSystemContext,
)
from aiops_k8s_agents.partition_models import (
    ApprovedExecutionMode,
    FederatedRoundPlan,
    ModelLayer,
    PartitionConstraints,
    PartitionContractError,
)


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


def _participants(payload: Mapping[str, Any]) -> tuple[str, ...]:
    participants = tuple(
        _text(item, "coordination_plan.payload.participants[]")
        for item in _sequence(
            payload.get("participants"), "coordination_plan.payload.participants"
        )
    )
    if not participants:
        raise PartitionContractError(
            "invalid_contract", "coordination_plan.payload.participants is required"
        )
    return participants


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
    def from_dict(cls, payload: Mapping[str, Any]) -> CoordinationPlanEnvelope:
        payload = _mapping(payload, "coordination_plan")
        if payload.get("approved") is not True:
            raise PartitionContractError(
                "approved_plan_required", "coordination plan must be approved"
            )
        plan_type = _text(payload.get("plan_type"), "coordination_plan.plan_type")
        if plan_type not in {"training", "inference"}:
            raise PartitionContractError(
                "unsupported_plan_type", f"unsupported plan type: {plan_type}"
            )
        approved_by = str(payload.get("approved_by") or "").strip()
        approval_ref = str(payload.get("approval_ref") or "").strip()
        if not approved_by or not approval_ref:
            raise PartitionContractError(
                "approval_provenance_required",
                "approved_by and approval_ref are required",
            )
        return cls(
            plan_type=plan_type,
            plan_id=_text(payload.get("plan_id"), "coordination_plan.plan_id"),
            job_id=_text(payload.get("job_id"), "coordination_plan.job_id"),
            approved_by=approved_by,
            approval_ref=approval_ref,
            approved_at=_text(payload.get("approved_at"), "coordination_plan.approved_at"),
            schema_version=_text(
                payload.get("schema_version"), "coordination_plan.schema_version"
            ),
        )


@dataclass(frozen=True)
class TrainingCoordinationPlan:
    model_id: str
    approved_model_version: str
    coordination_mode: str
    participants: tuple[str, ...]
    round_policy: Mapping[str, Any]
    aggregation_policy: Mapping[str, Any]
    synchronization_policy: Mapping[str, Any]
    training_objective: str
    resource_budget: Mapping[str, Any]
    constraints: PartitionConstraints

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TrainingCoordinationPlan:
        payload = _mapping(payload, "coordination_plan.payload")
        return cls(
            model_id=_text(payload.get("model_id"), "coordination_plan.payload.model_id"),
            approved_model_version=_text(
                payload.get("approved_model_version"),
                "coordination_plan.payload.approved_model_version",
            ),
            coordination_mode=_text(
                payload.get("coordination_mode"),
                "coordination_plan.payload.coordination_mode",
            ),
            participants=_participants(payload),
            round_policy=dict(
                _mapping(payload.get("round_policy"), "coordination_plan.payload.round_policy")
            ),
            aggregation_policy=dict(
                _mapping(
                    payload.get("aggregation_policy"),
                    "coordination_plan.payload.aggregation_policy",
                )
            ),
            synchronization_policy=dict(
                _mapping(
                    payload.get("synchronization_policy"),
                    "coordination_plan.payload.synchronization_policy",
                )
            ),
            training_objective=_text(
                payload.get("training_objective"),
                "coordination_plan.payload.training_objective",
            ),
            resource_budget=dict(
                _mapping(
                    payload.get("resource_budget"),
                    "coordination_plan.payload.resource_budget",
                )
            ),
            constraints=PartitionConstraints.from_dict(
                _mapping(payload.get("constraints"), "coordination_plan.payload.constraints")
            ),
        )


@dataclass(frozen=True)
class InferenceCoordinationPlan:
    model_id: str
    approved_model_version: str
    service_objective: str
    latency_slo_ms: float
    minimum_throughput_rps: float
    availability_target: float
    traffic_policy: Mapping[str, Any]
    concurrency_policy: Mapping[str, Any]
    participants: tuple[str, ...]
    resource_budget: Mapping[str, Any]
    constraints: PartitionConstraints

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> InferenceCoordinationPlan:
        payload = _mapping(payload, "coordination_plan.payload")
        availability_target = _float(
            payload.get("availability_target"),
            "coordination_plan.payload.availability_target",
            minimum=0.0,
        )
        if availability_target > 1.0:
            raise PartitionContractError(
                "invalid_contract",
                "coordination_plan.payload.availability_target must be at most 1.0",
            )
        return cls(
            model_id=_text(payload.get("model_id"), "coordination_plan.payload.model_id"),
            approved_model_version=_text(
                payload.get("approved_model_version"),
                "coordination_plan.payload.approved_model_version",
            ),
            service_objective=_text(
                payload.get("service_objective"),
                "coordination_plan.payload.service_objective",
            ),
            latency_slo_ms=_float(
                payload.get("latency_slo_ms"),
                "coordination_plan.payload.latency_slo_ms",
                minimum=0.000001,
            ),
            minimum_throughput_rps=_float(
                payload.get("minimum_throughput_rps"),
                "coordination_plan.payload.minimum_throughput_rps",
                minimum=0.000001,
            ),
            availability_target=availability_target,
            traffic_policy=dict(
                _mapping(
                    payload.get("traffic_policy"),
                    "coordination_plan.payload.traffic_policy",
                )
            ),
            concurrency_policy=dict(
                _mapping(
                    payload.get("concurrency_policy"),
                    "coordination_plan.payload.concurrency_policy",
                )
            ),
            participants=_participants(payload),
            resource_budget=dict(
                _mapping(
                    payload.get("resource_budget"),
                    "coordination_plan.payload.resource_budget",
                )
            ),
            constraints=PartitionConstraints.from_dict(
                _mapping(payload.get("constraints"), "coordination_plan.payload.constraints")
            ),
        )


@dataclass(frozen=True)
class PartitionPlanningRequest:
    envelope: CoordinationPlanEnvelope
    plan: TrainingCoordinationPlan | InferenceCoordinationPlan
    context: PartitionSystemContext
    legacy_input: bool = False
    approved_execution_mode: ApprovedExecutionMode | None = None
    legacy_layers: tuple[ModelLayer, ...] | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionPlanningRequest:
        payload = _mapping(payload, "partition_planning_request")
        coordination_plan = _mapping(payload.get("coordination_plan"), "coordination_plan")
        envelope = CoordinationPlanEnvelope.from_dict(coordination_plan)
        plan_payload = _mapping(
            coordination_plan.get("payload"), "coordination_plan.payload"
        )
        plan = (
            TrainingCoordinationPlan.from_dict(plan_payload)
            if envelope.plan_type == "training"
            else InferenceCoordinationPlan.from_dict(plan_payload)
        )
        context = PartitionSystemContext.from_dict(
            _mapping(payload.get("system_context"), "system_context")
        )
        if (
            plan.model_id != context.model_registry_context.model_id
            or plan.approved_model_version
            != context.model_registry_context.approved_model_version
        ):
            raise PartitionContractError(
                "model_version_mismatch",
                "coordination plan and model registry context must match",
            )
        return cls(envelope=envelope, plan=plan, context=context)


class LegacyFederatedRoundPlanAdapter:
    """Maps validated V1 round plans into the immutable V2 request boundary."""

    LEGACY_SCHEMA_VERSION = "legacy-1.0"

    def adapt(self, payload: Mapping[str, Any] | FederatedRoundPlan) -> PartitionPlanningRequest:
        round_plan = (
            payload
            if isinstance(payload, FederatedRoundPlan)
            else FederatedRoundPlan.from_dict(_mapping(payload, "round_plan"))
        )
        model_version = self._model_version(round_plan.model_id)
        profile = ModelStructureProfile(
            profile_id=f"legacy-profile-{model_version}",
            model_id=round_plan.model_id,
            model_version=model_version,
            blocks=tuple(
                ModelBlock(
                    block_id=layer.name,
                    layer_names=(layer.name,),
                    parameter_bytes=layer.parameter_bytes,
                    activation_bytes=layer.activation_bytes,
                    working_memory_bytes=layer.working_memory_bytes,
                )
                for layer in round_plan.layers
            ),
        )
        context = PartitionSystemContext(
            snapshot_id=f"legacy-snapshot-{round_plan.job_id}",
            snapshot_version=self.LEGACY_SCHEMA_VERSION,
            collected_at="legacy-input",
            model_structure_profile=profile,
            model_registry_context=ModelRegistryContext(
                registry_id=f"legacy-registry-{round_plan.model_id}",
                registry_version=self.LEGACY_SCHEMA_VERSION,
                model_id=round_plan.model_id,
                approved_model_version=model_version,
            ),
            devices=round_plan.devices,
            network_links=round_plan.network_links,
            workload_forecast=None,
        )
        return PartitionPlanningRequest(
            envelope=CoordinationPlanEnvelope(
                plan_type="inference",
                plan_id=f"legacy-plan-{round_plan.job_id}",
                job_id=round_plan.job_id,
                approved_by=round_plan.execution_mode.approved_by,
                approval_ref=round_plan.execution_mode.approval_ref,
                approved_at="legacy-input",
                schema_version=self.LEGACY_SCHEMA_VERSION,
            ),
            plan=InferenceCoordinationPlan(
                model_id=round_plan.model_id,
                approved_model_version=model_version,
                service_objective="legacy federated round partitioning",
                latency_slo_ms=round_plan.constraints.max_end_to_end_latency_ms or 1.0,
                minimum_throughput_rps=1.0,
                availability_target=0.0,
                traffic_policy={},
                concurrency_policy={},
                participants=round_plan.participants,
                resource_budget={},
                constraints=round_plan.constraints,
            ),
            context=context,
            legacy_input=True,
            approved_execution_mode=round_plan.execution_mode,
            legacy_layers=round_plan.layers,
        )

    @staticmethod
    def _model_version(model_id: str) -> str:
        digest = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:16]
        return f"legacy-{digest}"
