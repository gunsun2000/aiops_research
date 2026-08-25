from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class SelectionMode(str, Enum):
    DETERMINISTIC = "deterministic"
    SHADOW = "shadow"
    LEARNED_GUARDED = "learned_guarded"


@dataclass(frozen=True)
class CandidateRankingEntry:
    candidate_key: str
    baseline_score: float
    predicted_reward: float | None
    prediction_confidence: float | None
    rank: int
    eligible: bool
    warnings: tuple[str, ...] = ()
    feature_contributions: tuple[tuple[str, float], ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateRankingEntry:
        contributions = payload.get("feature_contributions", [])
        if isinstance(contributions, (str, bytes)) or not isinstance(
            contributions, Sequence
        ):
            raise ValueError("feature_contributions must be an array")
        return cls(
            candidate_key=str(payload["candidate_key"]),
            baseline_score=float(payload["baseline_score"]),
            predicted_reward=_optional_float(payload.get("predicted_reward")),
            prediction_confidence=_optional_float(
                payload.get("prediction_confidence")
            ),
            rank=int(payload["rank"]),
            eligible=bool(payload["eligible"]),
            warnings=tuple(str(item) for item in payload.get("warnings", [])),
            feature_contributions=tuple(
                _feature_contribution(item) for item in contributions
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "baseline_score": self.baseline_score,
            "predicted_reward": self.predicted_reward,
            "prediction_confidence": self.prediction_confidence,
            "rank": self.rank,
            "eligible": self.eligible,
            "warnings": list(self.warnings),
            "feature_contributions": [list(item) for item in self.feature_contributions],
        }


@dataclass(frozen=True)
class CandidateSelection:
    mode: SelectionMode
    active_ranker_id: str
    active_ranker_version: str
    baseline_selected_candidate_key: str | None
    learned_selected_candidate_key: str | None
    final_selected_candidate_key: str | None
    model_version: str | None
    model_artifact_hash: str | None
    feature_schema_version: str
    entries: tuple[CandidateRankingEntry, ...]
    confidence: float
    fallback_used: bool
    fallback_reason: str | None
    rationale: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateSelection:
        entries = payload.get("entries", [])
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
            raise ValueError("entries must be an array")
        return cls(
            mode=SelectionMode(str(payload["mode"])),
            active_ranker_id=str(payload["active_ranker_id"]),
            active_ranker_version=str(payload["active_ranker_version"]),
            baseline_selected_candidate_key=_optional_text(
                payload.get("baseline_selected_candidate_key")
            ),
            learned_selected_candidate_key=_optional_text(
                payload.get("learned_selected_candidate_key")
            ),
            final_selected_candidate_key=_optional_text(
                payload.get("final_selected_candidate_key")
            ),
            model_version=_optional_text(payload.get("model_version")),
            model_artifact_hash=_optional_text(payload.get("model_artifact_hash")),
            feature_schema_version=str(payload["feature_schema_version"]),
            entries=tuple(
                CandidateRankingEntry.from_dict(_mapping(item, "entries[]"))
                for item in entries
            ),
            confidence=float(payload["confidence"]),
            fallback_used=bool(payload["fallback_used"]),
            fallback_reason=_optional_text(payload.get("fallback_reason")),
            rationale=tuple(str(item) for item in payload.get("rationale", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "active_ranker_id": self.active_ranker_id,
            "active_ranker_version": self.active_ranker_version,
            "baseline_selected_candidate_key": self.baseline_selected_candidate_key,
            "learned_selected_candidate_key": self.learned_selected_candidate_key,
            "final_selected_candidate_key": self.final_selected_candidate_key,
            "model_version": self.model_version,
            "model_artifact_hash": self.model_artifact_hash,
            "feature_schema_version": self.feature_schema_version,
            "entries": [entry.to_dict() for entry in self.entries],
            "confidence": self.confidence,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "rationale": list(self.rationale),
        }

    def signature_provenance(self) -> dict[str, str | None]:
        return {
            "mode": self.mode.value,
            "active_ranker_id": self.active_ranker_id,
            "active_ranker_version": self.active_ranker_version,
            "model_artifact_hash": self.model_artifact_hash,
            "final_selected_candidate_key": self.final_selected_candidate_key,
        }


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _feature_contribution(value: Any) -> tuple[str, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        raise ValueError("feature_contributions[] must contain a name and value")
    return str(value[0]), float(value[1])

