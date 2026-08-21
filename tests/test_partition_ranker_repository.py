from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_ranker_repository import (
    PartitionRankerModelArtifact,
    PartitionRankerRepository,
)


@pytest.fixture
def model_artifact() -> PartitionRankerModelArtifact:
    return PartitionRankerModelArtifact(
        schema_version="partition-ranker-model-v2",
        model_type="linear-regression",
        model_version="ranker-2026-08-21",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        trained_at="2026-08-21T00:00:00Z",
        training_dataset_hash="a" * 64,
        training_scope="offline-evaluation",
        sample_count=12,
        group_count=3,
        feature_order=FEATURE_ORDER,
        feature_mean=tuple(float(index) for index, _ in enumerate(FEATURE_ORDER)),
        feature_scale=tuple(1.0 for _ in FEATURE_ORDER),
        coefficients=tuple(0.1 for _ in FEATURE_ORDER),
        intercept=0.25,
        training_feature_ranges={name: (0.0, 100.0) for name in FEATURE_ORDER},
        validation_metrics={"mae": 0.1},
        confidence_policy={"minimum_confidence": 0.8},
        training_provenance={
            "seed": 17,
            "ridge_alpha": 1.0,
            "holdout_test_fraction": 0.2,
            "eligibility_thresholds": {
                "minimum_observed_samples": 30,
                "minimum_independent_groups": 5,
                "maximum_holdout_mae": 0.25,
                "minimum_spearman_correlation": 0.3,
                "minimum_selection_confidence": 0.7,
                "maximum_ood_feature_ratio": 0.2,
            },
            "training_lineage_group_hashes": ("1" * 64, "2" * 64, "3" * 64),
        },
        artifact_hash="",
    )


def test_repository_saves_and_loads_a_verified_model_artifact(tmp_path, model_artifact):
    repository = PartitionRankerRepository(tmp_path)

    path = repository.save(model_artifact)
    loaded = repository.get(model_artifact.model_version)

    assert path == tmp_path / model_artifact.model_version / "model.json"
    assert loaded.model_version == model_artifact.model_version
    assert loaded.feature_order == FEATURE_ORDER
    assert len(loaded.artifact_hash) == 64
    loaded.verify_hash()


def test_repository_rejects_tampered_model_artifact(tmp_path, model_artifact):
    repository = PartitionRankerRepository(tmp_path)
    path = repository.save(model_artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["intercept"] = payload["intercept"] + 0.5
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PartitionContractError, match="artifact hash"):
        repository.get(model_artifact.model_version)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"unrecognized": True}), "unknown artifact fields"),
        (lambda payload: payload.update({"intercept": "0.25"}), "intercept must be numeric"),
        (
            lambda payload: payload.update({"model_type": " linear-regression "}),
            "model_type must not contain leading or trailing whitespace",
        ),
    ],
)
def test_repository_rejects_artifact_input_that_changes_its_hashed_meaning(
    tmp_path, model_artifact, mutation, message
):
    repository = PartitionRankerRepository(tmp_path)
    path = repository.save(model_artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PartitionContractError, match=message):
        repository.get(model_artifact.model_version)


def test_artifact_rejects_a_feature_order_that_does_not_match_the_schema(model_artifact):
    with pytest.raises(PartitionContractError, match="feature order"):
        replace(model_artifact, feature_order=tuple(reversed(FEATURE_ORDER))).with_computed_hash()


def test_artifact_rejects_non_finite_parameters(model_artifact):
    with pytest.raises(PartitionContractError, match="finite"):
        replace(model_artifact, intercept=float("nan")).with_computed_hash()


def test_artifact_rejects_group_count_that_disagrees_with_training_lineages(model_artifact):
    provenance = {
        **model_artifact.training_provenance,
        "training_lineage_group_hashes": ("1" * 64, "2" * 64, "3" * 64),
    }

    with pytest.raises(PartitionContractError, match="group_count"):
        replace(model_artifact, group_count=2, training_provenance=provenance).with_computed_hash()


def test_artifact_rejects_invalid_eligibility_threshold_semantics(model_artifact):
    provenance = {
        **model_artifact.training_provenance,
        "eligibility_thresholds": {
            **model_artifact.training_provenance["eligibility_thresholds"],
            "maximum_holdout_mae": -0.01,
        },
    }

    with pytest.raises(PartitionContractError, match="maximum_holdout_mae"):
        replace(model_artifact, training_provenance=provenance).with_computed_hash()


def test_artifact_canonicalizes_feature_range_object_order(model_artifact):
    reversed_ranges = {
        name: model_artifact.training_feature_ranges[name]
        for name in reversed(FEATURE_ORDER)
    }

    artifact = replace(model_artifact, training_feature_ranges=reversed_ranges)

    assert artifact.with_computed_hash().to_dict()["training_feature_ranges"] == {
        name: [0.0, 100.0] for name in FEATURE_ORDER
    }


def test_repository_rejects_path_traversal_in_model_version(tmp_path, model_artifact):
    repository = PartitionRankerRepository(tmp_path)

    with pytest.raises(PartitionContractError, match="model_version"):
        repository.save(replace(model_artifact, model_version="../outside"))


def test_repository_lists_verified_artifacts_in_version_order(tmp_path, model_artifact):
    repository = PartitionRankerRepository(tmp_path)
    repository.save(replace(model_artifact, model_version="ranker-b"))
    repository.save(replace(model_artifact, model_version="ranker-a"))

    assert [artifact.model_version for artifact in repository.list()] == [
        "ranker-a",
        "ranker-b",
    ]


def test_repository_rejects_symlinked_model_directory_for_get_save_and_list(
    tmp_path, model_artifact
):
    registry_root = tmp_path / "registry"
    outside_root = tmp_path / "outside"
    external_repository = PartitionRankerRepository(outside_root)
    external_path = external_repository.save(model_artifact)
    external_contents = external_path.read_text(encoding="utf-8")
    linked_version = registry_root / model_artifact.model_version
    registry_root.mkdir()
    _link_directory(linked_version, external_path.parent)

    repository = PartitionRankerRepository(registry_root)

    with pytest.raises(PartitionContractError, match="symlink"):
        repository.get(model_artifact.model_version)
    with pytest.raises(PartitionContractError, match="symlink"):
        repository.save(model_artifact)
    with pytest.raises(PartitionContractError, match="symlink"):
        repository.list()

    assert external_path.read_text(encoding="utf-8") == external_contents


def _link_directory(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory symlinks are unavailable: {symlink_error}")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"directory links are unavailable: {result.stderr.strip()}")
