from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence
from uuid import uuid4

from aiops_k8s_agents.partition_context import canonical_json
from aiops_k8s_agents.partition_features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from aiops_k8s_agents.partition_models import PartitionContractError


MODEL_ARTIFACT_SCHEMA_VERSION = "partition-ranker-model-v2"
_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "model_type",
        "model_version",
        "feature_schema_version",
        "trained_at",
        "training_dataset_hash",
        "training_scope",
        "sample_count",
        "group_count",
        "feature_order",
        "feature_mean",
        "feature_scale",
        "coefficients",
        "intercept",
        "training_feature_ranges",
        "validation_metrics",
        "confidence_policy",
        "training_provenance",
        "artifact_hash",
    }
)


@dataclass(frozen=True)
class PartitionRankerModelArtifact:
    schema_version: str
    model_type: str
    model_version: str
    feature_schema_version: str
    trained_at: str
    training_dataset_hash: str
    training_scope: str
    sample_count: int
    group_count: int
    feature_order: tuple[str, ...]
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    training_feature_ranges: dict[str, tuple[float, float]]
    validation_metrics: dict[str, float]
    confidence_policy: dict[str, float]
    training_provenance: dict[str, object]
    artifact_hash: str

    def with_computed_hash(self) -> PartitionRankerModelArtifact:
        self._validate(require_hash=False)
        return replace(self, artifact_hash=self._computed_hash())

    def verify_hash(self) -> None:
        self._validate(require_hash=True)
        if self.artifact_hash != self._computed_hash():
            raise PartitionContractError(
                "invalid_model_artifact", "artifact hash does not match its canonical payload"
            )

    def to_dict(self) -> dict[str, object]:
        self._validate(require_hash=False)
        return {
            "schema_version": self.schema_version,
            "model_type": self.model_type,
            "model_version": self.model_version,
            "feature_schema_version": self.feature_schema_version,
            "trained_at": self.trained_at,
            "training_dataset_hash": self.training_dataset_hash,
            "training_scope": self.training_scope,
            "sample_count": self.sample_count,
            "group_count": self.group_count,
            "feature_order": list(self.feature_order),
            "feature_mean": list(self.feature_mean),
            "feature_scale": list(self.feature_scale),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "training_feature_ranges": {
                name: list(self.training_feature_ranges[name]) for name in FEATURE_ORDER
            },
            "validation_metrics": dict(self.validation_metrics),
            "confidence_policy": dict(self.confidence_policy),
            "training_provenance": _training_provenance_to_dict(self.training_provenance),
            "artifact_hash": self.artifact_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionRankerModelArtifact:
        unknown_fields = set(payload) - _ARTIFACT_FIELDS
        if unknown_fields:
            raise PartitionContractError(
                "invalid_model_artifact", "unknown artifact fields are not allowed"
            )
        missing_fields = _ARTIFACT_FIELDS - set(payload)
        if missing_fields:
            raise PartitionContractError(
                "invalid_model_artifact", "required artifact fields are missing"
            )
        artifact = cls(
            schema_version=_text(payload.get("schema_version"), "schema_version"),
            model_type=_text(payload.get("model_type"), "model_type"),
            model_version=_text(payload.get("model_version"), "model_version"),
            feature_schema_version=_text(
                payload.get("feature_schema_version"), "feature_schema_version"
            ),
            trained_at=_text(payload.get("trained_at"), "trained_at"),
            training_dataset_hash=_text(
                payload.get("training_dataset_hash"), "training_dataset_hash"
            ),
            training_scope=_text(payload.get("training_scope"), "training_scope"),
            sample_count=_integer(payload.get("sample_count"), "sample_count", minimum=0),
            group_count=_integer(payload.get("group_count"), "group_count", minimum=0),
            feature_order=_text_tuple(payload.get("feature_order"), "feature_order"),
            feature_mean=_number_tuple(payload.get("feature_mean"), "feature_mean"),
            feature_scale=_number_tuple(payload.get("feature_scale"), "feature_scale"),
            coefficients=_number_tuple(payload.get("coefficients"), "coefficients"),
            intercept=_number(payload.get("intercept"), "intercept"),
            training_feature_ranges=_feature_ranges(
                payload.get("training_feature_ranges")
            ),
            validation_metrics=_numeric_mapping(
                payload.get("validation_metrics"), "validation_metrics"
            ),
            confidence_policy=_numeric_mapping(
                payload.get("confidence_policy"), "confidence_policy"
            ),
            training_provenance=_training_provenance(
                payload.get("training_provenance")
            ),
            artifact_hash=_text(payload.get("artifact_hash"), "artifact_hash"),
        )
        artifact._validate(require_hash=True)
        return artifact

    def _computed_hash(self) -> str:
        payload = self.to_dict()
        payload.pop("artifact_hash")
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _validate(self, *, require_hash: bool) -> None:
        if self.schema_version != MODEL_ARTIFACT_SCHEMA_VERSION:
            raise PartitionContractError(
                "invalid_model_artifact", "unsupported artifact schema version"
            )
        _text(self.model_type, "model_type")
        _validate_model_version(self.model_version)
        _text(self.trained_at, "trained_at")
        _text(self.training_scope, "training_scope")
        if self.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise PartitionContractError(
                "invalid_model_artifact", "feature schema version does not match partition-feature-v1"
            )
        if self.feature_order != FEATURE_ORDER:
            raise PartitionContractError(
                "invalid_model_artifact", "feature order does not match partition-feature-v1"
            )
        _validate_sha256(self.training_dataset_hash, "training_dataset_hash")
        _integer(self.sample_count, "sample_count", minimum=0)
        _integer(self.group_count, "group_count", minimum=0)
        _validate_vector(self.feature_mean, "feature_mean", positive=False)
        _validate_vector(self.feature_scale, "feature_scale", positive=True)
        _validate_vector(self.coefficients, "coefficients", positive=False)
        _number(self.intercept, "intercept")
        _validate_feature_ranges(self.training_feature_ranges)
        _numeric_mapping(self.validation_metrics, "validation_metrics")
        _numeric_mapping(self.confidence_policy, "confidence_policy")
        _training_provenance(self.training_provenance)
        if require_hash:
            _validate_sha256(self.artifact_hash, "artifact_hash")


class PartitionRankerRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()

    def save(self, artifact: PartitionRankerModelArtifact) -> Path:
        verified = artifact.with_computed_hash()
        path = self._model_path(verified.model_version, create_root=True)
        self._write_json_atomic(path, verified.to_dict())
        return path

    def get(self, model_version: str) -> PartitionRankerModelArtifact:
        artifact = PartitionRankerModelArtifact.from_dict(
            self._read_json(self._model_path(model_version, create_root=False))
        )
        artifact.verify_hash()
        return artifact

    def list(self) -> tuple[PartitionRankerModelArtifact, ...]:
        if self._registry_root(create=False) is None:
            return ()
        versions = []
        for path in self.root.iterdir():
            if _is_link(path):
                raise PartitionContractError(
                    "invalid_model_artifact", "registry path must not contain a symlink"
                )
            if not path.is_dir():
                continue
            model_path = self._model_path(path.name, create_root=False)
            if model_path.exists():
                versions.append(path.name)
        return tuple(self.get(version) for version in sorted(versions))

    def _model_path(self, model_version: str, *, create_root: bool) -> Path:
        version = _validate_model_version(model_version)
        resolved_root = self._registry_root(create=create_root)
        if resolved_root is None:
            return self.root / version / "model.json"
        path = self.root / version / "model.json"
        current = self.root
        for component in path.relative_to(self.root).parts:
            current /= component
            if _is_link(current):
                raise PartitionContractError(
                    "invalid_model_artifact", "registry path must not contain a symlink"
                )
        try:
            path.resolve(strict=False).relative_to(resolved_root)
        except ValueError as exc:
            raise PartitionContractError(
                "invalid_model_artifact", "registry path escapes the configured root"
            ) from exc
        return path

    def _registry_root(self, *, create: bool) -> Path | None:
        if not self.root.exists():
            if not create:
                return None
            self.root.mkdir(parents=True, exist_ok=True)
        if _is_link(self.root) or not self.root.is_dir():
            raise PartitionContractError(
                "invalid_model_artifact", "registry root must be a directory, not a symlink"
            )
        return self.root.resolve()

    @staticmethod
    def _read_json(path: Path) -> Mapping[str, Any]:
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise PartitionContractError(
                "model_not_found", "model artifact could not be read from the registry"
            ) from exc
        if not isinstance(payload, Mapping):
            raise PartitionContractError("invalid_model_artifact", "artifact must be an object")
        return payload

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
            with temporary.open("r+b") as handle:
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _validate_model_version(value: Any) -> str:
    version = _text(value, "model_version")
    windows_path = PureWindowsPath(version)
    if (
        "/" in version
        or "\\" in version
        or windows_path.drive
        or version in {".", ".."}
        or version != version.rstrip(" .")
    ):
        raise PartitionContractError(
            "invalid_model_artifact", "model_version must be a single safe registry segment"
        )
    return version


def _validate_sha256(value: Any, field: str) -> None:
    text = _text(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise PartitionContractError(
            "invalid_model_artifact", f"{field} must be a lowercase SHA-256 hex digest"
        )


def _training_provenance(value: Any) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PartitionContractError("invalid_model_artifact", "training_provenance must be an object")
    required_fields = {
        "seed",
        "ridge_alpha",
        "holdout_test_fraction",
        "eligibility_thresholds",
        "training_lineage_group_hashes",
    }
    if set(value) != required_fields:
        raise PartitionContractError(
            "invalid_model_artifact", "training_provenance fields are unsupported"
        )
    seed = value.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise PartitionContractError("invalid_model_artifact", "training_provenance.seed must be an integer")
    alpha = _number(value.get("ridge_alpha"), "training_provenance.ridge_alpha")
    if alpha <= 0.0:
        raise PartitionContractError("invalid_model_artifact", "training_provenance.ridge_alpha must be positive")
    test_fraction = _number(
        value.get("holdout_test_fraction"), "training_provenance.holdout_test_fraction"
    )
    if not 0.0 < test_fraction < 1.0:
        raise PartitionContractError(
            "invalid_model_artifact",
            "training_provenance.holdout_test_fraction must be between 0 and 1",
        )
    thresholds = value.get("eligibility_thresholds")
    required_thresholds = {
        "minimum_observed_samples",
        "minimum_independent_groups",
        "maximum_holdout_mae",
        "minimum_spearman_correlation",
    }
    if not isinstance(thresholds, Mapping) or set(thresholds) != required_thresholds:
        raise PartitionContractError(
            "invalid_model_artifact", "training_provenance.eligibility_thresholds are unsupported"
        )
    normalized_thresholds = {
        name: _number(item, f"training_provenance.eligibility_thresholds.{name}")
        for name, item in thresholds.items()
    }
    lineage_groups = value.get("training_lineage_group_hashes")
    if isinstance(lineage_groups, (str, bytes)) or not isinstance(lineage_groups, Sequence):
        raise PartitionContractError(
            "invalid_model_artifact", "training_provenance.training_lineage_group_hashes must be an array"
        )
    normalized_lineages = tuple(
        _validated_lineage_hash(item) for item in lineage_groups
    )
    if tuple(sorted(normalized_lineages)) != normalized_lineages or len(set(normalized_lineages)) != len(normalized_lineages):
        raise PartitionContractError(
            "invalid_model_artifact", "training provenance lineage hashes must be sorted and unique"
        )
    return {
        "seed": seed,
        "ridge_alpha": alpha,
        "holdout_test_fraction": test_fraction,
        "eligibility_thresholds": normalized_thresholds,
        "training_lineage_group_hashes": normalized_lineages,
    }


def _training_provenance_to_dict(value: Mapping[str, object]) -> dict[str, object]:
    provenance = _training_provenance(value)
    return {
        "seed": provenance["seed"],
        "ridge_alpha": provenance["ridge_alpha"],
        "holdout_test_fraction": provenance["holdout_test_fraction"],
        "eligibility_thresholds": provenance["eligibility_thresholds"],
        "training_lineage_group_hashes": list(provenance["training_lineage_group_hashes"]),
    }


def _validated_lineage_hash(value: Any) -> str:
    text = _text(value, "training_provenance.training_lineage_group_hashes[]")
    _validate_sha256(text, "training_provenance.training_lineage_group_hashes[]")
    return text


def _validate_vector(values: tuple[float, ...], field: str, *, positive: bool) -> None:
    if len(values) != len(FEATURE_ORDER):
        raise PartitionContractError(
            "invalid_model_artifact", f"{field} must match the fixed feature order"
        )
    for value in values:
        number = _number(value, field)
        if positive and number <= 0.0:
            raise PartitionContractError(
                "invalid_model_artifact", f"{field} values must be positive"
            )


def _validate_feature_ranges(ranges: Mapping[str, tuple[float, float]]) -> None:
    if set(ranges) != set(FEATURE_ORDER):
        raise PartitionContractError(
            "invalid_model_artifact", "training feature ranges must match the fixed feature order"
        )
    for name in FEATURE_ORDER:
        lower, upper = ranges[name]
        if _number(lower, f"training_feature_ranges.{name}[0]") > _number(
            upper, f"training_feature_ranges.{name}[1]"
        ):
            raise PartitionContractError(
                "invalid_model_artifact", "training feature range minimum exceeds maximum"
            )


def _feature_ranges(value: Any) -> dict[str, tuple[float, float]]:
    if not isinstance(value, Mapping):
        raise PartitionContractError(
            "invalid_model_artifact", "training_feature_ranges must be an object"
        )
    if set(value) != set(FEATURE_ORDER):
        raise PartitionContractError(
            "invalid_model_artifact", "training feature ranges must match the fixed feature order"
        )
    ranges: dict[str, tuple[float, float]] = {}
    for name in FEATURE_ORDER:
        pair = value[name]
        if isinstance(pair, (str, bytes)) or not isinstance(pair, Sequence) or len(pair) != 2:
            raise PartitionContractError(
                "invalid_model_artifact", f"training_feature_ranges.{name} must contain two values"
            )
        ranges[name] = (
            _number(pair[0], f"training_feature_ranges.{name}[0]"),
            _number(pair[1], f"training_feature_ranges.{name}[1]"),
        )
    return ranges


def _numeric_mapping(value: Any, field: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be an object")
    return {
        _text(name, f"{field} key"): _number(item, f"{field}.{name}")
        for name, item in value.items()
    }


def _text_tuple(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be an array")
    return tuple(_text(item, f"{field}[]") for item in value)


def _number_tuple(value: Any, field: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be an array")
    return tuple(_number(item, f"{field}[]") for item in value)


def _integer(value: Any, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PartitionContractError(
            "invalid_model_artifact", f"{field} must be an integer of at least {minimum}"
        )
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be finite")
    return number


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PartitionContractError("invalid_model_artifact", f"{field} is required")
    if value != value.strip():
        raise PartitionContractError(
            "invalid_model_artifact",
            f"{field} must not contain leading or trailing whitespace",
        )
    return value


def _is_link(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return path.is_symlink()
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
