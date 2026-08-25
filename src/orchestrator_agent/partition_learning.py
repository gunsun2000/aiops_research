from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt
from pathlib import Path
from typing import Any

from orchestrator_agent.partition_common import NormalizedPartitionRequest
from orchestrator_agent.partition_context import WorkloadForecast, canonical_json
from orchestrator_agent.partition_evaluator import ObservedPartitionMetrics
from orchestrator_agent.partition_features import (
    FEATURE_ORDER,
    FEATURE_SCHEMA_VERSION,
    candidate_key,
    extract_partition_features,
)
from orchestrator_agent.partition_models import (
    ApprovedExecutionMode,
    ModelLayer,
    NetworkLink,
    PartitionCandidate,
    PartitionConstraints,
    PartitionContractError,
    PartitionExecutionPlan,
    ResourceDevice,
)
from orchestrator_agent.partition_ranking import RankingContext
from orchestrator_agent.partition_ranker_repository import (
    MODEL_ARTIFACT_SCHEMA_VERSION,
    PartitionRankerModelArtifact,
    PartitionRankerRepository,
)
from orchestrator_agent.partition_repository import PartitionArtifactAuthenticator
from orchestrator_agent.partition_ranking import (
    DEFAULT_LEARNED_RANKER_GUARD_POLICY,
    LearnedRewardRanker,
)
from orchestrator_agent.partition_strategies import PartitionIntent


DATASET_SCHEMA_VERSION = "partition-ranking-dataset-v1"
_DATASET_BUILDER_PROVENANCE = {
    "builder_id": "orchestrator_agent.partition_learning.build_partition_ranking_dataset",
    "contract_version": "partition-ranking-dataset-builder-v1",
}
_OBSERVED_RUNTIME_EVIDENCE_SOURCES = frozenset({"runtime-monitor"})
_DEFAULT_HOLDOUT_TEST_FRACTION = 0.2


@dataclass(frozen=True)
class PartitionRankingTrainingRow:
    row_id: str
    job_id: str
    plan_id: str
    plan_version: int
    candidate_key: str
    input_snapshot_hash: str
    policy_version: str
    strategy_version: str
    feature_schema_version: str
    features: dict[str, float]
    target_reward: float
    reward_components: dict[str, float]
    evidence_level: str
    evidence_source: str
    observed_at: str
    selected_by: str
    selection_probability: float | None
    runtime_outcome_ref: str

    def to_dict(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "job_id": self.job_id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "candidate_key": self.candidate_key,
            "input_snapshot_hash": self.input_snapshot_hash,
            "policy_version": self.policy_version,
            "strategy_version": self.strategy_version,
            "feature_schema_version": self.feature_schema_version,
            "features": dict(self.features),
            "target_reward": self.target_reward,
            "reward_components": dict(self.reward_components),
            "evidence_level": self.evidence_level,
            "evidence_source": self.evidence_source,
            "observed_at": self.observed_at,
            "selected_by": self.selected_by,
            "selection_probability": self.selection_probability,
            "runtime_outcome_ref": self.runtime_outcome_ref,
        }


@dataclass(frozen=True)
class PartitionRankingDatasetSummary:
    scope: str
    row_count: int
    rejections: dict[str, int]
    dataset_hash: str
    unique_job_count: int
    unique_snapshot_count: int
    lineage_group_count: int
    manifest_path: Path


@dataclass(frozen=True)
class PartitionRankingDataset:
    rows: tuple[PartitionRankingTrainingRow, ...]
    path: Path
    manifest_path: Path
    dataset_hash: str
    scope: str
    eligible_for_real_claims: bool


@dataclass(frozen=True)
class PartitionRankingGroupSplit:
    train: tuple[PartitionRankingTrainingRow, ...]
    test: tuple[PartitionRankingTrainingRow, ...]


@dataclass(frozen=True)
class PartitionRankerTrainingSummary:
    model_version: str
    artifact_path: Path
    artifact: PartitionRankerModelArtifact
    validation_metrics: dict[str, float]
    deployment_eligible: bool


@dataclass(frozen=True)
class PartitionRankerEvaluation:
    scope: str
    sample_count: int
    group_count: int
    metrics: dict[str, float]
    deployment_eligible: bool


@dataclass(frozen=True)
class _FeatureNormalizer:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    ranges: dict[str, tuple[float, float]]

    def transform(self, rows: Sequence[PartitionRankingTrainingRow]) -> list[list[float]]:
        return [
            [
                (row.features[name] - mean) / scale
                for name, mean, scale in zip(
                    FEATURE_ORDER, self.mean, self.scale, strict=True
                )
            ]
            for row in rows
        ]


@dataclass(frozen=True)
class _PersistedPartitionReport:
    plan_directory: Path
    report: Mapping[str, Any]
    normalized_request: Mapping[str, Any]
    partition_intent: Mapping[str, Any]
    runtime_outcome_path: Path


@dataclass(frozen=True)
class _ArtifactRejection:
    reason: str


def build_partition_ranking_dataset(
    artifact_roots: Sequence[str | Path],
    output_path: str | Path,
    *,
    scope: str = "observed",
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
) -> PartitionRankingDatasetSummary:
    """Build a deterministic, selected-candidate dataset from committed artifacts only."""
    normalized_scope = _scope(scope)
    authenticator = (
        None
        if normalized_scope != "observed"
        else PartitionArtifactAuthenticator.from_config(
            key=artifact_signing_key,
            key_file=artifact_signing_key_file,
        )
    )
    reports = tuple(iter_partition_reports(artifact_roots))
    rows, rejection_counts, source_artifact_contracts = collect_training_rows(
        reports, scope=normalized_scope, authenticator=authenticator
    )
    ordered_rows = tuple(sorted(rows, key=training_row_sort_key))
    return write_partition_ranking_dataset(
        ordered_rows,
        output_path,
        scope=normalized_scope,
        rejection_counts=rejection_counts,
        artifact_roots=artifact_roots,
        source_artifact_contracts=source_artifact_contracts,
    )


def iter_partition_reports(
    artifact_roots: Sequence[str | Path],
) -> Iterator[_PersistedPartitionReport | _ArtifactRejection]:
    """Yield only complete repository artifacts, retaining rejection reasons for the manifest."""
    seen_roots: set[Path] = set()
    for root in sorted((Path(item).expanduser().resolve() for item in artifact_roots), key=str):
        if root in seen_roots:
            continue
        seen_roots.add(root)
        if not root.is_dir():
            yield _ArtifactRejection("artifact_root_missing")
            continue
        for plan_directory in sorted(root.iterdir(), key=lambda item: item.name):
            if not plan_directory.is_dir() or plan_directory.is_symlink():
                continue
            try:
                yield _read_committed_partition_report(plan_directory)
            except (OSError, ValueError, TypeError, KeyError, PartitionContractError):
                yield _ArtifactRejection("corrupt_or_partial_artifact")


def collect_training_rows(
    reports: Sequence[_PersistedPartitionReport | _ArtifactRejection],
    *,
    scope: str,
    authenticator: PartitionArtifactAuthenticator | None = None,
) -> tuple[tuple[PartitionRankingTrainingRow, ...], Counter[str], tuple[dict[str, object], ...]]:
    rejections: Counter[str] = Counter()
    rows: list[PartitionRankingTrainingRow] = []
    source_artifact_contracts: list[dict[str, object]] = []
    for item in reports:
        if isinstance(item, _ArtifactRejection):
            rejections[item.reason] += 1
            continue
        try:
            row, reasons = _training_row(
                item, scope=scope, authenticator=authenticator
            )
        except (ValueError, TypeError, KeyError, PartitionContractError):
            rejections["corrupt_or_partial_artifact"] += 1
            continue
        rejections.update(reasons)
        if row is not None:
            rows.append(row)
            if scope == "observed":
                source_artifact_contracts.append(_source_artifact_contract(item, row))
    return tuple(rows), rejections, tuple(source_artifact_contracts)


def training_row_sort_key(row: PartitionRankingTrainingRow) -> tuple[str, str, str, int]:
    return (row.job_id, row.input_snapshot_hash, row.plan_id, row.plan_version)


def write_partition_ranking_dataset(
    rows: Sequence[PartitionRankingTrainingRow],
    output_path: str | Path,
    *,
    scope: str,
    rejection_counts: Mapping[str, int],
    artifact_roots: Sequence[str | Path],
    source_artifact_contracts: Sequence[Mapping[str, object]] = (),
) -> PartitionRankingDatasetSummary:
    path = Path(output_path).expanduser().resolve()
    payload = b"".join(
        (canonical_json(row.to_dict()) + "\n").encode("utf-8") for row in rows
    )
    _write_bytes_atomic(path, payload)
    dataset_hash = hashlib.sha256(payload).hexdigest()
    manifest_path = Path(f"{path}.manifest.json")
    normalized_roots = sorted(
        {str(Path(item).expanduser().resolve()) for item in artifact_roots}
    )
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "scope": scope,
        "row_count": len(rows),
        "rejections": dict(sorted(rejection_counts.items())),
        "dataset_sha256": dataset_hash,
        "unique_job_count": len({row.job_id for row in rows}),
        "unique_snapshot_count": len({row.input_snapshot_hash for row in rows}),
        "lineage_group_count": len({group_key(row) for row in rows}),
        "source_roots": normalized_roots,
        "selected_candidates_only": True,
        "eligible_for_real_claims": scope == "observed" and bool(source_artifact_contracts),
    }
    if source_artifact_contracts:
        manifest["builder_provenance"] = dict(_DATASET_BUILDER_PROVENANCE)
        manifest["source_artifact_contracts"] = [
            dict(contract)
            for contract in sorted(source_artifact_contracts, key=lambda item: str(item["row_id"]))
        ]
    _write_bytes_atomic(
        manifest_path, (canonical_json(manifest) + "\n").encode("utf-8")
    )
    return PartitionRankingDatasetSummary(
        scope=scope,
        row_count=len(rows),
        rejections=dict(sorted(rejection_counts.items())),
        dataset_hash=dataset_hash,
        unique_job_count=manifest["unique_job_count"],
        unique_snapshot_count=manifest["unique_snapshot_count"],
        lineage_group_count=manifest["lineage_group_count"],
        manifest_path=manifest_path,
    )


def group_key(row: PartitionRankingTrainingRow) -> str:
    """Return the stable lineage key used to prevent train/test leakage."""
    return hashlib.sha256(
        canonical_json(
            {
                "job_id": row.job_id,
                "input_snapshot_hash": row.input_snapshot_hash,
                "lineage_root": row.runtime_outcome_ref.split("/versions/", 1)[0],
            }
        ).encode("utf-8")
    ).hexdigest()


def group_holdout_split(
    rows: Sequence[PartitionRankingTrainingRow], *, test_fraction: float = 0.2, seed: int = 17
) -> PartitionRankingGroupSplit:
    if isinstance(test_fraction, bool) or not isinstance(test_fraction, (int, float)):
        raise PartitionContractError("invalid_split", "test_fraction must be numeric")
    if not 0.0 < float(test_fraction) < 1.0:
        raise PartitionContractError("invalid_split", "test_fraction must be between 0 and 1")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise PartitionContractError("invalid_split", "seed must be an integer")
    grouped: dict[str, list[PartitionRankingTrainingRow]] = {}
    for row in rows:
        grouped.setdefault(group_key(row), []).append(row)
    if len(grouped) < 2:
        raise PartitionContractError(
            "insufficient_training_data", "at least two independent lineage groups are required"
        )
    group_ids = sorted(grouped)
    random.Random(seed).shuffle(group_ids)
    test_count = min(len(group_ids) - 1, max(1, round(len(group_ids) * float(test_fraction))))
    test_ids = frozenset(group_ids[:test_count])
    train = tuple(row for row in rows if group_key(row) not in test_ids)
    test = tuple(row for row in rows if group_key(row) in test_ids)
    if not train or not test:
        raise PartitionContractError("insufficient_training_data", "group split must retain train and test rows")
    return PartitionRankingGroupSplit(train=train, test=test)


def train_partition_ranker(
    dataset_path: str | Path,
    *,
    registry_root: str | Path,
    model_version: str,
    seed: int = 17,
    alpha: float = 1.0,
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
) -> PartitionRankerTrainingSummary:
    """Fit an offline Ridge reward regressor and export its runtime-safe JSON contract."""
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not isfinite(float(alpha)):
        raise PartitionContractError("invalid_training_parameter", "alpha must be finite and positive")
    if float(alpha) <= 0.0:
        raise PartitionContractError("invalid_training_parameter", "alpha must be finite and positive")
    dataset = load_partition_ranking_dataset(
        dataset_path,
        artifact_signing_key=artifact_signing_key,
        artifact_signing_key_file=artifact_signing_key_file,
    )
    split = group_holdout_split(
        dataset.rows, test_fraction=_DEFAULT_HOLDOUT_TEST_FRACTION, seed=seed
    )
    normalizer = fit_feature_normalizer(split.train)
    try:
        from sklearn.linear_model import Ridge
    except ImportError as exc:
        raise PartitionContractError(
            "ml_dependency_missing",
            "scikit-learn is required only for training; install aiops-k8s-agents[ml]",
        ) from exc
    model = Ridge(alpha=float(alpha)).fit(
        normalizer.transform(split.train), [row.target_reward for row in split.train]
    )
    coefficients = tuple(float(value) for value in model.coef_)
    intercept = float(model.intercept_)
    predictions = _linear_predictions(split.test, normalizer, coefficients, intercept)
    metrics = _evaluation_metrics(split.test, predictions)
    deployment_eligible = dataset.eligible_for_real_claims and _quality_eligible(
        dataset.scope, dataset.rows, metrics
    )
    metrics.update(
        {
            "quality_eligible": float(deployment_eligible),
            "deployment_eligible": float(deployment_eligible),
        }
    )
    artifact = PartitionRankerModelArtifact(
        schema_version=MODEL_ARTIFACT_SCHEMA_VERSION,
        model_type="ridge_reward_regressor",
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        trained_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        training_dataset_hash=dataset.dataset_hash,
        training_scope=dataset.scope,
        sample_count=len(dataset.rows),
        group_count=len({group_key(row) for row in dataset.rows}),
        feature_order=FEATURE_ORDER,
        feature_mean=normalizer.mean,
        feature_scale=normalizer.scale,
        coefficients=coefficients,
        intercept=intercept,
        training_feature_ranges=normalizer.ranges,
        validation_metrics=metrics,
        confidence_policy={"base_confidence": 0.95 if deployment_eligible else 0.0},
        training_provenance={
            "seed": seed,
            "ridge_alpha": float(alpha),
            "holdout_test_fraction": _DEFAULT_HOLDOUT_TEST_FRACTION,
            "eligibility_thresholds": _eligibility_thresholds(),
            "training_lineage_group_hashes": sorted(
                {group_key(row) for row in dataset.rows}
            ),
        },
        artifact_hash="",
    ).with_computed_hash()
    artifact_path = PartitionRankerRepository(registry_root).save(artifact)
    return PartitionRankerTrainingSummary(
        model_version=artifact.model_version,
        artifact_path=artifact_path,
        artifact=artifact,
        validation_metrics=metrics,
        deployment_eligible=deployment_eligible,
    )


def evaluate_partition_ranker(
    dataset_path: str | Path,
    artifact: PartitionRankerModelArtifact,
    *,
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
) -> PartitionRankerEvaluation:
    """Evaluate one dataset scope with pure-Python inference; scopes are never aggregated."""
    artifact.verify_hash()
    if artifact.model_type != "ridge_reward_regressor":
        raise PartitionContractError("invalid_model_artifact", "artifact must be a ridge reward regressor")
    dataset = load_partition_ranking_dataset(
        dataset_path,
        artifact_signing_key=artifact_signing_key,
        artifact_signing_key_file=artifact_signing_key_file,
    )
    training_lineages = frozenset(
        artifact.training_provenance["training_lineage_group_hashes"]
    )
    evaluation_lineages = frozenset(group_key(row) for row in dataset.rows)
    if (
        dataset.dataset_hash == artifact.training_dataset_hash
        or training_lineages.intersection(evaluation_lineages)
    ):
        raise PartitionContractError(
            "evaluation_dataset_not_independent",
            "evaluation dataset must not reuse the training dataset or its lineage groups",
        )
    ranker = LearnedRewardRanker(artifact)
    predictions = [ranker.predict(row.features)[0] for row in dataset.rows]
    metrics = _evaluation_metrics(dataset.rows, predictions)
    deployment_eligible = (
        dataset.scope == "observed"
        and dataset.eligible_for_real_claims
        and artifact.training_scope == "observed"
        and artifact.validation_metrics.get("deployment_eligible") == 1.0
    )
    metrics["deployment_eligible"] = float(deployment_eligible)
    return PartitionRankerEvaluation(
        scope=dataset.scope,
        sample_count=len(dataset.rows),
        group_count=len({group_key(row) for row in dataset.rows}),
        metrics=metrics,
        deployment_eligible=deployment_eligible,
    )


def load_partition_ranking_dataset(
    dataset_path: str | Path,
    *,
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
) -> PartitionRankingDataset:
    path = Path(dataset_path).expanduser().resolve()
    manifest_path = Path(f"{path}.manifest.json")
    try:
        payload = path.read_bytes()
        manifest = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PartitionContractError(
            "invalid_dataset_manifest", "dataset and manifest must be readable JSON artifacts"
        ) from exc
    digest = hashlib.sha256(payload).hexdigest()
    _validate_dataset_manifest(manifest, digest)
    authenticator = (
        None
        if not (
            manifest.get("scope") == "observed"
            and manifest.get("eligible_for_real_claims") is True
        )
        else PartitionArtifactAuthenticator.from_config(
            key=artifact_signing_key,
            key_file=artifact_signing_key_file,
        )
    )
    try:
        rows = tuple(
            _training_row_from_dict(json.loads(line), index)
            for index, line in enumerate(payload.decode("utf-8").splitlines(), start=1)
            if line.strip()
        )
    except PartitionContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_dataset_row", "dataset JSONL contains an invalid training row"
        ) from exc
    if not rows:
        raise PartitionContractError("insufficient_training_data", "dataset must contain training rows")
    _validate_dataset_rows(rows, manifest, authenticator=authenticator)
    return PartitionRankingDataset(
        rows=rows,
        path=path,
        manifest_path=manifest_path,
        dataset_hash=digest,
        scope=str(manifest["scope"]),
        eligible_for_real_claims=manifest["eligible_for_real_claims"],
    )


def fit_feature_normalizer(rows: Sequence[PartitionRankingTrainingRow]) -> _FeatureNormalizer:
    if not rows:
        raise PartitionContractError("insufficient_training_data", "training split must not be empty")
    means: list[float] = []
    scales: list[float] = []
    ranges: dict[str, tuple[float, float]] = {}
    for name in FEATURE_ORDER:
        values = [row.features[name] for row in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        scales.append(sqrt(variance) if variance > 0.0 else 1.0)
        ranges[name] = (min(values), max(values))
    return _FeatureNormalizer(tuple(means), tuple(scales), ranges)


def _validate_dataset_manifest(manifest: Mapping[str, Any], digest: str) -> None:
    if manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise PartitionContractError("dataset_schema_mismatch", "dataset manifest schema is unsupported")
    scope = manifest.get("scope")
    if scope not in {"observed", "predicted", "synthetic"}:
        raise PartitionContractError("dataset_scope_mismatch", "dataset scope is unsupported")
    if manifest.get("dataset_sha256") != digest:
        raise PartitionContractError("dataset_hash_mismatch", "dataset hash does not match manifest")
    if manifest.get("selected_candidates_only") is not True:
        raise PartitionContractError(
            "invalid_dataset_manifest", "dataset must contain selected candidates only"
        )
    if not isinstance(manifest.get("eligible_for_real_claims"), bool):
        raise PartitionContractError("invalid_dataset_manifest", "real-claim eligibility must be boolean")
    if manifest["eligible_for_real_claims"] and scope != "observed":
        raise PartitionContractError(
            "dataset_scope_mismatch", "only observed datasets can claim real eligibility"
        )


def _training_row_from_dict(payload: object, index: int) -> PartitionRankingTrainingRow:
    fields = _mapping(payload, f"dataset row {index}")
    try:
        features = _finite_mapping(fields.get("features"), f"dataset row {index}.features")
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "nonfinite_features", "dataset feature values must be finite"
        ) from exc
    return PartitionRankingTrainingRow(
        row_id=_text(fields.get("row_id"), "row_id"),
        job_id=_text(fields.get("job_id"), "job_id"),
        plan_id=_text(fields.get("plan_id"), "plan_id"),
        plan_version=_positive_int(fields.get("plan_version"), "plan_version"),
        candidate_key=_text(fields.get("candidate_key"), "candidate_key"),
        input_snapshot_hash=_text(fields.get("input_snapshot_hash"), "input_snapshot_hash"),
        policy_version=_text(fields.get("policy_version"), "policy_version"),
        strategy_version=_text(fields.get("strategy_version"), "strategy_version"),
        feature_schema_version=_text(fields.get("feature_schema_version"), "feature_schema_version"),
        features=features,
        target_reward=_finite_number(fields.get("target_reward"), "target_reward"),
        reward_components=_finite_mapping(fields.get("reward_components"), "reward_components"),
        evidence_level=_text(fields.get("evidence_level"), "evidence_level"),
        evidence_source=_text(fields.get("evidence_source"), "evidence_source"),
        observed_at=_validated_observed_at(fields.get("observed_at")),
        selected_by=_text(fields.get("selected_by"), "selected_by"),
        selection_probability=(
            None
            if fields.get("selection_probability") is None
            else _finite_number(fields.get("selection_probability"), "selection_probability")
        ),
        runtime_outcome_ref=_text(fields.get("runtime_outcome_ref"), "runtime_outcome_ref"),
    )


def _validate_dataset_rows(
    rows: Sequence[PartitionRankingTrainingRow],
    manifest: Mapping[str, Any],
    *,
    authenticator: PartitionArtifactAuthenticator | None,
) -> None:
    expected_row_count = manifest.get("row_count")
    if expected_row_count != len(rows):
        raise PartitionContractError("invalid_dataset_manifest", "manifest row count does not match JSONL")
    scope = str(manifest["scope"])
    for row in rows:
        if row.feature_schema_version != FEATURE_SCHEMA_VERSION or set(row.features) != set(FEATURE_ORDER):
            raise PartitionContractError(
                "feature_schema_mismatch", "dataset row features do not match partition-feature-v1"
            )
        if not -1.0 <= row.target_reward <= 1.0:
            raise PartitionContractError("invalid_dataset_row", "target reward must be between -1 and 1")
        if scope == "observed":
            if (
                row.evidence_level != "observed"
                or not row.observed_at.strip()
                or not _is_observed_runtime_source(row.evidence_source)
                or not row.runtime_outcome_ref.strip()
            ):
                raise PartitionContractError(
                    "dataset_scope_mismatch", "observed dataset requires runtime observed evidence"
                )
        elif row.evidence_level == "observed":
            raise PartitionContractError(
                "dataset_scope_mismatch", "non-observed datasets must not contain observed rows"
            )
    if manifest["eligible_for_real_claims"]:
        if authenticator is None:
            raise PartitionContractError(
                "artifact_signing_key_required",
                "observed real-claim datasets require an external signing key",
            )
        _validate_observed_source_contract(rows, manifest, authenticator)
    counts = {
        "unique_job_count": len({row.job_id for row in rows}),
        "unique_snapshot_count": len({row.input_snapshot_hash for row in rows}),
        "lineage_group_count": len({group_key(row) for row in rows}),
    }
    for name, actual in counts.items():
        if manifest.get(name) != actual:
            raise PartitionContractError(
                "invalid_dataset_manifest", f"manifest {name} does not match JSONL"
            )


def _linear_predictions(
    rows: Sequence[PartitionRankingTrainingRow],
    normalizer: _FeatureNormalizer,
    coefficients: Sequence[float],
    intercept: float,
) -> list[float]:
    return [
        max(-1.0, min(1.0, intercept + sum(
            coefficient * value
            for coefficient, value in zip(coefficients, vector, strict=True)
        )))
        for vector in normalizer.transform(rows)
    ]


def _evaluation_metrics(
    rows: Sequence[PartitionRankingTrainingRow], predictions: Sequence[float]
) -> dict[str, float]:
    if len(rows) != len(predictions) or not rows:
        raise PartitionContractError("invalid_evaluation", "evaluation requires one finite prediction per row")
    actual = [row.target_reward for row in rows]
    predicted = [float(value) for value in predictions]
    if not all(isfinite(value) for value in predicted):
        raise PartitionContractError("invalid_evaluation", "evaluation predictions must be finite")
    errors = [abs(expected - value) for expected, value in zip(actual, predicted, strict=True)]
    selection = _candidate_selection_metrics(rows, predicted)
    return {
        "holdout_mae": sum(errors) / len(errors),
        "mae": sum(errors) / len(errors),
        "rmse": sqrt(sum(error * error for error in errors) / len(errors)),
        "spearman_correlation": _spearman(actual, predicted),
        **selection,
    }


def _candidate_selection_metrics(
    rows: Sequence[PartitionRankingTrainingRow], predictions: Sequence[float]
) -> dict[str, float]:
    groups: dict[str, list[tuple[PartitionRankingTrainingRow, float]]] = {}
    for row, prediction in zip(rows, predictions, strict=True):
        groups.setdefault(group_key(row), []).append((row, prediction))
    comparable = [group for group in groups.values() if len(group) >= 2]
    if not comparable:
        return {
            "candidate_selection_agreement": 0.0,
            "candidate_selection_agreement_available": 0.0,
            "learned_regret": 0.0,
            "learned_regret_available": 0.0,
            "baseline_regret": 0.0,
            "baseline_regret_available": 0.0,
            "ranking_group_count": 0.0,
        }
    agreement = 0
    learned_regrets: list[float] = []
    regrets: list[float] = []
    for group in comparable:
        learned = max(group, key=lambda item: (item[1], item[0].candidate_key))[0]
        reward_best = max(
            group, key=lambda item: (item[0].target_reward, item[0].candidate_key)
        )[0]
        baseline = min(
            group,
            key=lambda item: (item[0].features["baseline_score"], item[0].candidate_key),
        )[0]
        agreement += learned.candidate_key == reward_best.candidate_key
        learned_regrets.append(reward_best.target_reward - learned.target_reward)
        regrets.append(reward_best.target_reward - baseline.target_reward)
    return {
        "candidate_selection_agreement": agreement / len(comparable),
        "candidate_selection_agreement_available": 1.0,
        "learned_regret": sum(learned_regrets) / len(learned_regrets),
        "learned_regret_available": 1.0,
        "baseline_regret": sum(regrets) / len(regrets),
        "baseline_regret_available": 1.0,
        "ranking_group_count": float(len(comparable)),
    }


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) < 2:
        return 0.0
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    left_mean = sum(left_ranks) / len(left_ranks)
    right_mean = sum(right_ranks) / len(right_ranks)
    covariance = sum(
        (first - left_mean) * (second - right_mean)
        for first, second in zip(left_ranks, right_ranks, strict=True)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left_ranks)
    right_variance = sum((value - right_mean) ** 2 for value in right_ranks)
    if left_variance == 0.0 or right_variance == 0.0:
        return 0.0
    return covariance / sqrt(left_variance * right_variance)


def _average_ranks(values: Sequence[float]) -> list[float]:
    ranked = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    start = 0
    while start < len(ranked):
        end = start + 1
        while end < len(ranked) and ranked[end][1] == ranked[start][1]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for index, _ in ranked[start:end]:
            result[index] = rank
        start = end
    return result


def _quality_eligible(
    scope: str, rows: Sequence[PartitionRankingTrainingRow], metrics: Mapping[str, float]
) -> bool:
    policy = DEFAULT_LEARNED_RANKER_GUARD_POLICY
    return (
        scope == "observed"
        and len(rows) >= policy.minimum_observed_samples
        and len({group_key(row) for row in rows}) >= policy.minimum_independent_groups
        and metrics["holdout_mae"] <= policy.maximum_holdout_mae
        and metrics["spearman_correlation"] >= policy.minimum_spearman_correlation
    )


def _eligibility_thresholds() -> dict[str, float | int]:
    policy = DEFAULT_LEARNED_RANKER_GUARD_POLICY
    return {
        "minimum_observed_samples": policy.minimum_observed_samples,
        "minimum_independent_groups": policy.minimum_independent_groups,
        "maximum_holdout_mae": policy.maximum_holdout_mae,
        "minimum_spearman_correlation": policy.minimum_spearman_correlation,
        "minimum_selection_confidence": policy.minimum_selection_confidence,
        "maximum_ood_feature_ratio": policy.maximum_ood_feature_ratio,
    }


def _read_committed_partition_report(plan_directory: Path) -> _PersistedPartitionReport:
    commit_path = plan_directory / "commit.json"
    if commit_path.is_file() and (plan_directory / "pending.json").exists():
        raise ValueError("artifact has both committed and pending markers")
    commit = _read_json(commit_path)
    if commit.get("committed") is not True:
        raise ValueError("artifact is not committed")
    latest = _read_json(plan_directory / "latest.json")
    latest_plan = _mapping(latest.get("plan"), "latest.plan")
    plan_id = _text(latest_plan.get("plan_id"), "latest.plan.plan_id")
    plan_version = _positive_int(latest_plan.get("plan_version"), "latest.plan.plan_version")
    if plan_id != plan_directory.name:
        raise ValueError("directory does not match latest plan")
    version_directory = plan_directory / "versions" / str(plan_version)
    report = _read_json(version_directory / "report.json")
    if report != latest:
        raise ValueError("latest report does not match committed version")
    return _PersistedPartitionReport(
        plan_directory=plan_directory,
        report=report,
        normalized_request=_read_json(version_directory / "normalized_request.json"),
        partition_intent=_read_json(version_directory / "partition_intent.json"),
        runtime_outcome_path=version_directory / "runtime_outcome.json",
    )


def _source_artifact_contract(
    artifact: _PersistedPartitionReport, row: PartitionRankingTrainingRow
) -> dict[str, object]:
    return {
        "row_id": row.row_id,
        "source_root": str(artifact.plan_directory.parent.resolve()),
        "plan_id": row.plan_id,
        "plan_version": row.plan_version,
        "runtime_outcome_ref": row.runtime_outcome_ref,
        "artifact_sha256": _source_artifact_hash(artifact.plan_directory, row.plan_version),
    }


def _source_artifact_hash(plan_directory: Path, plan_version: int) -> str:
    version_directory = plan_directory / "versions" / str(plan_version)
    files = {
        "commit.json": plan_directory / "commit.json",
        "latest.json": plan_directory / "latest.json",
        "versions/report.json": version_directory / "report.json",
        "versions/normalized_request.json": version_directory / "normalized_request.json",
        "versions/partition_intent.json": version_directory / "partition_intent.json",
    }
    runtime_outcome = version_directory / "runtime_outcome.json"
    if runtime_outcome.is_file():
        files["versions/runtime_outcome.json"] = runtime_outcome
    authenticated_manifest = version_directory / "authenticated_manifest.json"
    if authenticated_manifest.is_file():
        files["versions/authenticated_manifest.json"] = authenticated_manifest
    payload = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in files.items()
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_observed_source_contract(
    rows: Sequence[PartitionRankingTrainingRow],
    manifest: Mapping[str, Any],
    authenticator: PartitionArtifactAuthenticator,
) -> None:
    if manifest.get("builder_provenance") != _DATASET_BUILDER_PROVENANCE:
        raise PartitionContractError(
            "dataset_source_mismatch", "observed real-claim datasets require the registered builder provenance"
        )
    contracts = manifest.get("source_artifact_contracts")
    if isinstance(contracts, (str, bytes)) or not isinstance(contracts, Sequence):
        raise PartitionContractError(
            "dataset_source_mismatch", "observed real-claim datasets require source artifact contracts"
        )
    row_by_id = {row.row_id: row for row in rows}
    if len(row_by_id) != len(rows) or len(contracts) != len(rows):
        raise PartitionContractError(
            "dataset_source_mismatch", "source artifact contracts must bind each observed row exactly once"
        )
    manifest_roots = set(manifest.get("source_roots", ()))
    seen_rows: set[str] = set()
    for contract_payload in contracts:
        contract = _mapping(contract_payload, "source artifact contract")
        expected_fields = {
            "row_id", "source_root", "plan_id", "plan_version", "runtime_outcome_ref", "artifact_sha256"
        }
        if set(contract) != expected_fields:
            raise PartitionContractError("dataset_source_mismatch", "source artifact contract fields are unsupported")
        row_id = _text(contract.get("row_id"), "source artifact contract.row_id")
        row = row_by_id.get(row_id)
        source_root = Path(_text(contract.get("source_root"), "source artifact contract.source_root")).expanduser().resolve()
        plan_id = _text(contract.get("plan_id"), "source artifact contract.plan_id")
        plan_version = _positive_int(contract.get("plan_version"), "source artifact contract.plan_version")
        outcome_ref = _text(contract.get("runtime_outcome_ref"), "source artifact contract.runtime_outcome_ref")
        artifact_hash = _text(contract.get("artifact_sha256"), "source artifact contract.artifact_sha256")
        if (
            row is None
            or row_id in seen_rows
            or str(source_root) not in manifest_roots
            or row.plan_id != plan_id
            or row.plan_version != plan_version
            or row.runtime_outcome_ref != outcome_ref
            or not _is_sha256_hex(artifact_hash)
        ):
            raise PartitionContractError("dataset_source_mismatch", "source artifact contract does not bind the dataset row")
        try:
            plan_directory = (source_root / plan_id).resolve()
            plan_directory.relative_to(source_root)
            artifact = _read_committed_partition_report(plan_directory)
            source_row, _ = _training_row(
                artifact, scope="observed", authenticator=authenticator
            )
            if (
                source_row is None
                or source_row.to_dict() != row.to_dict()
                or _source_artifact_hash(plan_directory, plan_version) != artifact_hash
            ):
                raise ValueError("source artifact differs from the recorded contract")
        except (OSError, ValueError, TypeError, KeyError, PartitionContractError) as exc:
            raise PartitionContractError(
                "dataset_source_mismatch", "source artifact does not verify the observed dataset row"
            ) from exc
        seen_rows.add(row_id)


def _validated_observed_at(value: object) -> str:
    if value is None or value == "":
        return ""
    text = _text(value, "observed_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PartitionContractError("invalid_dataset_row", "observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise PartitionContractError("invalid_dataset_row", "observed_at must include a timezone")
    return text


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _training_row(
    artifact: _PersistedPartitionReport,
    *,
    scope: str,
    authenticator: PartitionArtifactAuthenticator | None = None,
) -> tuple[PartitionRankingTrainingRow | None, Counter[str]]:
    rejections: Counter[str] = Counter()
    report = artifact.report
    if report.get("status") != "planned":
        return None, Counter({"unplanned_report": 1})
    plan = PartitionExecutionPlan.from_dict(_mapping(report.get("plan"), "plan"))
    if not plan.valid or plan.selected_candidate is None:
        return None, Counter({"unselected_candidate": 1})
    rejections["unselected_candidate"] += len(plan.alternative_candidates)
    if plan.selection is None or plan.selection.final_selected_candidate_key is None:
        return None, _with_rejection(rejections, "missing_selection_provenance")
    if plan.selection.feature_schema_version != FEATURE_SCHEMA_VERSION:
        return None, _with_rejection(rejections, "feature_schema_mismatch")
    selected_key = candidate_key(plan.selected_candidate, plan.strategy_version)
    if selected_key != plan.selection.final_selected_candidate_key:
        return None, _with_rejection(rejections, "selected_candidate_key_mismatch")
    validation = _mapping(report.get("validation"), "validation")
    if validation.get("valid") is not True:
        return None, _with_rejection(rejections, "independent_validation_failed")

    evaluation = _mapping(report.get("evaluation"), "evaluation")
    evidence_level = _text(evaluation.get("evidence_level"), "evaluation.evidence_level")
    if scope == "observed" and evidence_level != "observed":
        return None, _with_rejection(
            rejections,
            "predicted_evidence" if evidence_level == "predicted" else "non_observed_evidence",
        )
    if scope == "observed" and evaluation.get("estimated") is not False:
        return None, _with_rejection(rejections, "estimated_evidence")
    if scope == "observed" and (
        authenticator is None
        or not authenticator.verifies_version(
            artifact.runtime_outcome_path.parent,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
        )
    ):
        return None, _with_rejection(rejections, "authenticated_manifest_mismatch")

    reward = _finite_number(evaluation.get("reward"), "evaluation.reward")
    if not -1.0 <= reward <= 1.0:
        return None, _with_rejection(rejections, "reward_out_of_bounds")
    components = _finite_mapping(evaluation.get("components"), "evaluation.components")
    metrics = _mapping(evaluation.get("metrics"), "evaluation.metrics")
    source = _optional_text(metrics.get("source"))
    observed_at = _optional_text(metrics.get("observed_at"))
    runtime_outcome_ref = _optional_text(metrics.get("runtime_outcome_ref"))
    if scope == "observed" and (
        source is None or observed_at is None or runtime_outcome_ref is None
    ):
        return None, _with_rejection(rejections, "missing_observed_provenance")
    if scope == "observed" and not _is_observed_runtime_source(source):
        return None, _with_rejection(rejections, "non_runtime_evidence_source")
    if evidence_level == "observed":
        ObservedPartitionMetrics.from_dict(metrics)
    if scope == "observed" and not _runtime_outcome_matches_report(
        artifact, plan, evaluation
    ):
        return None, _with_rejection(rejections, "runtime_outcome_mismatch")

    context = RankingContext(
        request=_normalized_request(artifact.normalized_request),
        intent=_partition_intent(artifact.partition_intent),
        strategy_version=plan.strategy_version,
    )
    if context.intent.strategy_version != plan.strategy_version:
        return None, _with_rejection(rejections, "strategy_version_mismatch")
    features = extract_partition_features(context, plan.selected_candidate)
    if not all(isfinite(value) for value in features.values()):
        return None, _with_rejection(rejections, "nonfinite_features")
    source_text = source or "non_observed"
    observed_at_text = observed_at or ""
    runtime_outcome_ref = runtime_outcome_ref or (
        f"{plan.plan_id}:{plan.plan_version}:evaluation"
    )
    row_id = hashlib.sha256(
        canonical_json(
            {
                "job_id": plan.job_id,
                "plan_id": plan.plan_id,
                "plan_version": plan.plan_version,
                "candidate_key": selected_key,
                "input_snapshot_hash": plan.input_snapshot_hash,
                "policy_version": plan.policy_version,
                "strategy_version": plan.strategy_version,
                "evidence_source": source_text,
                "observed_at": observed_at_text,
            }
        ).encode("utf-8")
    ).hexdigest()
    return (
        PartitionRankingTrainingRow(
            row_id=row_id,
            job_id=plan.job_id,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            candidate_key=selected_key,
            input_snapshot_hash=plan.input_snapshot_hash,
            policy_version=plan.policy_version,
            strategy_version=plan.strategy_version,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            features=features,
            target_reward=reward,
            reward_components=components,
            evidence_level=evidence_level,
            evidence_source=source_text,
            observed_at=observed_at_text,
            selected_by=plan.selection.active_ranker_id,
            selection_probability=None,
            runtime_outcome_ref=runtime_outcome_ref,
        ),
        rejections,
    )


def _runtime_outcome_matches_report(
    artifact: _PersistedPartitionReport,
    plan: PartitionExecutionPlan,
    evaluation: Mapping[str, Any],
) -> bool:
    try:
        outcome = _read_json(artifact.runtime_outcome_path)
        payload_sha256 = _text(outcome.pop("payload_sha256"), "runtime outcome payload_sha256")
        if not _is_sha256_hex(payload_sha256) or hashlib.sha256(
            canonical_json(outcome).encode("utf-8")
        ).hexdigest() != payload_sha256:
            return False
        selection = plan.selection
        metrics = _mapping(evaluation.get("metrics"), "evaluation.metrics")
        components = _mapping(evaluation.get("components"), "evaluation.components")
        return outcome == {
            "schema_version": "partition-runtime-outcome-v1",
            "plan_id": plan.plan_id,
            "plan_version": plan.plan_version,
            "selected_candidate_key": selection.final_selected_candidate_key,
            "source": metrics.get("source"),
            "observed_at": metrics.get("observed_at"),
            "runtime_outcome_ref": metrics.get("runtime_outcome_ref"),
            "metrics": dict(metrics),
            "evaluation_reward": evaluation.get("reward"),
            "evaluation_components": dict(components),
        }
    except (OSError, ValueError, TypeError, KeyError, PartitionContractError):
        return False


def _normalized_request(payload: Mapping[str, Any]) -> NormalizedPartitionRequest:
    forecast_payload = payload.get("workload_forecast")
    forecast = (
        None
        if forecast_payload is None
        else WorkloadForecast.from_dict(_mapping(forecast_payload, "workload_forecast"))
    )
    forecast_available = payload.get("workload_forecast_available") is True
    if forecast_available != (forecast is not None):
        raise ValueError("workload forecast sidecar is inconsistent")
    return NormalizedPartitionRequest(
        plan_type=_text(payload.get("plan_type"), "normalized_request.plan_type"),
        job_id=_text(payload.get("job_id"), "normalized_request.job_id"),
        model_id=_text(payload.get("model_id"), "normalized_request.model_id"),
        approved_model_version=_text(
            payload.get("approved_model_version"), "normalized_request.approved_model_version"
        ),
        approved_execution_mode=ApprovedExecutionMode.from_dict(
            _mapping(payload.get("approved_execution_mode"), "approved_execution_mode")
        ),
        participants=_text_tuple(payload.get("participants"), "participants"),
        layers=tuple(
            ModelLayer.from_dict(_mapping(item, "layers[]"))
            for item in _sequence(payload.get("layers"), "layers")
        ),
        devices=tuple(
            ResourceDevice.from_dict(_mapping(item, "devices[]"))
            for item in _sequence(payload.get("devices"), "devices")
        ),
        network_links=tuple(
            NetworkLink.from_dict(_mapping(item, "network_links[]"))
            for item in _sequence(payload.get("network_links"), "network_links")
        ),
        constraints=PartitionConstraints.from_dict(
            _mapping(payload.get("constraints"), "constraints")
        ),
        context_snapshot_id=_text(
            payload.get("context_snapshot_id"), "normalized_request.context_snapshot_id"
        ),
        context_snapshot_hash=_text(
            payload.get("context_snapshot_hash"), "normalized_request.context_snapshot_hash"
        ),
        input_signature=_text(payload.get("input_signature"), "normalized_request.input_signature"),
        legacy_input=payload.get("legacy_input") is True,
        workload_forecast_available=forecast_available,
        workload_forecast=forecast,
    )


def _partition_intent(payload: Mapping[str, Any]) -> PartitionIntent:
    return PartitionIntent(
        strategy_id=_text(payload.get("strategy_id"), "partition_intent.strategy_id"),
        strategy_version=_text(
            payload.get("strategy_version"), "partition_intent.strategy_version"
        ),
        allowed_partition_methods=_text_tuple(
            payload.get("allowed_partition_methods"), "allowed_partition_methods"
        ),
        allowed_split_boundaries=_int_tuple(
            payload.get("allowed_split_boundaries"), "allowed_split_boundaries"
        ),
        forbidden_split_boundaries=_int_tuple(
            payload.get("forbidden_split_boundaries"), "forbidden_split_boundaries"
        ),
        graph_requirements=_text_tuple(payload.get("graph_requirements"), "graph_requirements"),
        memory_rules=_text_tuple(payload.get("memory_rules"), "memory_rules"),
        communication_rules=_text_tuple(
            payload.get("communication_rules"), "communication_rules"
        ),
        optimization_objectives=_text_tuple(
            payload.get("optimization_objectives"), "optimization_objectives"
        ),
        assumptions=_text_tuple(payload.get("assumptions"), "assumptions"),
        warnings=_text_tuple(payload.get("warnings", []), "warnings"),
        objective_weights=tuple(
            (_text(item[0], "objective_weights[].name"), _finite_number(item[1], "objective_weights[].value"))
            for item in _sequence(payload.get("objective_weights", []), "objective_weights")
            if isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) == 2
        ),
    )


def _scope(value: str) -> str:
    scope = _text(value, "scope")
    return scope


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return _mapping(json.load(handle), str(path))


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an array")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{field}[]") for item in _sequence(value, field))


def _int_tuple(value: object, field: str) -> tuple[int, ...]:
    return tuple(_positive_int(item, f"{field}[]", minimum=0) for item in _sequence(value, field))


def _positive_int(value: object, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    return value


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _finite_mapping(value: object, field: str) -> dict[str, float]:
    mapping = _mapping(value, field)
    return {str(key): _finite_number(item, f"{field}.{key}") for key, item in mapping.items()}


def _is_observed_runtime_source(source: str | None) -> bool:
    return source is not None and source.casefold() in _OBSERVED_RUNTIME_EVIDENCE_SOURCES


def _with_rejection(rejections: Counter[str], reason: str) -> Counter[str]:
    rejections[reason] += 1
    return rejections

