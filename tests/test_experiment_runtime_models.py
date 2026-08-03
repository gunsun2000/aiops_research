from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from enum import Enum
import json
from math import inf, nan
from pathlib import Path
from types import MappingProxyType

import pytest

from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    ExperimentRuntimeResult,
    RuntimeEvent,
    RuntimeStage,
)
from aiops_k8s_agents.experiment_session import (
    ExperimentSession,
    normalize_experiment_session,
)


def _session() -> ExperimentSession:
    return normalize_experiment_session(
        {
            "run_id": "exp-1",
            "mode": "mock",
            "final_status": "recovered",
            "protocol_profile": {"profile_id": "profile-v1"},
            "evidence": {"namespace": "online-boutique"},
        }
    )


def test_runtime_request_normalizes_mode_and_target():
    request = ExperimentRuntimeRequest(
        scenario_id=" cpu-stress ",
        namespace=" online-boutique ",
        deployment=" paymentservice ",
        metric="CPU-utilization",
        threshold=80.0,
        mode="dry-run",
        backend="python",
        protocol_profile=" four-agent-role-veto-v1 ",
    )

    assert request.scenario_id == "cpu-stress"
    assert request.namespace == "online-boutique"
    assert request.deployment == "paymentservice"
    assert request.metric == "cpu_utilization"
    assert request.mode.value == "dry-run"
    assert request.backend.value == "python"
    assert request.protocol_profile == "four-agent-role-veto-v1"
    assert request.controller == "deterministic"
    assert request.to_dict()["controller"] == "deterministic"
    json.dumps(request.to_dict(), allow_nan=False)
    with pytest.raises(FrozenInstanceError):
        request.namespace = "default"


def test_runtime_request_normalizes_explicit_autogen_controller():
    request = ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="mock",
        backend="python",
        protocol_profile="four-agent-autogen-v1",
        controller=" AutoGen ",
    )

    assert request.controller == "autogen"
    assert request.to_dict()["controller"] == "autogen"


def test_runtime_request_rejects_unknown_controller():
    with pytest.raises(ValueError, match="controller"):
        ExperimentRuntimeRequest(
            "scenario", "namespace", "deployment", "cpu", 80.0,
            "mock", "python", "profile", controller="free-form-agent",
        )


@pytest.mark.parametrize("field", ["scenario_id", "namespace", "deployment", "metric", "protocol_profile"])
def test_runtime_request_rejects_empty_identifiers(field):
    values = {
        "scenario_id": "cpu-stress",
        "namespace": "online-boutique",
        "deployment": "paymentservice",
        "metric": "cpu",
        "threshold": 80.0,
        "mode": "mock",
        "backend": "python",
        "protocol_profile": "profile-v1",
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        ExperimentRuntimeRequest(**values)


@pytest.mark.parametrize("repetitions", [True, False, 0, -1])
def test_runtime_request_rejects_invalid_repetitions(repetitions):
    with pytest.raises(ValueError, match="repetitions"):
        ExperimentRuntimeRequest(
            "scenario", "namespace", "deployment", "cpu", 80.0,
            "mock", "python", "profile", repetitions,
        )


@pytest.mark.parametrize("threshold", [nan, inf, -inf])
def test_runtime_request_rejects_non_finite_threshold(threshold):
    with pytest.raises(ValueError, match="threshold"):
        ExperimentRuntimeRequest(
            "scenario", "namespace", "deployment", "cpu", threshold,
            "mock", "python", "profile",
        )


def test_runtime_event_serializes_and_detaches_payload():
    payload = {"source": {"labels": ["pod"]}}
    event = RuntimeEvent(
        "exp-1", 3, RuntimeStage.COLLECTING_EVIDENCE, "running",
        "collecting registered evidence", "2026-08-03T00:00:00+00:00", payload,
    )

    serialized = event.to_dict()
    assert serialized["stage"] == "collecting_evidence"
    assert serialized["sequence"] == 3
    json.dumps(serialized, allow_nan=False)
    serialized["payload"]["source"]["labels"].append("tampered")
    assert event.payload["source"]["labels"] == ("pod",)
    with pytest.raises(ValueError, match="sequence"):
        RuntimeEvent("exp-1", -1, RuntimeStage.QUEUED, "queued", "waiting", "now", {})


def test_runtime_result_serializes_session_events_and_mutable_copies():
    result = ExperimentRuntimeResult(
        experiment_id="exp-1",
        status="completed",
        report={"summary": {"ok": True}},
        session=_session(),
        events=(RuntimeEvent("exp-1", 0, RuntimeStage.COMPLETED, "done", "finished", "now"),),
        cleanup={"valid": True},
    )

    serialized = result.to_dict()
    assert serialized["session"]["experiment_id"] == "exp-1"
    assert serialized["events"][0]["stage"] == "completed"
    serialized["report"]["summary"]["ok"] = False
    serialized["cleanup"]["valid"] = False
    assert result.report["summary"]["ok"] is True
    assert result.cleanup["valid"] is True


class _EvidenceKind(Enum):
    CPU = "cpu"


def test_runtime_result_to_dict_is_json_safe_for_nested_runtime_values():
    observed_at = datetime(2026, 8, 3, 1, 2, 3, tzinfo=timezone.utc)
    report = MappingProxyType(
        {
            "observed_at": observed_at,
            "artifact": Path("evidence.json"),
            "evidence": (
                _EvidenceKind.CPU,
                MappingProxyType({"timestamps": (observed_at,)}),
            ),
        }
    )
    event = RuntimeEvent(
        "exp-1",
        0,
        RuntimeStage.COLLECTING_EVIDENCE,
        "completed",
        "evidence collected",
        "2026-08-03T00:00:00+00:00",
        {"observed_at": observed_at, "values": (1, 2)},
    )
    result = ExperimentRuntimeResult(
        "exp-1",
        "completed",
        report,
        _session(),
        (event,),
        MappingProxyType({"finished_at": observed_at}),
    )

    serialized = result.to_dict()
    json.dumps(serialized, allow_nan=False)

    assert serialized["report"]["observed_at"] == "2026-08-03T01:02:03+00:00"
    assert serialized["report"]["artifact"] == "evidence.json"
    assert serialized["report"]["evidence"][0] == "cpu"
    assert serialized["report"]["evidence"][1]["timestamps"] == [
        "2026-08-03T01:02:03+00:00"
    ]
    assert result.report["observed_at"] == "2026-08-03T01:02:03+00:00"
    assert result.report["evidence"][1]["timestamps"] == (
        "2026-08-03T01:02:03+00:00",
    )
    assert result.events[0].payload["observed_at"] == (
        "2026-08-03T01:02:03+00:00"
    )
    assert result.events[0].payload["values"] == (1, 2)


def test_runtime_event_rejects_nested_non_finite_float_at_construction():
    with pytest.raises(ValueError, match="finite"):
        RuntimeEvent(
            "exp-1", 0, RuntimeStage.QUEUED, "queued", "waiting", "now",
            {"nested": {"value": nan}},
        )


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_runtime_result_rejects_nested_non_finite_float_at_construction(value):
    with pytest.raises(ValueError, match="finite"):
        ExperimentRuntimeResult(
            "exp-1",
            "completed",
            {"nested": (MappingProxyType({"value": value}),)},
            _session(),
            (),
            {"valid": True},
        )


def test_runtime_result_rejects_opaque_nested_object_at_construction():
    with pytest.raises(TypeError, match="not JSON serializable"):
        ExperimentRuntimeResult(
            "exp-1",
            "completed",
            {"nested": [object()]},
            _session(),
            (),
            {"valid": True},
        )
