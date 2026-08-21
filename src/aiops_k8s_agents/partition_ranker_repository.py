from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence
from uuid import uuid4

from aiops_k8s_agents.partition_context import canonical_json
from aiops_k8s_agents.partition_features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from aiops_k8s_agents.partition_models import PartitionContractError


MODEL_ARTIFACT_SCHEMA_VERSION = "partition-ranker-model-v1"


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
            "artifact_hash": self.artifact_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionRankerModelArtifact:
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
        if require_hash:
            _validate_sha256(self.artifact_hash, "artifact_hash")


class PartitionRankerRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def save(self, artifact: PartitionRankerModelArtifact) -> Path:
        verified = artifact.with_computed_hash()
        path = self._model_path(verified.model_version)
        self._write_json_atomic(path, verified.to_dict())
        return path

    def get(self, model_version: str) -> PartitionRankerModelArtifact:
        artifact = PartitionRankerModelArtifact.from_dict(
            self._read_json(self._model_path(model_version))
        )
        artifact.verify_hash()
        return artifact

    def list(self) -> tuple[PartitionRankerModelArtifact, ...]:
        if not self.root.is_dir():
            return ()
        versions = sorted(path.parent.name for path in self.root.glob("*/model.json"))
        return tuple(self.get(version) for version in versions)

    def _model_path(self, model_version: str) -> Path:
        return self.root / _validate_model_version(model_version) / "model.json"

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
    if isinstance(value, bool):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_model_artifact", f"{field} must be numeric"
        ) from exc
    if not isfinite(number):
        raise PartitionContractError("invalid_model_artifact", f"{field} must be finite")
    return number


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PartitionContractError("invalid_model_artifact", f"{field} is required")
    return value.strip()
