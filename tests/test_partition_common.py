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


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy_payload() -> dict:
    return json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def inference_request() -> PartitionPlanningRequest:
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return PartitionPlanningRequest.from_dict(payload)


@pytest.fixture
def training_request() -> PartitionPlanningRequest:
    payload = json.loads(
        (ROOT / "config/examples/model_partition_training_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return PartitionPlanningRequest.from_dict(payload)


def test_legacy_adapter_preserves_existing_job_and_candidate_inputs(legacy_payload):
    request = LegacyFederatedRoundPlanAdapter().adapt(legacy_payload)
    normalized = PartitionCommonProcessor().process(request)

    assert normalized.job_id == legacy_payload["job_id"]
    assert normalized.model_id == legacy_payload["model_id"]
    assert normalized.plan_type == "inference"
    assert normalized.legacy_input is True
    assert normalized.approved_execution_mode.to_dict() == legacy_payload["execution_mode"]
    assert [layer.to_dict() for layer in normalized.layers] == legacy_payload["layers"]
    assert list(normalized.participants) == legacy_payload["participants"]
    assert [device.to_dict() for device in normalized.devices] == legacy_payload["devices"]
    assert [link.to_dict() for link in normalized.network_links] == legacy_payload[
        "network_links"
    ]
    assert normalized.constraints.to_dict() == legacy_payload["constraints"]


def test_common_processor_signature_binds_normalized_input_and_context(
    inference_request,
):
    processor = PartitionCommonProcessor()

    first = processor.process(inference_request)
    repeated = processor.process(inference_request)
    changed_context = replace(
        inference_request,
        context=replace(inference_request.context, snapshot_version="2026-08-20.2"),
    )

    assert first.input_signature == repeated.input_signature
    assert first.input_signature != processor.process(changed_context).input_signature


@pytest.mark.parametrize(
    ("field", "updated_request"),
    [
        (
            "service_objective",
            lambda request: replace(
                request,
                plan=replace(request.plan, service_objective="batch text generation"),
            ),
        ),
        (
            "latency_slo_ms",
            lambda request: replace(
                request, plan=replace(request.plan, latency_slo_ms=175.0)
            ),
        ),
        (
            "minimum_throughput_rps",
            lambda request: replace(
                request, plan=replace(request.plan, minimum_throughput_rps=30.0)
            ),
        ),
        (
            "availability_target",
            lambda request: replace(
                request, plan=replace(request.plan, availability_target=0.98)
            ),
        ),
        (
            "traffic_policy",
            lambda request: replace(
                request,
                plan=replace(request.plan, traffic_policy={"routing": "canary"}),
            ),
        ),
        (
            "concurrency_policy",
            lambda request: replace(
                request,
                plan=replace(request.plan, concurrency_policy={"max_requests": 32}),
            ),
        ),
        (
            "resource_budget",
            lambda request: replace(
                request, plan=replace(request.plan, resource_budget={"max_devices": 3})
            ),
        ),
        (
            "constraints",
            lambda request: replace(
                request,
                plan=replace(
                    request.plan,
                    constraints=replace(
                        request.plan.constraints, max_transfer_bytes=4_000_000
                    ),
                ),
            ),
        ),
    ],
)
def test_common_processor_signature_binds_inference_plan_fields(
    inference_request, field, updated_request
):
    processor = PartitionCommonProcessor()

    baseline = processor.process(inference_request)
    updated = processor.process(updated_request(inference_request))

    assert updated.input_signature != baseline.input_signature, field


@pytest.mark.parametrize(
    ("field", "updated_request"),
    [
        (
            "coordination_mode",
            lambda request: replace(
                request, plan=replace(request.plan, coordination_mode="split_learning")
            ),
        ),
        (
            "round_policy",
            lambda request: replace(
                request, plan=replace(request.plan, round_policy={"rounds": 12})
            ),
        ),
        (
            "aggregation_policy",
            lambda request: replace(
                request,
                plan=replace(request.plan, aggregation_policy={"name": "fedprox"}),
            ),
        ),
        (
            "synchronization_policy",
            lambda request: replace(
                request,
                plan=replace(
                    request.plan, synchronization_policy={"name": "asynchronous"}
                ),
            ),
        ),
        (
            "training_objective",
            lambda request: replace(
                request,
                plan=replace(request.plan, training_objective="minimize energy"),
            ),
        ),
        (
            "resource_budget",
            lambda request: replace(
                request, plan=replace(request.plan, resource_budget={"max_devices": 3})
            ),
        ),
        (
            "constraints",
            lambda request: replace(
                request,
                plan=replace(
                    request.plan,
                    constraints=replace(
                        request.plan.constraints, max_transfer_bytes=10_000_000
                    ),
                ),
            ),
        ),
    ],
)
def test_common_processor_signature_binds_training_plan_fields(
    training_request, field, updated_request
):
    processor = PartitionCommonProcessor()

    baseline = processor.process(training_request)
    updated = processor.process(updated_request(training_request))

    assert updated.input_signature != baseline.input_signature, field


def test_common_processor_canonicalizes_policy_mapping_key_order(inference_request):
    processor = PartitionCommonProcessor()
    first = replace(
        inference_request,
        plan=replace(
            inference_request.plan,
            traffic_policy={"routing": "weighted", "max_replicas": 4},
        ),
    )
    reordered = replace(
        inference_request,
        plan=replace(
            inference_request.plan,
            traffic_policy={"max_replicas": 4, "routing": "weighted"},
        ),
    )

    assert processor.process(first).input_signature == processor.process(
        reordered
    ).input_signature


@pytest.mark.parametrize(
    ("path", "mode_name"),
    [
        ("config/examples/model_partition_inference_v2.json", "split_inference"),
        ("config/examples/model_partition_training_v2.json", "pipeline_parallel"),
    ],
)
def test_v2_examples_require_and_process_explicit_approved_execution_mode(
    path, mode_name
):
    payload = json.loads((ROOT / path).read_text(encoding="utf-8"))

    request = PartitionPlanningRequest.from_dict(payload)
    normalized = PartitionCommonProcessor().process(request)

    assert request.approved_execution_mode is not None
    assert request.approved_execution_mode.name == mode_name
    assert normalized.approved_execution_mode == request.approved_execution_mode


def test_v2_request_requires_explicit_approved_execution_mode():
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload.pop("approved_execution_mode", None)

    with pytest.raises(PartitionContractError) as error:
        PartitionPlanningRequest.from_dict(payload)

    assert error.value.code == "approved_mode_required"


def test_common_processor_rejects_missing_v2_approved_execution_mode(
    inference_request,
):
    request = replace(inference_request, approved_execution_mode=None)

    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)

    assert error.value.code == "approved_mode_required"


@pytest.mark.parametrize("version", ["", " ", 0])
def test_common_processor_rejects_blank_or_invalid_model_version(
    inference_request, version
):
    request = replace(
        inference_request,
        plan=replace(inference_request.plan, approved_model_version=version),
        context=replace(
            inference_request.context,
            model_structure_profile=replace(
                inference_request.context.model_structure_profile, model_version=version
            ),
            model_registry_context=replace(
                inference_request.context.model_registry_context,
                approved_model_version=version,
            ),
        ),
    )

    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)

    assert error.value.code == "model_version_mismatch"


def test_common_processor_rejects_unsupported_plan_type(inference_request):
    request = replace(
        inference_request,
        envelope=replace(inference_request.envelope, plan_type="unsupported"),
    )

    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)

    assert error.value.code == "unsupported_plan_type"


@pytest.mark.parametrize("field", ["approved_by", "approval_ref"])
def test_common_processor_rejects_missing_upstream_approval_provenance(
    inference_request, field
):
    request = replace(
        inference_request,
        envelope=replace(inference_request.envelope, **{field: ""}),
    )

    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)

    assert error.value.code == "approval_provenance_required"


def test_common_processor_rejects_missing_model_profile(inference_request):
    request = replace(
        inference_request,
        context=replace(inference_request.context, model_structure_profile=None),
    )

    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)

    assert error.value.code == "model_profile_missing"


def test_common_processor_rejects_missing_participant_device(inference_request):
    request = replace(
        inference_request,
        context=replace(
            inference_request.context,
            devices=tuple(
                device
                for device in inference_request.context.devices
                if device.device_id != "gpu-worker-01"
            ),
        ),
    )

    with pytest.raises(PartitionContractError) as error:
        PartitionCommonProcessor().process(request)

    assert error.value.code == "early_feasibility_failed"

