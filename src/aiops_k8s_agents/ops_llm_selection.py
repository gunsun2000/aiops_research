from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class OpsLLMSelectionError(ValueError):
    """Raised when the Ops LLM benchmark or selection policy is invalid."""


@dataclass(frozen=True)
class OpsLLMBenchmarkMetadata:
    data_source: str
    benchmark_run_id: str
    generated_from: tuple[str, ...]
    is_synthetic: bool
    last_updated: str
    notes: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpsLLMBenchmarkMetadata:
        data_source = str(data.get("data_source", "unspecified")).strip()
        if not data_source:
            raise OpsLLMSelectionError("benchmark metadata data_source is required")
        return cls(
            data_source=data_source,
            benchmark_run_id=str(data.get("benchmark_run_id", "")).strip(),
            generated_from=tuple(
                str(item) for item in data.get("generated_from", [])
            ),
            is_synthetic=bool(data.get("is_synthetic", False)),
            last_updated=str(data.get("last_updated", "")).strip(),
            notes=tuple(str(item) for item in data.get("notes", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["generated_from"] = list(self.generated_from)
        data["notes"] = list(self.notes)
        return data


@dataclass(frozen=True)
class OpsLLMCandidate:
    model: str
    provider: str
    role: str
    correct_detection_runs: int
    total_detection_runs: int
    metric_success_runs: int
    total_metric_runs: int
    average_ttd_seconds: float
    average_action_steps: float
    action_validity_rate: float
    consistency_score: float
    estimated_cost_per_1k_ops: float
    average_latency_ms: float
    notes: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpsLLMCandidate:
        model = str(data.get("model", "")).strip()
        if not model:
            raise OpsLLMSelectionError("candidate model is required")
        total_detection_runs = int(data.get("total_detection_runs", 0))
        total_metric_runs = int(data.get("total_metric_runs", 0))
        if total_detection_runs <= 0:
            raise OpsLLMSelectionError(
                f"candidate {model} must define total_detection_runs > 0"
            )
        if total_metric_runs <= 0:
            raise OpsLLMSelectionError(
                f"candidate {model} must define total_metric_runs > 0"
            )
        return cls(
            model=model,
            provider=str(data.get("provider", "")),
            role=str(data.get("role", "")),
            correct_detection_runs=int(data.get("correct_detection_runs", 0)),
            total_detection_runs=total_detection_runs,
            metric_success_runs=int(data.get("metric_success_runs", 0)),
            total_metric_runs=total_metric_runs,
            average_ttd_seconds=float(data.get("average_ttd_seconds", 0)),
            average_action_steps=float(data.get("average_action_steps", 0)),
            action_validity_rate=float(data.get("action_validity_rate", 0)),
            consistency_score=float(data.get("consistency_score", 0)),
            estimated_cost_per_1k_ops=float(
                data.get("estimated_cost_per_1k_ops", 0)
            ),
            average_latency_ms=float(data.get("average_latency_ms", 0)),
            notes=tuple(str(item) for item in data.get("notes", [])),
        )

    @property
    def accuracy_rate(self) -> float:
        return self.correct_detection_runs / self.total_detection_runs

    @property
    def metric_success_rate(self) -> float:
        return self.metric_success_runs / self.total_metric_runs

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        data["accuracy_rate"] = round(self.accuracy_rate, 6)
        data["metric_success_rate"] = round(self.metric_success_rate, 6)
        return data


@dataclass(frozen=True)
class OpsLLMSelectionPolicy:
    name: str
    weights: dict[str, float]
    description: str

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> OpsLLMSelectionPolicy:
        weights = {str(key): float(value) for key, value in data.get("weights", {}).items()}
        if not weights:
            raise OpsLLMSelectionError(f"policy {name} must define weights")
        return cls(
            name=name,
            weights=weights,
            description=str(data.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpsLLMBenchmarkConfig:
    version: str
    metadata: OpsLLMBenchmarkMetadata
    candidates: dict[str, OpsLLMCandidate]
    policies: dict[str, OpsLLMSelectionPolicy]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpsLLMBenchmarkConfig:
        candidates = {
            candidate.model: candidate
            for candidate in (
                OpsLLMCandidate.from_dict(dict(raw))
                for raw in data.get("candidates", [])
            )
        }
        if not candidates:
            raise OpsLLMSelectionError("at least one LLM candidate is required")

        policies = {
            str(name): OpsLLMSelectionPolicy.from_dict(str(name), dict(raw_policy))
            for name, raw_policy in dict(data.get("policies", {})).items()
        }
        if not policies:
            raise OpsLLMSelectionError("at least one LLM selection policy is required")

        return cls(
            version=str(data.get("version", "1")),
            metadata=OpsLLMBenchmarkMetadata.from_dict(
                dict(data.get("metadata", {}))
            ),
            candidates=candidates,
            policies=policies,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "metadata": self.metadata.to_dict(),
            "candidates": [
                self.candidates[model].to_dict()
                for model in sorted(self.candidates)
            ],
            "policies": {
                name: self.policies[name].to_dict()
                for name in sorted(self.policies)
            },
        }


@dataclass(frozen=True)
class OpsLLMSelectionResult:
    valid: bool
    policy: str
    selected_model: str
    selected_score: float
    rationale: str
    ranking: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_ops_llm_benchmark_config(path: str | Path) -> OpsLLMBenchmarkConfig:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return OpsLLMBenchmarkConfig.from_dict(data)


def select_ops_llm(
    config: OpsLLMBenchmarkConfig,
    policy_name: str = "quality_first",
) -> OpsLLMSelectionResult:
    try:
        policy = config.policies[policy_name]
    except KeyError as exc:
        raise OpsLLMSelectionError(
            f"unknown LLM selection policy: {policy_name}"
        ) from exc

    minimums = _candidate_minimums(config.candidates.values())
    ranking = []
    for candidate in config.candidates.values():
        metrics = _normalized_metrics(candidate, minimums)
        score = sum(
            policy.weights.get(metric_name, 0.0) * metric_value
            for metric_name, metric_value in metrics.items()
        )
        ranking.append(
            {
                "model": candidate.model,
                "provider": candidate.provider,
                "role": candidate.role,
                "score": round(score, 6),
                "metrics": {key: round(value, 6) for key, value in metrics.items()},
                "notes": list(candidate.notes),
            }
        )

    ranking.sort(key=lambda item: (-float(item["score"]), str(item["model"])))
    selected = ranking[0]
    return OpsLLMSelectionResult(
        valid=True,
        policy=policy.name,
        selected_model=str(selected["model"]),
        selected_score=float(selected["score"]),
        rationale=(
            f"{selected['model']} ranked first under {policy.name} because the "
            "weighted Ops accuracy, action safety, consistency, latency, and cost "
            "criteria produced the highest score."
        ),
        ranking=ranking,
    )


def _candidate_minimums(
    candidates: Any,
) -> dict[str, float]:
    candidate_list = list(candidates)
    return {
        "ttd": min(
            candidate.average_ttd_seconds
            for candidate in candidate_list
            if candidate.average_ttd_seconds > 0
        ),
        "cost": min(
            candidate.estimated_cost_per_1k_ops
            for candidate in candidate_list
            if candidate.estimated_cost_per_1k_ops > 0
        ),
        "latency": min(
            candidate.average_latency_ms
            for candidate in candidate_list
            if candidate.average_latency_ms > 0
        ),
    }


def _normalized_metrics(
    candidate: OpsLLMCandidate,
    minimums: dict[str, float],
) -> dict[str, float]:
    return {
        "accuracy": candidate.accuracy_rate,
        "metric_success": candidate.metric_success_rate,
        "action_validity": candidate.action_validity_rate,
        "consistency": candidate.consistency_score,
        "ttd": _lower_is_better_score(
            minimums["ttd"],
            candidate.average_ttd_seconds,
        ),
        "cost": _lower_is_better_score(
            minimums["cost"],
            candidate.estimated_cost_per_1k_ops,
        ),
        "latency": _lower_is_better_score(
            minimums["latency"],
            candidate.average_latency_ms,
        ),
    }


def _lower_is_better_score(best_value: float, candidate_value: float) -> float:
    if best_value <= 0 or candidate_value <= 0:
        return 0.0
    return min(best_value / candidate_value, 1.0)
