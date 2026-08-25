from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from orchestrator_agent.partition_common import PartitionCommonProcessor
from orchestrator_agent.partition_coordination import (
    LegacyFederatedRoundPlanAdapter,
    PartitionPlanningRequest,
)
from orchestrator_agent.partition_models import PartitionContractError
from orchestrator_agent.partition_strategies import PartitionStrategyRegistry


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def normalized_inference_request():
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return PartitionCommonProcessor().process(PartitionPlanningRequest.from_dict(payload))


def test_registry_routes_inference_request(normalized_inference_request):
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized_inference_request.plan_type,
        normalized_inference_request.approved_execution_mode.name,
    )

    assert strategy.strategy_id == "inference-partition-v1"


def test_registry_keeps_inference_compatible_with_old_policy_without_training_strategy(
    tmp_path: Path,
    normalized_inference_request,
):
    policy = json.loads(
        (ROOT / "config/model_partition_policy.json").read_text(encoding="utf-8")
    )
    policy["strategy_policies"].pop("training-partition-v1")
    path = tmp_path / "inference-only-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    strategy = PartitionStrategyRegistry.default(path).resolve(
        normalized_inference_request.plan_type,
        normalized_inference_request.approved_execution_mode.name,
    )

    assert strategy.strategy_id == "inference-partition-v1"


def test_registry_fails_closed_for_unknown_mode(normalized_inference_request):
    with pytest.raises(PartitionContractError) as error:
        PartitionStrategyRegistry.default().resolve("inference", "unknown-mode")

    assert error.value.code == "strategy_not_supported"


def test_inference_intent_binds_the_approved_mode_policy_and_normalized_input(
    normalized_inference_request,
):
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized_inference_request.plan_type,
        normalized_inference_request.approved_execution_mode.name,
    )

    intent = strategy.build_partition_intent(normalized_inference_request)

    assert intent.strategy_id == "inference-partition-v1"
    assert intent.strategy_version == "inference-partition-v1:partition-policy-v1"
    assert intent.allowed_partition_methods == ("split_inference",)
    assert intent.allowed_split_boundaries == (1, 2)
    assert intent.forbidden_split_boundaries == (0, 3)
    assert intent.graph_requirements == (
        "forward_only_dag",
        "adjacent_partition_edges_only",
    )
    assert intent.memory_rules == (
        "per_partition_parameter_bytes",
        "per_partition_working_memory_bytes",
        "per_partition_peak_activation_bytes",
    )
    assert intent.communication_rules == (
        "forward_activation_transfer_only",
        "adjacent_partition_transfer_only",
    )
    assert intent.optimization_objectives == (
        "predicted_latency:0.5",
        "predicted_memory_pressure:0.3",
        "predicted_communication:0.2",
    )
    assert f"input_signature:{normalized_inference_request.input_signature}" in intent.assumptions
    assert "policy_version:partition-policy-v1" in intent.assumptions
    assert intent.warnings == ()


def test_inference_intent_rejects_a_mode_not_approved_for_its_strategy(
    normalized_inference_request,
):
    strategy = PartitionStrategyRegistry.default().resolve("inference", "split_inference")

    with pytest.raises(PartitionContractError) as error:
        strategy.build_partition_intent(
            replace(
                normalized_inference_request,
                approved_execution_mode=replace(
                    normalized_inference_request.approved_execution_mode,
                    name="unknown-mode",
                ),
            )
        )

    assert error.value.code == "strategy_not_supported"


@pytest.mark.parametrize("mode", ["pipeline_parallel", "split_learning"])
def test_registry_supports_each_explicitly_approved_inference_mode(mode):
    strategy = PartitionStrategyRegistry.default().resolve("inference", mode)

    assert strategy.strategy_id == "inference-partition-v1"


@pytest.mark.parametrize(
    "mode", ["pipeline_parallel", "split_learning", "hybrid_partition"]
)
def test_registry_routes_each_explicitly_approved_training_mode(mode):
    strategy = PartitionStrategyRegistry.default().resolve("training", mode)

    assert strategy.strategy_id == "training-partition-v1"
    assert strategy.supported_modes == (
        "pipeline_parallel",
        "split_learning",
        "hybrid_partition",
    )


def test_inference_intent_warns_when_the_normalized_request_has_no_forecast():
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["system_context"].pop("workload_forecast")
    request = PartitionCommonProcessor().process(PartitionPlanningRequest.from_dict(payload))
    strategy = PartitionStrategyRegistry.default().resolve(
        request.plan_type,
        request.approved_execution_mode.name,
    )

    intent = strategy.build_partition_intent(request)

    assert "workload_forecast_missing: confidence reduced" in intent.warnings
    assert "planning_confidence:0.8" in intent.assumptions


def test_registry_routes_the_actual_legacy_adapter_mode():
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    request = PartitionCommonProcessor().process(
        LegacyFederatedRoundPlanAdapter().adapt(payload)
    )

    strategy = PartitionStrategyRegistry.default().resolve(
        request.plan_type,
        request.approved_execution_mode.name,
    )

    assert request.approved_execution_mode.name == "split_learning"
    assert strategy.strategy_id == "inference-partition-v1"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize(
    "section,key",
    [
        ("confidence", "base"),
        ("confidence", "missing_forecast_penalty"),
        ("confidence", "legacy_input_penalty"),
        ("objectives", "latency"),
        ("objectives", "memory_pressure"),
        ("objectives", "communication"),
    ],
)
def test_registry_rejects_non_finite_policy_fractions(tmp_path, section, key, value):
    policy = json.loads(
        (ROOT / "config/model_partition_policy.json").read_text(encoding="utf-8")
    )
    target = (
        policy["confidence"]
        if section == "confidence"
        else policy["strategy_policies"]["inference-partition-v1"]["objectives"]
    )
    target[key] = value
    path = tmp_path / "model_partition_policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(PartitionContractError) as error:
        PartitionStrategyRegistry.default(path)

    assert error.value.code == "invalid_partition_policy"

