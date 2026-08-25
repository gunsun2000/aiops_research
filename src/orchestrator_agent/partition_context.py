from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from orchestrator_agent.partition_models import (
    NetworkLink,
    PartitionContractError,
    ResourceDevice,
)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PartitionContractError("invalid_system_snapshot", f"{field} must be an object")
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PartitionContractError("invalid_system_snapshot", f"{field} must be an array")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PartitionContractError("invalid_system_snapshot", f"{field} is required")
    return text


def _int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PartitionContractError(
            "invalid_system_snapshot", f"{field} must be an integer of at least {minimum}"
        )
    return value


def _float(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise PartitionContractError("invalid_system_snapshot", f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_system_snapshot", f"{field} must be numeric"
        ) from exc
    if not isfinite(number) or number < minimum:
        raise PartitionContractError(
            "invalid_system_snapshot", f"{field} must be at least {minimum}"
        )
    return number


def _require_unique(values: Sequence[str], field: str) -> None:
    if len(set(values)) != len(values):
        raise PartitionContractError("invalid_system_snapshot", f"{field} must be unique")


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class ModelBlock:
    block_id: str
    layer_names: tuple[str, ...]
    parameter_bytes: int
    activation_bytes: int
    working_memory_bytes: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModelBlock:
        payload = _mapping(payload, "model_structure_profile.blocks[]")
        layer_names = tuple(
            _text(item, "model_structure_profile.blocks[].layer_names[]")
            for item in _sequence(
                payload.get("layer_names"),
                "model_structure_profile.blocks[].layer_names",
            )
        )
        if not layer_names:
            raise PartitionContractError(
                "invalid_system_snapshot",
                "model_structure_profile.blocks[].layer_names is required",
            )
        _require_unique(layer_names, "model_structure_profile.blocks[].layer_names")
        return cls(
            block_id=_text(payload.get("block_id"), "model_structure_profile.blocks[].block_id"),
            layer_names=layer_names,
            parameter_bytes=_int(
                payload.get("parameter_bytes"),
                "model_structure_profile.blocks[].parameter_bytes",
            ),
            activation_bytes=_int(
                payload.get("activation_bytes"),
                "model_structure_profile.blocks[].activation_bytes",
            ),
            working_memory_bytes=_int(
                payload.get("working_memory_bytes"),
                "model_structure_profile.blocks[].working_memory_bytes",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "layer_names": list(self.layer_names),
            "parameter_bytes": self.parameter_bytes,
            "activation_bytes": self.activation_bytes,
            "working_memory_bytes": self.working_memory_bytes,
        }


@dataclass(frozen=True)
class ModelStructureProfile:
    profile_id: str
    model_id: str
    model_version: str
    blocks: tuple[ModelBlock, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModelStructureProfile:
        payload = _mapping(payload, "model_structure_profile")
        blocks = tuple(
            ModelBlock.from_dict(item)
            for item in _sequence(payload.get("blocks"), "model_structure_profile.blocks")
        )
        if not blocks:
            raise PartitionContractError(
                "invalid_system_snapshot", "model_structure_profile.blocks is required"
            )
        _require_unique(
            [block.block_id for block in blocks], "model_structure_profile.blocks.block_id"
        )
        layer_names = [layer for block in blocks for layer in block.layer_names]
        _require_unique(layer_names, "model_structure_profile.blocks.layer_names")
        return cls(
            profile_id=_text(payload.get("profile_id"), "model_structure_profile.profile_id"),
            model_id=_text(payload.get("model_id"), "model_structure_profile.model_id"),
            model_version=_text(
                payload.get("model_version"), "model_structure_profile.model_version"
            ),
            blocks=blocks,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "blocks": [block.to_dict() for block in self.blocks],
        }


@dataclass(frozen=True)
class ModelRegistryContext:
    registry_id: str
    registry_version: str
    model_id: str
    approved_model_version: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModelRegistryContext:
        payload = _mapping(payload, "model_registry_context")
        return cls(
            registry_id=_text(payload.get("registry_id"), "model_registry_context.registry_id"),
            registry_version=_text(
                payload.get("registry_version"), "model_registry_context.registry_version"
            ),
            model_id=_text(payload.get("model_id"), "model_registry_context.model_id"),
            approved_model_version=_text(
                payload.get("approved_model_version"),
                "model_registry_context.approved_model_version",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "model_id": self.model_id,
            "approved_model_version": self.approved_model_version,
        }


@dataclass(frozen=True)
class WorkloadForecast:
    forecast_id: str
    horizon_seconds: int
    expected_request_rate: float
    expected_batch_size: int
    expected_sequence_length: int
    uncertainty: float
    source: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkloadForecast:
        payload = _mapping(payload, "workload_forecast")
        uncertainty = _float(payload.get("uncertainty"), "workload_forecast.uncertainty")
        if uncertainty > 1.0:
            raise PartitionContractError(
                "invalid_system_snapshot", "workload_forecast.uncertainty must be at most 1.0"
            )
        return cls(
            forecast_id=_text(payload.get("forecast_id"), "workload_forecast.forecast_id"),
            horizon_seconds=_int(
                payload.get("horizon_seconds"), "workload_forecast.horizon_seconds", minimum=1
            ),
            expected_request_rate=_float(
                payload.get("expected_request_rate"), "workload_forecast.expected_request_rate"
            ),
            expected_batch_size=_int(
                payload.get("expected_batch_size"),
                "workload_forecast.expected_batch_size",
                minimum=1,
            ),
            expected_sequence_length=_int(
                payload.get("expected_sequence_length"),
                "workload_forecast.expected_sequence_length",
                minimum=1,
            ),
            uncertainty=uncertainty,
            source=_text(payload.get("source"), "workload_forecast.source"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "horizon_seconds": self.horizon_seconds,
            "expected_request_rate": self.expected_request_rate,
            "expected_batch_size": self.expected_batch_size,
            "expected_sequence_length": self.expected_sequence_length,
            "uncertainty": self.uncertainty,
            "source": self.source,
        }


@dataclass(frozen=True)
class PartitionSystemContext:
    snapshot_id: str
    snapshot_version: str
    collected_at: str
    model_structure_profile: ModelStructureProfile
    model_registry_context: ModelRegistryContext
    devices: tuple[ResourceDevice, ...]
    network_links: tuple[NetworkLink, ...]
    workload_forecast: WorkloadForecast | None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionSystemContext:
        payload = _mapping(payload, "system_context")
        devices = tuple(
            ResourceDevice.from_dict(_mapping(item, "system_context.devices[]"))
            for item in _sequence(payload.get("devices"), "system_context.devices")
        )
        if not devices:
            raise PartitionContractError(
                "invalid_system_snapshot", "system_context.devices is required"
            )
        _require_unique([device.device_id for device in devices], "system_context.devices")
        network_links = tuple(
            NetworkLink.from_dict(_mapping(item, "system_context.network_links[]"))
            for item in _sequence(
                payload.get("network_links"), "system_context.network_links"
            )
        )
        _require_unique(
            [f"{link.source_device}->{link.target_device}" for link in network_links],
            "system_context.network_links",
        )
        device_ids = {device.device_id for device in devices}
        for link in network_links:
            if link.source_device not in device_ids or link.target_device not in device_ids:
                raise PartitionContractError(
                    "invalid_system_snapshot",
                    f"network link {link.source_device}->{link.target_device} references an unknown device",
                )
        profile = ModelStructureProfile.from_dict(
            _mapping(payload.get("model_structure_profile"), "model_structure_profile")
        )
        registry = ModelRegistryContext.from_dict(
            _mapping(payload.get("model_registry_context"), "model_registry_context")
        )
        if (
            profile.model_id != registry.model_id
            or profile.model_version != registry.approved_model_version
        ):
            raise PartitionContractError(
                "model_version_mismatch",
                "model structure profile and model registry context must match",
            )
        forecast_payload = payload.get("workload_forecast")
        return cls(
            snapshot_id=_text(payload.get("snapshot_id"), "system_context.snapshot_id"),
            snapshot_version=_text(
                payload.get("snapshot_version"), "system_context.snapshot_version"
            ),
            collected_at=_text(payload.get("collected_at"), "system_context.collected_at"),
            model_structure_profile=profile,
            model_registry_context=registry,
            devices=devices,
            network_links=network_links,
            workload_forecast=(
                None
                if forecast_payload is None
                else WorkloadForecast.from_dict(
                    _mapping(forecast_payload, "workload_forecast")
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "collected_at": self.collected_at,
            "model_structure_profile": self.model_structure_profile.to_dict(),
            "model_registry_context": self.model_registry_context.to_dict(),
            "devices": [device.to_dict() for device in self.devices],
            "network_links": [link.to_dict() for link in self.network_links],
            "workload_forecast": (
                None
                if self.workload_forecast is None
                else self.workload_forecast.to_dict()
            ),
        }

    def deterministic_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

