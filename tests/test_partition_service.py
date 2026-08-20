from __future__ import annotations

import json
from pathlib import Path

from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.partition_service import run_partition_planning


ROOT = Path(__file__).resolve().parents[1]


def test_partition_service_persists_same_validated_and_evaluated_plan(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )

    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        plan_id_factory=lambda: "partition-service-plan",
    )
    stored = json.loads(Path(report["artifact_path"]).read_text(encoding="utf-8"))

    assert report["status"] == "planned"
    assert report["plan"]["selected_candidate"]["split_points"] == [3]
    assert report["validation"]["valid"] is True
    assert report["evaluation"]["evidence_level"] == "predicted"
    assert "estimated" in report["evaluation"]["label"].lower()
    assert stored["plan"] == report["plan"]
    assert stored["validation"] == report["validation"]
    assert stored["evaluation"] == report["evaluation"]
    artifact_directory = Path(report["artifact_path"]).parent
    version_directory = artifact_directory / "versions" / "1"
    assert (version_directory / "normalized_request.json").is_file()
    assert (version_directory / "partition_intent.json").is_file()
    handoff = json.loads(
        (version_directory / "scheduling_handoff.json").read_text(encoding="utf-8")
    )
    assert handoff["status"] == "blocked"
    assert handoff["scheduler_ref"] is None
    assert report["scheduling_handoff"] == handoff


def test_partition_service_supports_bounded_replanning(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    first = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        plan_id_factory=lambda: "partition-first-plan",
    )

    second = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        previous_plan_payload=first["plan"],
        failure_payload={"signal": "latency_slo_violation"},
        replan_attempt=1,
        plan_id_factory=lambda: "partition-second-plan",
    )

    assert second["plan"]["selected_candidate"]["split_points"] != [3]
    assert second["replanning"]["attempt"] == 1


def test_artifact_writer_adds_a_blocked_handoff_for_existing_valid_reports(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path / "service-artifacts",
        plan_id_factory=lambda: "partition-service-plan",
    )
    report.pop("scheduling_handoff")

    artifact_path = write_partition_report(report, tmp_path / "writer-artifacts")
    handoff = json.loads(
        (
            artifact_path.parent
            / "versions"
            / "1"
            / "scheduling_handoff.json"
        ).read_text(encoding="utf-8")
    )

    assert handoff["status"] == "blocked"
    assert handoff["scheduler_ref"] is None
