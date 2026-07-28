from __future__ import annotations

from dataclasses import replace

from aiops_k8s_agents.experiment_session import (
    ExperimentSession,
    InMemoryExperimentSessionStore,
    normalize_experiment_session,
)


def _mutual_report() -> dict[str, object]:
    return {
        "run_id": "experiment-001",
        "mode": "mock",
        "valid": True,
        "final_status": "recovered",
        "protocol_profile": {
            "profile_id": "four-agent-role-veto-v1",
            "version": "1.0.0",
            "config_hash": "a" * 64,
        },
        "active_agents": [
            "AIServiceHASupportAgent",
            "AIApplicationManagementAgent",
            "AISemiconductorInfraOpsAgent",
            "CostOptimizationAgent",
        ],
        "evidence": {
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric_values": {"cpu": 95.0},
            "source": "control-plane-fake",
        },
        "diagnosis": {
            "cause": "cpu_saturation",
            "severity": "critical",
        },
        "initial_decisions": [{"agent": "AIServiceHASupportAgent"}],
        "peer_reviews": [{"reviewer": "CostOptimizationAgent"}],
        "negotiation": {
            "consensus": "approved",
            "round_count": 1,
            "strategy": "role_based_veto",
        },
        "selected_action": {
            "kind": "scale_out",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "replicas": 3,
        },
        "safety_validation": {
            "valid": True,
            "command": (
                "kubectl scale deployment paymentservice --replicas=3 "
                "-n online-boutique"
            ),
            "stderr": "",
        },
        "execution_result": {
            "valid": True,
            "mode": "mock",
            "command": (
                "kubectl scale deployment paymentservice --replicas=3 "
                "-n online-boutique"
            ),
            "stdout": "mock: command validated and not executed",
            "stderr": "",
        },
        "recovery_monitoring": {
            "recovered": True,
            "recovery_seconds": 2.4,
        },
        "post_execution_reviews": [
            {"reviewer": "AIServiceHASupportAgent", "approved": True}
        ],
        "human_review_required": False,
        "metadata": {
            "controller": "mutual_supervision_deterministic",
            "guard_backend": "python",
        },
    }


def _session(experiment_id: str) -> ExperimentSession:
    return replace(
        normalize_experiment_session(_mutual_report()),
        experiment_id=experiment_id,
    )


def test_mutual_report_normalizes_to_one_experiment_session():
    report = _mutual_report()
    session = normalize_experiment_session(report)

    assert session.experiment_id == report["run_id"]
    assert session.protocol_profile["profile_id"] == "four-agent-role-veto-v1"
    assert session.stages["evidence"]["status"] == "completed"
    assert session.stages["consensus"]["experiment_id"] == session.experiment_id
    assert session.stages["safety"]["experiment_id"] == session.experiment_id
    assert session.stages["result"]["experiment_id"] == session.experiment_id
    assert session.stages["execution"]["status"] == "completed"


def test_validation_rejection_blocks_safety_and_skips_execution():
    report = _mutual_report()
    report["valid"] = False
    report["final_status"] = "safe_stopped"
    report["safety_validation"] = {
        "valid": False,
        "command": "",
        "stderr": "replica limit exceeded",
    }
    report["execution_result"] = {
        "valid": False,
        "mode": "mock",
        "command": "",
        "stdout": "",
        "stderr": "no action executed",
    }
    report["human_review_required"] = True

    session = normalize_experiment_session(report)

    assert session.status == "safe_stopped"
    assert session.stages["safety"]["status"] == "blocked"
    assert session.stages["execution"]["status"] == "pending"
    assert session.human_review_required is True


def test_session_serialization_returns_detached_nested_copies():
    session = normalize_experiment_session(_mutual_report())

    first = session.to_dict()
    first["stages"]["evidence"]["payload"]["source"] = "tampered"
    second = session.to_dict()

    assert second["stages"]["evidence"]["payload"]["source"] == (
        "control-plane-fake"
    )


def test_session_store_evicts_oldest_entry_and_lists_newest_first():
    store = InMemoryExperimentSessionStore(max_sessions=2)
    store.put(_session("one"))
    store.put(_session("two"))
    store.put(_session("three"))

    assert store.get("one") is None
    assert [item.experiment_id for item in store.list()] == ["three", "two"]


def test_session_store_rejects_non_positive_capacity():
    try:
        InMemoryExperimentSessionStore(max_sessions=0)
    except ValueError as exc:
        assert "max_sessions" in str(exc)
    else:
        raise AssertionError("non-positive session capacity was accepted")
