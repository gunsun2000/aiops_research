from __future__ import annotations

import hashlib
from math import isfinite
from typing import TYPE_CHECKING, Any

from orchestrator_agent.partition_context import canonical_json
from orchestrator_agent.partition_models import PartitionCandidate, PartitionContractError

if TYPE_CHECKING:
    from orchestrator_agent.partition_ranking import RankingContext


FEATURE_SCHEMA_VERSION = "partition-feature-v1"
FEATURE_ORDER = (
    "plan_type_training",
    "plan_type_inference",
    "layer_count",
    "participant_count",
    "total_compute_units",
    "total_parameter_bytes",
    "total_activation_bytes",
    "total_working_memory_bytes",
    "device_compute_min",
    "device_compute_mean",
    "device_compute_max",
    "device_memory_min",
    "device_memory_mean",
    "device_memory_max",
    "network_bandwidth_min",
    "network_bandwidth_mean",
    "network_bandwidth_max",
    "network_latency_min",
    "network_latency_mean",
    "network_latency_max",
    "max_latency_ms",
    "max_transfer_bytes",
    "minimum_memory_headroom_ratio",
    "forecast_request_rate",
    "forecast_batch_size",
    "forecast_sequence_length",
    "forecast_uncertainty",
    "forecast_request_rate_missing",
    "forecast_batch_size_missing",
    "forecast_sequence_length_missing",
    "candidate_partition_count",
    "candidate_compute_share_min",
    "candidate_compute_share_mean",
    "candidate_compute_share_max",
    "estimated_compute_ms",
    "estimated_transfer_ms",
    "estimated_total_latency_ms",
    "estimated_step_time_ms",
    "total_transfer_bytes",
    "gradient_transfer_bytes",
    "maximum_memory_pressure",
    "maximum_load_imbalance",
    "predicted_resilience_risk",
    "baseline_score",
    "split_position_min",
    "split_position_mean",
    "split_position_max",
)


def candidate_key(candidate: PartitionCandidate, strategy_version: str) -> str:
    """Return the plan-independent identity used by every ranker."""
    payload = {
        "split_points": list(candidate.split_points),
        "assignments": [
            {"partition_id": item.partition_id, "device_id": item.device_id}
            for item in candidate.partitions
        ],
        "strategy_version": _text(strategy_version, "strategy_version"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def extract_partition_features(
    context: RankingContext, candidate: PartitionCandidate
) -> dict[str, float]:
    """Build the fixed-order, sklearn-independent partition feature vector."""
    request = context.request
    plan_type = _text(request.plan_type, "plan_type")
    if plan_type not in {"training", "inference"}:
        raise PartitionContractError("invalid_partition_features", "plan_type is unsupported")

    layers = request.layers
    devices = request.devices
    links = request.network_links
    if not layers or not devices or not links:
        raise PartitionContractError(
            "invalid_partition_features", "layers, devices, and network links are required"
        )

    total_compute_units = sum(
        _number(layer.compute_units, "layers.compute_units", minimum=0.0)
        for layer in layers
    )
    if total_compute_units <= 0.0:
        raise PartitionContractError(
            "invalid_partition_features", "total_compute_units must be positive"
        )
    total_parameter_bytes = sum(
        _bytes(layer.parameter_bytes, "layers.parameter_bytes") for layer in layers
    )
    total_activation_bytes = sum(
        _bytes(layer.activation_bytes, "layers.activation_bytes") for layer in layers
    )
    total_working_memory_bytes = sum(
        _bytes(layer.working_memory_bytes, "layers.working_memory_bytes")
        for layer in layers
    )

    device_compute = tuple(
        _number(device.compute_units_per_second, "devices.compute_units_per_second", minimum=0.0)
        for device in devices
    )
    device_memory = tuple(
        _bytes(device.memory_available_bytes, "devices.memory_available_bytes")
        for device in devices
    )
    network_bandwidth = tuple(
        _number(
            link.bandwidth_bytes_per_second,
            "network_links.bandwidth_bytes_per_second",
            minimum=0.0,
        )
        for link in links
    )
    network_latency = tuple(
        _number(link.latency_ms, "network_links.latency_ms", minimum=0.0)
        for link in links
    )

    forecast = request.workload_forecast
    forecast_request_rate, request_rate_missing = _forecast_value(
        forecast, "expected_request_rate"
    )
    forecast_batch_size, batch_size_missing = _forecast_value(
        forecast, "expected_batch_size"
    )
    forecast_sequence_length, sequence_length_missing = _forecast_value(
        forecast, "expected_sequence_length"
    )
    forecast_uncertainty = (
        0.0
        if forecast is None
        else _number(forecast.uncertainty, "workload_forecast.uncertainty", minimum=0.0)
    )

    partition_compute = tuple(
        _number(partition.compute_units, "partitions.compute_units", minimum=0.0)
        for partition in candidate.partitions
    )
    partition_memory = tuple(
        _bytes(partition.memory_demand_bytes, "partitions.memory_demand_bytes")
        for partition in candidate.partitions
    )
    if not partition_compute:
        raise PartitionContractError(
            "invalid_partition_features", "candidate must contain partitions"
        )
    if not candidate.split_points:
        raise PartitionContractError(
            "invalid_partition_features", "candidate must contain split points"
        )

    split_positions = tuple(
        _number(split_point, "split_points", minimum=0.0)
        for split_point in candidate.split_points
    )
    vector = {
        "plan_type_training": 1.0 if plan_type == "training" else 0.0,
        "plan_type_inference": 1.0 if plan_type == "inference" else 0.0,
        "layer_count": _number(len(layers), "layer_count", minimum=0.0),
        "participant_count": _number(len(request.participants), "participant_count", minimum=0.0),
        "total_compute_units": total_compute_units,
        "total_parameter_bytes": total_parameter_bytes,
        "total_activation_bytes": total_activation_bytes,
        "total_working_memory_bytes": total_working_memory_bytes,
        "device_compute_min": min(device_compute),
        "device_compute_mean": _mean(device_compute),
        "device_compute_max": max(device_compute),
        "device_memory_min": min(device_memory),
        "device_memory_mean": _mean(device_memory),
        "device_memory_max": max(device_memory),
        "network_bandwidth_min": min(network_bandwidth),
        "network_bandwidth_mean": _mean(network_bandwidth),
        "network_bandwidth_max": max(network_bandwidth),
        "network_latency_min": min(network_latency),
        "network_latency_mean": _mean(network_latency),
        "network_latency_max": max(network_latency),
        "max_latency_ms": _optional_number(
            request.constraints.max_end_to_end_latency_ms,
            "constraints.max_end_to_end_latency_ms",
        ),
        "max_transfer_bytes": _optional_bytes(
            request.constraints.max_transfer_bytes, "constraints.max_transfer_bytes"
        ),
        "minimum_memory_headroom_ratio": _number(
            request.constraints.minimum_memory_headroom_ratio,
            "constraints.minimum_memory_headroom_ratio",
            minimum=0.0,
        ),
        "forecast_request_rate": forecast_request_rate,
        "forecast_batch_size": forecast_batch_size,
        "forecast_sequence_length": forecast_sequence_length,
        "forecast_uncertainty": forecast_uncertainty,
        "forecast_request_rate_missing": request_rate_missing,
        "forecast_batch_size_missing": batch_size_missing,
        "forecast_sequence_length_missing": sequence_length_missing,
        "candidate_partition_count": _number(
            len(candidate.partitions), "candidate_partition_count", minimum=0.0
        ),
        "candidate_compute_share_min": min(partition_compute) / total_compute_units,
        "candidate_compute_share_mean": _mean(partition_compute) / total_compute_units,
        "candidate_compute_share_max": max(partition_compute) / total_compute_units,
        "estimated_compute_ms": _number(
            candidate.estimated_compute_ms, "estimated_compute_ms", minimum=0.0
        ),
        "estimated_transfer_ms": _number(
            candidate.estimated_transfer_ms, "estimated_transfer_ms", minimum=0.0
        ),
        "estimated_total_latency_ms": _number(
            candidate.estimated_total_latency_ms,
            "estimated_total_latency_ms",
            minimum=0.0,
        ),
        "estimated_step_time_ms": _number(
            candidate.estimated_step_time_ms, "estimated_step_time_ms", minimum=0.0
        ),
        "total_transfer_bytes": _bytes(
            candidate.total_transfer_bytes, "total_transfer_bytes"
        ),
        "gradient_transfer_bytes": _bytes(
            candidate.gradient_transfer_bytes, "gradient_transfer_bytes"
        ),
        "maximum_memory_pressure": _number(
            candidate.maximum_memory_pressure, "maximum_memory_pressure", minimum=0.0
        ),
        "maximum_load_imbalance": _number(
            candidate.maximum_load_imbalance, "maximum_load_imbalance", minimum=0.0
        ),
        "predicted_resilience_risk": _number(
            candidate.predicted_resilience_risk,
            "predicted_resilience_risk",
            minimum=0.0,
        ),
        "baseline_score": _number(candidate.score, "baseline_score", minimum=0.0),
        "split_position_min": min(split_positions),
        "split_position_mean": _mean(split_positions),
        "split_position_max": max(split_positions),
    }
    if tuple(vector) != FEATURE_ORDER:
        raise PartitionContractError(
            "invalid_partition_features", "feature order does not match partition-feature-v1"
        )
    return {name: _number(value, name, minimum=0.0) for name, value in vector.items()}


def _forecast_value(forecast: Any, attribute: str) -> tuple[float, float]:
    if forecast is None:
        return 0.0, 1.0
    return _number(
        getattr(forecast, attribute), f"workload_forecast.{attribute}", minimum=0.0
    ), 0.0


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _optional_number(value: Any, field: str) -> float:
    return 0.0 if value is None else _number(value, field, minimum=0.0)


def _optional_bytes(value: Any, field: str) -> float:
    return 0.0 if value is None else _bytes(value, field)


def _bytes(value: Any, field: str) -> float:
    return _number(value, field, minimum=0.0)


def _number(value: Any, field: str, *, minimum: float) -> float:
    if isinstance(value, bool):
        raise PartitionContractError("invalid_partition_features", f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_partition_features", f"{field} must be numeric"
        ) from exc
    if not isfinite(number):
        raise PartitionContractError(
            "invalid_partition_features", f"{field} must be finite"
        )
    if number < minimum:
        raise PartitionContractError(
            "invalid_partition_features", f"{field} byte sizes must not be negative"
        )
    return number


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PartitionContractError("invalid_partition_features", f"{field} is required")
    return value.strip()

