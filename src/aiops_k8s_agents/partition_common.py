from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from aiops_k8s_agents.partition_context import WorkloadForecast, canonical_json
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import (
    ApprovedExecutionMode,
    ModelLayer,
    NetworkLink,
    PartitionConstraints,
    PartitionContractError,
    ResourceDevice,
)


@dataclass(frozen=True)
class NormalizedPartitionRequest:
    plan_type: str
    job_id: str
    model_id: str
    approved_model_version: str
    approved_execution_mode: ApprovedExecutionMode
    participants: tuple[str, ...]
    layers: tuple[ModelLayer, ...]
    devices: tuple[ResourceDevice, ...]
    network_links: tuple[NetworkLink, ...]
    constraints: PartitionConstraints
    context_snapshot_id: str
    context_snapshot_hash: str
    input_signature: str
    legacy_input: bool
    workload_forecast_available: bool = False
    workload_forecast: WorkloadForecast | None = None


class PartitionCommonProcessor:
    """Validates common planning inputs before strategy-specific processing."""

    def process(self, request: PartitionPlanningRequest) -> NormalizedPartitionRequest:
        if request.envelope.plan_type not in {"training", "inference"}:
            raise PartitionContractError(
                "unsupported_plan_type",
                f"unsupported plan type: {request.envelope.plan_type}",
            )
        if not request.envelope.approved_by or not request.envelope.approval_ref:
            raise PartitionContractError(
                "approval_provenance_required",
                "approved_by and approval_ref are required",
            )
        context = request.context
        profile = context.model_structure_profile
        if profile is None:
            raise PartitionContractError(
                "model_profile_missing", "model structure profile is required"
            )
        plan = request.plan
        approved_mode = self._approved_mode(request)
        versions = (
            plan.approved_model_version,
            context.model_registry_context.approved_model_version,
            profile.model_version,
        )
        if any(
            not isinstance(version, str) or not version.strip()
            for version in versions
        ):
            raise PartitionContractError(
                "model_version_mismatch",
                "approved model version must be non-empty text",
            )
        if (
            plan.model_id != context.model_registry_context.model_id
            or plan.approved_model_version
            != context.model_registry_context.approved_model_version
            or profile.model_id != plan.model_id
            or profile.model_version != plan.approved_model_version
        ):
            raise PartitionContractError(
                "model_version_mismatch",
                "planning request and model context must match",
            )

        layers = request.legacy_layers or self._layers_from_profile(request)
        self._validate_feasibility(request, layers)
        context_hash = context.deterministic_hash()
        signature_payload = {
            "envelope": asdict(request.envelope),
            "plan": asdict(plan),
            "approved_execution_mode": approved_mode.to_dict(),
            "layers": [layer.to_dict() for layer in layers],
            "devices": [device.to_dict() for device in context.devices],
            "network_links": [link.to_dict() for link in context.network_links],
            "context_snapshot_id": context.snapshot_id,
            "context_snapshot_hash": context_hash,
            "legacy_input": request.legacy_input,
            "workload_forecast_available": context.workload_forecast is not None,
        }
        return NormalizedPartitionRequest(
            plan_type=request.envelope.plan_type,
            job_id=request.envelope.job_id,
            model_id=plan.model_id,
            approved_model_version=plan.approved_model_version,
            approved_execution_mode=approved_mode,
            participants=plan.participants,
            layers=layers,
            devices=context.devices,
            network_links=context.network_links,
            constraints=plan.constraints,
            context_snapshot_id=context.snapshot_id,
            context_snapshot_hash=context_hash,
            input_signature=hashlib.sha256(
                canonical_json(signature_payload).encode("utf-8")
            ).hexdigest(),
            legacy_input=request.legacy_input,
            workload_forecast_available=context.workload_forecast is not None,
            workload_forecast=context.workload_forecast,
        )

    @staticmethod
    def _approved_mode(request: PartitionPlanningRequest) -> ApprovedExecutionMode:
        mode = request.approved_execution_mode
        if (
            mode is None
            or not isinstance(mode.name, str)
            or not mode.name.strip()
            or not mode.approved
            or not mode.approved_by
            or not mode.approval_ref
        ):
            raise PartitionContractError(
                "approved_mode_required", "execution mode must be approved upstream"
            )
        return mode

    @staticmethod
    def _layers_from_profile(request: PartitionPlanningRequest) -> tuple[ModelLayer, ...]:
        layers: list[ModelLayer] = []
        for block in request.context.model_structure_profile.blocks:
            layer_count = len(block.layer_names)
            for layer_name in block.layer_names:
                layers.append(
                    ModelLayer(
                        name=layer_name,
                        compute_units=1.0,
                        parameter_bytes=block.parameter_bytes // layer_count,
                        activation_bytes=block.activation_bytes,
                        working_memory_bytes=block.working_memory_bytes // layer_count,
                    )
                )
        return tuple(layers)

    @staticmethod
    def _validate_feasibility(
        request: PartitionPlanningRequest, layers: tuple[ModelLayer, ...]
    ) -> None:
        participants = request.plan.participants
        device_ids = {device.device_id for device in request.context.devices}
        is_federated_learning = (
            request.approved_execution_mode is not None
            and request.approved_execution_mode.name == "federated_learning"
        )
        if len(participants) < 2 or not layers or (
            not is_federated_learning and len(layers) < len(participants)
        ):
            raise PartitionContractError(
                "early_feasibility_failed",
                (
                    "federated learning requires a full model and at least two participants"
                    if is_federated_learning
                    else "each participant requires a non-empty model partition"
                ),
            )
        if any(participant not in device_ids for participant in participants):
            raise PartitionContractError(
                "early_feasibility_failed",
                "each participant requires a device snapshot",
            )
        links = {
            (link.source_device, link.target_device)
            for link in request.context.network_links
        }
        required_pairs = (
            tuple((participant, participants[0]) for participant in participants[1:])
            if is_federated_learning
            else tuple(zip(participants, participants[1:]))
        )
        if any(pair not in links for pair in required_pairs):
            raise PartitionContractError(
                "early_feasibility_failed",
                "required participant network evidence is unavailable",
            )
