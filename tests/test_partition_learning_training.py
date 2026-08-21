from __future__ import annotations

import hashlib
import json
import sys
from builtins import __import__ as builtin_import
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_context import canonical_json
from aiops_k8s_agents.partition_features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from aiops_k8s_agents.partition_learning import (
    PartitionRankingTrainingRow,
    _candidate_selection_metrics,
    evaluate_partition_ranker,
    group_holdout_split,
    group_key,
    load_partition_ranking_dataset,
    train_partition_ranker,
    write_partition_ranking_dataset,
)
from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_ranker_repository import PartitionRankerRepository
from aiops_k8s_agents.partition_ranking import LearnedRewardRanker


def test_group_split_never_leaks_job_snapshot_lineage(dataset_rows):
    split = group_holdout_split(dataset_rows, test_fraction=0.25, seed=17)

    train_groups = {group_key(row) for row in split.train}
    test_groups = {group_key(row) for row in split.test}

    assert train_groups.isdisjoint(test_groups)
    assert len(split.train) + len(split.test) == len(dataset_rows)


def test_training_exports_verified_observed_ridge_artifact(tmp_path, observed_dataset_path):
    pytest.importorskip("sklearn")

    summary = train_partition_ranker(
        observed_dataset_path,
        registry_root=tmp_path / "registry",
        model_version="partition-ridge-observed-v1",
        seed=17,
    )
    payload = json.loads(summary.artifact_path.read_text(encoding="utf-8"))

    assert payload["model_type"] == "ridge_reward_regressor"
    assert payload["training_scope"] == "observed"
    assert len(payload["coefficients"]) == len(payload["feature_order"])
    assert payload["artifact_hash"] == hashlib.sha256(
        canonical_json({key: value for key, value in payload.items() if key != "artifact_hash"}).encode(
            "utf-8"
        )
    ).hexdigest()
    assert payload["validation_metrics"]["quality_eligible"] in (0.0, 1.0)
    assert payload["validation_metrics"]["deployment_eligible"] in (0.0, 1.0)
    assert payload["training_provenance"] == {
        "eligibility_thresholds": {
            "maximum_holdout_mae": 0.25,
            "maximum_ood_feature_ratio": 0.2,
            "minimum_independent_groups": 5,
            "minimum_observed_samples": 30,
            "minimum_selection_confidence": 0.7,
            "minimum_spearman_correlation": 0.3,
        },
        "holdout_test_fraction": 0.2,
        "ridge_alpha": 1.0,
        "seed": 17,
        "training_lineage_group_hashes": sorted({group_key(row) for row in _read_training_rows(observed_dataset_path)}),
    }


def test_registered_artifact_reproduces_prediction_without_sklearn(
    tmp_path, observed_dataset_path, monkeypatch
):
    pytest.importorskip("sklearn")
    summary = train_partition_ranker(
        observed_dataset_path,
        registry_root=tmp_path / "registry",
        model_version="partition-ridge-observed-v1",
        seed=17,
    )
    monkeypatch.setitem(sys.modules, "sklearn", None)

    artifact = PartitionRankerRepository(tmp_path / "registry").get(summary.model_version)
    features = _row_features(_read_rows(observed_dataset_path)[0])
    expected = artifact.intercept + sum(
        coefficient * ((features[name] - mean) / scale)
        for name, coefficient, mean, scale in zip(
            artifact.feature_order,
            artifact.coefficients,
            artifact.feature_mean,
            artifact.feature_scale,
            strict=True,
        )
    )

    prediction, _, _ = LearnedRewardRanker(artifact).predict(features)

    assert prediction == pytest.approx(max(-1.0, min(1.0, expected)))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda manifest: manifest.update({"dataset_sha256": "0" * 64}), "dataset_hash_mismatch"),
        (lambda manifest: manifest.update({"scope": "synthetic"}), "dataset_scope_mismatch"),
    ],
)
def test_training_rejects_invalid_dataset_manifest_before_fitting(
    observed_dataset_path, mutation, code
):
    manifest_path = Path(f"{observed_dataset_path}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutation(manifest)
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(PartitionContractError) as error:
        train_partition_ranker(
            observed_dataset_path,
            registry_root=observed_dataset_path.parent / "registry",
            model_version="partition-ridge-observed-v1",
        )

    assert error.value.code == code


def test_training_rejects_schema_mismatch_nan_and_insufficient_groups(tmp_path, dataset_rows):
    schema_mismatch = list(dataset_rows)
    schema_mismatch[0] = _replace_row(schema_mismatch[0], feature_schema_version="other-schema")
    schema_path = _write_dataset(tmp_path / "schema.jsonl", schema_mismatch, scope="observed")
    with pytest.raises(PartitionContractError) as schema_error:
        train_partition_ranker(
            schema_path, registry_root=tmp_path / "registry", model_version="schema-mismatch"
        )
    assert schema_error.value.code == "feature_schema_mismatch"

    nan_rows = list(dataset_rows)
    nan_rows[0] = _replace_row(nan_rows[0], features={**nan_rows[0].features, FEATURE_ORDER[0]: float("nan")})
    nan_path = _write_dataset(tmp_path / "nan.jsonl", nan_rows, scope="observed")
    with pytest.raises(PartitionContractError) as nan_error:
        train_partition_ranker(
            nan_path, registry_root=tmp_path / "registry", model_version="nan-features"
        )
    assert nan_error.value.code == "nonfinite_features"

    short_path = _write_dataset(tmp_path / "short.jsonl", dataset_rows[:2], scope="observed")
    with pytest.raises(PartitionContractError) as short_error:
        train_partition_ranker(
            short_path, registry_root=tmp_path / "registry", model_version="too-small"
        )
    assert short_error.value.code == "insufficient_training_data"


def test_evaluation_keeps_synthetic_scope_non_deployment_eligible(tmp_path, dataset_rows):
    pytest.importorskip("sklearn")
    observed_path = _write_dataset(tmp_path / "observed.jsonl", dataset_rows, scope="observed")
    summary = train_partition_ranker(
        observed_path,
        registry_root=tmp_path / "registry",
        model_version="partition-ridge-observed-v1",
    )
    synthetic_rows = [
        _replace_row(
            row,
            evidence_level="synthetic",
            evidence_source="offline-generator",
            observed_at="",
            runtime_outcome_ref=f"synthetic/{row.row_id}/versions/1/result",
        )
        for row in dataset_rows
    ]
    synthetic_path = _write_dataset(tmp_path / "synthetic.jsonl", synthetic_rows, scope="synthetic")

    evaluation = evaluate_partition_ranker(synthetic_path, summary.artifact)

    assert evaluation.scope == "synthetic"
    assert evaluation.deployment_eligible is False
    assert evaluation.metrics["deployment_eligible"] == 0.0


def test_dataset_loader_rejects_offline_generator_forged_as_observed(tmp_path, dataset_rows):
    forged_rows = [
        _replace_row(row, evidence_source="offline-generator") for row in dataset_rows
    ]
    forged_path = _write_dataset(tmp_path / "forged-observed.jsonl", forged_rows, scope="observed")

    with pytest.raises(PartitionContractError) as error:
        load_partition_ranking_dataset(forged_path)

    assert error.value.code == "dataset_scope_mismatch"


def test_dataset_loader_rejects_malformed_observed_timestamp(tmp_path, dataset_rows):
    malformed_rows = [_replace_row(dataset_rows[0], observed_at="not-a-timestamp")]
    dataset_path = _write_dataset(tmp_path / "malformed-timestamp.jsonl", malformed_rows, scope="observed")

    with pytest.raises(PartitionContractError) as error:
        load_partition_ranking_dataset(dataset_path)

    assert error.value.code == "invalid_dataset_row"


def test_direct_observed_jsonl_is_not_eligible_for_real_claims(tmp_path, dataset_rows):
    dataset_path = _write_dataset(tmp_path / "direct-observed.jsonl", dataset_rows, scope="observed")

    dataset = load_partition_ranking_dataset(dataset_path)

    assert dataset.eligible_for_real_claims is False


def test_dataset_writer_and_loader_share_the_lineage_group_contract(tmp_path, dataset_rows):
    rows = (
        _replace_row(
            dataset_rows[0],
            job_id="shared-job",
            input_snapshot_hash="shared-snapshot",
            runtime_outcome_ref="outcomes/one/versions/1/result",
        ),
        _replace_row(
            dataset_rows[1],
            job_id="shared-job",
            input_snapshot_hash="shared-snapshot",
            runtime_outcome_ref="outcomes/two/versions/1/result",
        ),
    )

    summary = write_partition_ranking_dataset(
        rows,
        tmp_path / "lineage.jsonl",
        scope="observed",
        rejection_counts={},
        artifact_roots=(),
    )
    dataset = load_partition_ranking_dataset(tmp_path / "lineage.jsonl")

    assert summary.lineage_group_count == len({group_key(row) for row in rows}) == 2
    assert len({group_key(row) for row in dataset.rows}) == summary.lineage_group_count


def test_candidate_selection_agreement_uses_the_reward_best_candidate(dataset_rows):
    rows = dataset_rows[:2]

    metrics = _candidate_selection_metrics(rows, predictions=(0.1, 0.9))

    assert metrics["candidate_selection_agreement"] == 1.0
    assert metrics["learned_regret"] == 0.0


def test_candidate_selection_metrics_keep_unavailable_keys_without_comparable_groups(dataset_rows):
    metrics = _candidate_selection_metrics((dataset_rows[0],), predictions=(0.1,))

    assert metrics["candidate_selection_agreement"] == 0.0
    assert metrics["candidate_selection_agreement_available"] == 0.0
    assert metrics["learned_regret"] == 0.0
    assert metrics["learned_regret_available"] == 0.0


def test_evaluation_rejects_its_training_dataset_as_not_independent(
    tmp_path, observed_dataset_path
):
    pytest.importorskip("sklearn")
    summary = train_partition_ranker(
        observed_dataset_path,
        registry_root=tmp_path / "registry",
        model_version="partition-ridge-observed-v1",
    )

    with pytest.raises(PartitionContractError) as error:
        evaluate_partition_ranker(observed_dataset_path, summary.artifact)

    assert error.value.code == "evaluation_dataset_not_independent"


def test_evaluation_rejects_lineage_overlap_with_its_training_dataset(
    tmp_path, observed_dataset_path
):
    pytest.importorskip("sklearn")
    summary = train_partition_ranker(
        observed_dataset_path,
        registry_root=tmp_path / "registry",
        model_version="partition-ridge-observed-v1",
    )
    evaluation_rows = [
        _replace_row(row, target_reward=row.target_reward + 0.001) for row in _read_training_rows(observed_dataset_path)
    ]
    evaluation_path = _write_dataset(tmp_path / "overlap.jsonl", evaluation_rows, scope="observed")

    with pytest.raises(PartitionContractError) as error:
        evaluate_partition_ranker(evaluation_path, summary.artifact)

    assert error.value.code == "evaluation_dataset_not_independent"


def test_training_reports_missing_optional_ml_dependency(tmp_path, observed_dataset_path, monkeypatch):
    def unavailable_ml_import(name, *args, **kwargs):
        if name == "sklearn" or name.startswith("sklearn."):
            raise ImportError("scikit-learn is unavailable")
        return builtin_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", unavailable_ml_import)

    with pytest.raises(PartitionContractError) as error:
        train_partition_ranker(
            observed_dataset_path,
            registry_root=tmp_path / "registry",
            model_version="partition-ridge-observed-v1",
        )

    assert error.value.code == "ml_dependency_missing"


@pytest.fixture
def dataset_rows() -> tuple[PartitionRankingTrainingRow, ...]:
    rows = []
    for group_index in range(10):
        for duplicate_index in range(3):
            features = {
                name: float((feature_index + 1) * (group_index + 1) + duplicate_index)
                for feature_index, name in enumerate(FEATURE_ORDER)
            }
            rows.append(
                PartitionRankingTrainingRow(
                    row_id=f"row-{group_index}-{duplicate_index}",
                    job_id=f"job-{group_index}",
                    plan_id=f"plan-{group_index}-{duplicate_index}",
                    plan_version=1,
                    candidate_key=f"candidate-{group_index}-{duplicate_index}",
                    input_snapshot_hash=f"snapshot-{group_index}",
                    policy_version="policy-v1",
                    strategy_version="strategy-v1",
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    features=features,
                    target_reward=-0.8 + (group_index * 0.15) + (duplicate_index * 0.01),
                    reward_components={"latency": 0.1},
                    evidence_level="observed",
                    evidence_source="runtime-monitor",
                    observed_at="2026-08-21T09:30:00Z",
                    selected_by="deterministic-policy-ranker",
                    selection_probability=None,
                    runtime_outcome_ref=(
                        f"jobs/{group_index}/versions/{duplicate_index}/outcomes/{duplicate_index}"
                    ),
                )
            )
    return tuple(rows)


@pytest.fixture
def observed_dataset_path(tmp_path, dataset_rows) -> Path:
    return _write_dataset(tmp_path / "observed.jsonl", dataset_rows, scope="observed")


def _write_dataset(
    path: Path, rows: list[PartitionRankingTrainingRow] | tuple[PartitionRankingTrainingRow, ...], *, scope: str
) -> Path:
    payload = b"".join(
        (canonical_json(row.to_dict()) + "\n").encode("utf-8") for row in rows
    )
    path.write_bytes(payload)
    manifest = {
        "schema_version": "partition-ranking-dataset-v1",
        "scope": scope,
        "row_count": len(rows),
        "rejections": {},
        "dataset_sha256": hashlib.sha256(payload).hexdigest(),
        "unique_job_count": len({row.job_id for row in rows}),
        "unique_snapshot_count": len({row.input_snapshot_hash for row in rows}),
        "lineage_group_count": len({group_key(row) for row in rows}),
        "source_roots": [str(path.parent)],
        "selected_candidates_only": True,
        "eligible_for_real_claims": False,
    }
    Path(f"{path}.manifest.json").write_text(
        canonical_json(manifest) + "\n", encoding="utf-8"
    )
    return path


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_training_rows(path: Path) -> list[PartitionRankingTrainingRow]:
    return [
        PartitionRankingTrainingRow(**row)
        for row in _read_rows(path)
    ]


def _row_features(row: dict) -> dict[str, float]:
    return {name: float(value) for name, value in row["features"].items()}


def _replace_row(row: PartitionRankingTrainingRow, **changes) -> PartitionRankingTrainingRow:
    return PartitionRankingTrainingRow(**{**row.__dict__, **changes})
