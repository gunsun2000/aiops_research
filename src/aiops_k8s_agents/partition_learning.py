from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from aiops_k8s_agents.partition_common import NormalizedPartitionRequest
from aiops_k8s_agents.partition_context import WorkloadForecast, canonical_json
from aiops_k8s_agents.partition_features import (
    FEATURE_SCHEMA_VERSION,
    candidate_key,
    extract_partition_features,
)
from aiops_k8s_agents.partition_models import (
    ApprovedExecutionMode,
    ModelLayer,
    NetworkLink,
    PartitionCandidate,
    PartitionConstraints,
    PartitionContractError,
    PartitionExecutionPlan,
    ResourceDevice,
)
from aiops_k8s_agents.partition_ranking import RankingContext
from aiops_k8s_agents.partition_strategies import PartitionIntent


DATASET_SCHEMA_VERSION = "partition-ranking-dataset-v1"
_NON_RUNTIME_SOURCE_MARKERS = ("mock", "dry-run", "dry_run", "synthetic", "predicted")


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
class _PersistedPartitionReport:
    report: Mapping[str, Any]
    normalized_request: Mapping[str, Any]
    partition_intent: Mapping[str, Any]


@dataclass(frozen=True)
class _ArtifactRejection:
    reason: str


def build_partition_ranking_dataset(
    artifact_roots: Sequence[str | Path],
    output_path: str | Path,
    *,
    scope: str = "observed",
) -> PartitionRankingDatasetSummary:
    """Build a deterministic, selected-candidate dataset from committed artifacts only."""
    normalized_scope = _scope(scope)
    reports = tuple(iter_partition_reports(artifact_roots))
    rows, rejection_counts = collect_training_rows(reports, scope=normalized_scope)
    ordered_rows = tuple(sorted(rows, key=training_row_sort_key))
    return write_partition_ranking_dataset(
        ordered_rows,
        output_path,
        scope=normalized_scope,
        rejection_counts=rejection_counts,
        artifact_roots=artifact_roots,
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
    reports: Sequence[_PersistedPartitionReport | _ArtifactRejection], *, scope: str
) -> tuple[tuple[PartitionRankingTrainingRow, ...], Counter[str]]:
    rejections: Counter[str] = Counter()
    rows: list[PartitionRankingTrainingRow] = []
    for item in reports:
        if isinstance(item, _ArtifactRejection):
            rejections[item.reason] += 1
            continue
        try:
            row, reasons = _training_row(item, scope=scope)
        except (ValueError, TypeError, KeyError, PartitionContractError):
            rejections["corrupt_or_partial_artifact"] += 1
            continue
        rejections.update(reasons)
        if row is not None:
            rows.append(row)
    return tuple(rows), rejections


def training_row_sort_key(row: PartitionRankingTrainingRow) -> tuple[str, str, str, int]:
    return (row.job_id, row.input_snapshot_hash, row.plan_id, row.plan_version)


def write_partition_ranking_dataset(
    rows: Sequence[PartitionRankingTrainingRow],
    output_path: str | Path,
    *,
    scope: str,
    rejection_counts: Mapping[str, int],
    artifact_roots: Sequence[str | Path],
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
        "lineage_group_count": len(
            {(row.job_id, row.input_snapshot_hash) for row in rows}
        ),
        "source_roots": normalized_roots,
        "selected_candidates_only": True,
        "eligible_for_real_claims": scope == "observed",
    }
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


def _read_committed_partition_report(plan_directory: Path) -> _PersistedPartitionReport:
    commit = _read_json(plan_directory / "commit.json")
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
        report=report,
        normalized_request=_read_json(version_directory / "normalized_request.json"),
        partition_intent=_read_json(version_directory / "partition_intent.json"),
    )


def _training_row(
    artifact: _PersistedPartitionReport, *, scope: str
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

    reward = _finite_number(evaluation.get("reward"), "evaluation.reward")
    if not -1.0 <= reward <= 1.0:
        return None, _with_rejection(rejections, "reward_out_of_bounds")
    components = _finite_mapping(evaluation.get("components"), "evaluation.components")
    metrics = _mapping(evaluation.get("metrics"), "evaluation.metrics")
    source = _optional_text(metrics.get("source"))
    observed_at = _optional_text(metrics.get("observed_at"))
    if scope == "observed" and (source is None or observed_at is None):
        return None, _with_rejection(rejections, "missing_observed_provenance")
    if scope == "observed" and _non_runtime_source(source):
        return None, _with_rejection(rejections, "non_runtime_evidence_source")

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
    runtime_outcome_ref = _optional_text(metrics.get("runtime_outcome_ref")) or (
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


def _non_runtime_source(source: str | None) -> bool:
    return source is not None and any(marker in source.casefold() for marker in _NON_RUNTIME_SOURCE_MARKERS)


def _with_rejection(rejections: Counter[str], reason: str) -> Counter[str]:
    rejections[reason] += 1
    return rejections
