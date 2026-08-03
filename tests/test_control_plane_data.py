from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiops_k8s_agents.control_plane_data import (
    artifact_path,
    build_overview,
    get_experiment_session,
    latest_recovery_run,
    parse_agent_reviews,
    run_mock_alert,
    run_mutual_supervision_mock,
    run_scenario_experiment_mock,
    scenario_catalog,
)


def test_parse_agent_reviews_extracts_consensus_metadata():
    reviews = parse_agent_reviews(
        {
            "agents": "HA,App",
            "decisions": "HA:approved|App:rejected",
            "actions": "HA:ha_scale_out_required|App:app_observe_only",
            "rewards": "HA:0.90|App:0.10",
        }
    )

    assert reviews == [
        {
            "agent": "HA",
            "decision": "approved",
            "action": "ha_scale_out_required",
            "reward": 0.9,
        },
        {
            "agent": "App",
            "decision": "rejected",
            "action": "app_observe_only",
            "reward": 0.1,
        },
    ]


def test_latest_recovery_run_summarizes_artifacts(tmp_path: Path):
    run_dir = tmp_path / "runs" / "recovery-action-pilot" / "20260723_120000"
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "statistics").mkdir()
    (run_dir / "outcomes.jsonl").write_text('{"ok": true}\n{"ok": true}\n')
    (run_dir / "analysis" / "reward_policy_comparison.md").write_text(
        "# Reward\nbalanced policy\n",
        encoding="utf-8",
    )
    (run_dir / "statistics" / "success_rate_by_action.png").write_bytes(b"png")
    (run_dir / "statistics" / "quantitative_summary.md").write_text(
        "# Summary\n- success: 1.0\n",
        encoding="utf-8",
    )

    summary = latest_recovery_run(tmp_path)

    assert summary is not None
    assert summary["name"] == "20260723_120000"
    assert summary["outcome_count"] == 2
    assert summary["has_reward_policy"] is True
    assert summary["has_statistics"] is True
    assert "balanced policy" in summary["reward_policy_excerpt"]
    assert "runs/recovery-action-pilot/20260723_120000/statistics/success_rate_by_action.png" in summary["statistics_files"]


def test_build_overview_reports_core_health(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "agent_registry.json").write_text(
        json.dumps(
            {
                "version": "1",
                "agents": [
                    {
                        "name": "A",
                        "bounded_actions": ["observe_only"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "recovery_action_experiments.json").write_text("{}", encoding="utf-8")
    (tmp_path / "k8s" / "chaos").mkdir(parents=True)

    overview = build_overview(tmp_path)

    assert overview["project"] == "AIOps 4-Agent Control Plane"
    assert overview["health"]["agent_registry"] is True
    assert overview["health"]["recovery_config"] is True
    assert overview["health"]["chaos_manifests"] is True


def test_mock_alert_uses_existing_four_agent_pipeline():
    payload = run_mock_alert(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
    )

    assert payload["result"]["valid"] is True
    assert payload["result"]["mode"] == "mock"
    assert "kubectl scale deployment paymentservice" in payload["result"]["command"]
    assert [item["agent"] for item in payload["agent_reviews"]] == [
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    ]


def test_mutual_supervision_mock_exposes_negotiation_and_post_reviews():
    report = run_mutual_supervision_mock(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
    )

    assert report["valid"] is True
    assert report["final_status"] == "recovered"
    assert report["negotiation"]["consensus"] == "approved"
    assert len(report["peer_reviews"]) >= 3
    assert len(report["post_execution_reviews"]) == 4
    assert report["execution_result"]["mode"] == "mock"


@pytest.mark.parametrize(
    ("scenario_id", "deployment", "metric", "value"),
    [
        ("cpu-stress", "paymentservice", "cpu", 95.0),
        ("memory-stress", "checkoutservice", "memory", 95.7),
        ("network-delay", "paymentservice", "latency", 0.234),
        ("pod-kill", "paymentservice", "availability", 0.0),
    ],
)
def test_scenario_experiment_creates_one_stored_session(
    scenario_id: str,
    deployment: str,
    metric: str,
    value: float,
):
    session = run_scenario_experiment_mock(
        scenario_id=scenario_id,
        backend="python",
    )

    assert session.mode == "mock"
    assert session.status == "recovered"
    assert session.condition["scenario"] == scenario_id
    assert session.condition["deployment"] == deployment
    assert session.condition["metric_values"][metric] == value
    assert len(session.active_agents) == 4
    assert session.stages["execution"]["status"] == "completed"
    assert session.stages["result"]["status"] == "completed"
    assert (
        session.stages["consensus"]["payload"]["selected_action"]["kind"]
        in {"observe_only", "rollout_restart", "scale_out"}
    )
    assert get_experiment_session(session.experiment_id) == session


def test_scenario_catalog_exposes_all_registered_faults():
    catalog = scenario_catalog()

    assert [item["scenario_id"] for item in catalog] == [
        "pod-kill",
        "cpu-stress",
        "memory-stress",
        "network-delay",
    ]
    assert all(item["mode"] == "mock" for item in catalog)


def test_scenario_catalog_accepts_registered_runtime_configuration(tmp_path: Path):
    source = Path("config/experiment_runtime.json")
    config_path = tmp_path / "experiment_runtime.json"
    config_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    from aiops_k8s_agents.real_evidence import load_runtime_configuration

    catalog = scenario_catalog(load_runtime_configuration(config_path))

    assert catalog[0]["manifest"] == "k8s/paymentservice-pod-kill.yaml"
    assert catalog[0]["ui_fallback"] is True


def test_scenario_experiment_rejects_unknown_scenario():
    with pytest.raises(ValueError, match="unknown scenario"):
        run_scenario_experiment_mock(
            scenario_id="disk-pressure",
            backend="python",
        )


def test_pod_kill_scenario_uses_internally_consistent_unavailable_evidence():
    session = run_scenario_experiment_mock(
        scenario_id="pod-kill",
        backend="python",
    )
    evidence = session.stages["evidence"]["payload"]

    assert evidence["metric_values"]["availability"] == 0.0
    assert evidence["desired_replicas"] == 1
    assert evidence["available_replicas"] == 0
    assert "Running" not in evidence["pod_statuses"]


def test_artifact_path_rejects_files_outside_allowed_roots(tmp_path: Path):
    outside = tmp_path / "README.md"
    outside.write_text("no", encoding="utf-8")

    try:
        artifact_path("README.md", tmp_path)
    except ValueError as exc:
        assert "outside allowed directories" in str(exc)
    else:
        raise AssertionError("artifact_path accepted an unsafe path")


def test_artifact_path_allows_research_docs(tmp_path: Path):
    doc = tmp_path / "docs" / "submission" / "guide.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("ok", encoding="utf-8")

    assert artifact_path("docs/submission/guide.md", tmp_path) == doc.resolve()
