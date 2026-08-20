from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import (
    LegacyFederatedRoundPlanAdapter,
    PartitionPlanningRequest,
)
from aiops_k8s_agents.partition_models import PartitionContractError


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
