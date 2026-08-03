from __future__ import annotations

from dataclasses import FrozenInstanceError
from math import inf, nan

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
    with pytest.raises(FrozenInstanceError):
        request.namespace = "default"


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
