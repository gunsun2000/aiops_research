from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.partition_features import candidate_key
from aiops_k8s_agents.partition_learning import build_partition_ranking_dataset
from aiops_k8s_agents.partition_models import PartitionCandidate
from aiops_k8s_agents.partition_service import run_partition_planning


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_report_fixture(root: Path, report: dict) -> Path:
    return write_partition_report(report, root)


@pytest.fixture
def observed_report(tmp_path) -> dict:
    report = _planned_report(tmp_path / "source", "observed-plan")
    return _as_observed(report)


@pytest.fixture
def predicted_report(tmp_path) -> dict:
    return _planned_report(tmp_path / "source", "predicted-plan")


def test_dataset_defaults_to_observed_selected_candidates_only(
    tmp_path, observed_report, predicted_report
):
    observed_root = tmp_path / "observed"
    predicted_root = tmp_path / "predicted"
    write_report_fixture(observed_root, observed_report)
    write_report_fixture(predicted_root, predicted_report)

    summary = build_partition_ranking_dataset(
        (observed_root, predicted_root), tmp_path / "dataset.jsonl"
    )
    rows = read_jsonl(tmp_path / "dataset.jsonl")

    assert summary.scope == "observed"
    assert summary.row_count == 1
    assert rows[0]["evidence_level"] == "observed"
    assert rows[0]["candidate_key"] == observed_report["plan"]["selection"][
        "final_selected_candidate_key"
    ]
    assert summary.rejections["predicted_evidence"] == 1
    assert summary.rejections["unselected_candidate"] == sum(
        len(report["plan"]["alternative_candidates"])
        for report in (observed_report, predicted_report)
    )


def test_dataset_does_not_copy_selected_reward_to_alternatives(tmp_path, observed_report):
    write_report_fixture(tmp_path / "artifacts", observed_report)

    build_partition_ranking_dataset((tmp_path / "artifacts",), tmp_path / "dataset.jsonl")
    rows = read_jsonl(tmp_path / "dataset.jsonl")

    assert len(rows) == 1
    assert rows[0]["candidate_key"] != candidate_key(
        PartitionCandidate.from_dict(observed_report["plan"]["alternative_candidates"][0]),
        observed_report["plan"]["strategy_version"],
    )


def test_dataset_rejects_observed_row_without_source_or_timestamp(tmp_path, observed_report):
    observed_report["evaluation"]["metrics"].pop("source")
    write_report_fixture(tmp_path / "artifacts", observed_report)

    summary = build_partition_ranking_dataset((tmp_path / "artifacts",), tmp_path / "dataset.jsonl")

    assert summary.row_count == 0
    assert summary.rejections["missing_observed_provenance"] == 1


@pytest.mark.parametrize("source", ("mock", "dry-run", "synthetic"))
def test_dataset_excludes_non_runtime_sources_and_discloses_the_reason(
    tmp_path, observed_report, source
):
    observed_report["evaluation"]["metrics"]["source"] = source
    write_report_fixture(tmp_path / "artifacts", observed_report)

    summary = build_partition_ranking_dataset((tmp_path / "artifacts",), tmp_path / "dataset.jsonl")
    manifest = json.loads((tmp_path / "dataset.jsonl.manifest.json").read_text(encoding="utf-8"))

    assert summary.row_count == 0
    assert summary.rejections["non_runtime_evidence_source"] == 1
    assert manifest["rejections"]["non_runtime_evidence_source"] == 1


def test_dataset_reads_only_committed_complete_report_and_sidecars(tmp_path, observed_report):
    root = tmp_path / "artifacts"
    write_report_fixture(root, observed_report)
    partial = root / "partial-plan"
    partial.mkdir()
    (partial / "commit.json").write_text('{"committed": true}\n', encoding="utf-8")
    (partial / "latest.json").write_text("{not-json", encoding="utf-8")

    summary = build_partition_ranking_dataset((root,), tmp_path / "dataset.jsonl")

    assert summary.row_count == 1
    assert summary.rejections["corrupt_or_partial_artifact"] == 1


def test_dataset_excludes_a_corrupt_committed_sidecar_without_aborting(
    tmp_path, observed_report
):
    root = tmp_path / "artifacts"
    write_report_fixture(root, observed_report)
    sidecar = (
        root
        / observed_report["plan"]["plan_id"]
        / "versions"
        / "1"
        / "normalized_request.json"
    )
    sidecar.write_text("{not-json", encoding="utf-8")

    summary = build_partition_ranking_dataset((root,), tmp_path / "dataset.jsonl")

    assert summary.row_count == 0
    assert summary.rejections["corrupt_or_partial_artifact"] == 1


def test_dataset_has_stable_order_hash_and_provenance_manifest(tmp_path, observed_report):
    first = _as_observed(_planned_report(tmp_path / "source-z", "z-plan"))
    second = _as_observed(_planned_report(tmp_path / "source-a", "a-plan"))
    write_report_fixture(tmp_path / "z-root", first)
    write_report_fixture(tmp_path / "a-root", second)

    first_summary = build_partition_ranking_dataset(
        (tmp_path / "z-root", tmp_path / "a-root"), tmp_path / "first.jsonl"
    )
    second_summary = build_partition_ranking_dataset(
        (tmp_path / "a-root", tmp_path / "z-root"), tmp_path / "second.jsonl"
    )
    manifest = json.loads((tmp_path / "first.jsonl.manifest.json").read_text(encoding="utf-8"))

    assert (tmp_path / "first.jsonl").read_bytes() == (tmp_path / "second.jsonl").read_bytes()
    assert first_summary.dataset_hash == second_summary.dataset_hash
    assert first_summary.dataset_hash == hashlib.sha256(
        (tmp_path / "first.jsonl").read_bytes()
    ).hexdigest()
    assert manifest["selected_candidates_only"] is True
    assert manifest["eligible_for_real_claims"] is True
    assert manifest["schema_version"] == "partition-ranking-dataset-v1"


def _planned_report(artifact_root: Path, plan_id: str) -> dict:
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=artifact_root,
        plan_id_factory=lambda: plan_id,
    )


def _as_observed(report: dict) -> dict:
    report["evaluation"] = {
        **report["evaluation"],
        "evidence_level": "observed",
        "estimated": False,
        "label": "Observed reward (runtime evidence)",
        "metrics": {
            **report["evaluation"]["metrics"],
            "source": "runtime-monitor",
            "observed_at": "2026-08-21T09:30:00Z",
        },
    }
    return report
