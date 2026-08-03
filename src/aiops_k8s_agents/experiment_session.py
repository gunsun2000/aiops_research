from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping, Protocol


class ExperimentStage(str, Enum):
    CONDITION = "condition"
    EVIDENCE = "evidence"
    DIAGNOSIS = "diagnosis"
    CONSENSUS = "consensus"
    SAFETY = "safety"
    EXECUTION = "execution"
    RESULT = "result"


@dataclass(frozen=True)
class ExperimentSession:
    experiment_id: str
    created_at: str
    mode: str
    guard_backend: str
    status: str
    protocol_profile: Mapping[str, Any]
    condition: Mapping[str, Any]
    stages: Mapping[str, Mapping[str, Any]]
    active_agents: tuple[str, ...]
    human_review_required: bool
    artifacts: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "mode": self.mode,
            "guard_backend": self.guard_backend,
            "status": self.status,
            "protocol_profile": _thaw(self.protocol_profile),
            "condition": _thaw(self.condition),
            "stages": _thaw(self.stages),
            "active_agents": list(self.active_agents),
            "human_review_required": self.human_review_required,
            "artifacts": _thaw(self.artifacts),
        }


class ExperimentSessionStore(Protocol):
    def put(self, session: ExperimentSession) -> ExperimentSession: ...

    def get(self, experiment_id: str) -> ExperimentSession | None: ...


class InMemoryExperimentSessionStore:
    def __init__(self, max_sessions: int = 50) -> None:
        if isinstance(max_sessions, bool) or max_sessions <= 0:
            raise ValueError("max_sessions must be a positive integer")
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, ExperimentSession] = OrderedDict()
        self._lock = RLock()

    def put(self, session: ExperimentSession) -> ExperimentSession:
        if not isinstance(session, ExperimentSession):
            raise TypeError("session must be an ExperimentSession")
        with self._lock:
            self._sessions.pop(session.experiment_id, None)
            self._sessions[session.experiment_id] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        return session

    def get(self, experiment_id: str) -> ExperimentSession | None:
        with self._lock:
            return self._sessions.get(experiment_id)

    def list(self) -> tuple[ExperimentSession, ...]:
        with self._lock:
            return tuple(reversed(self._sessions.values()))


def normalize_experiment_session(
    report: Mapping[str, Any],
) -> ExperimentSession:
    experiment_id = str(report.get("run_id", "")).strip()
    if not experiment_id:
        raise ValueError("mutual supervision report is missing run_id")

    evidence = _mapping(report.get("evidence"))
    diagnosis = _mapping(report.get("diagnosis"))
    negotiation = _mapping(report.get("negotiation"))
    safety = _mapping(report.get("safety_validation"))
    execution = _mapping(report.get("execution_result"))
    recovery = _mapping(report.get("recovery_monitoring"))
    metadata = _mapping(report.get("metadata"))
    final_status = str(report.get("final_status", "unknown")).strip() or "unknown"

    condition = {
        "scenario": evidence.get("scenario", ""),
        "namespace": evidence.get("namespace", ""),
        "deployment": evidence.get("deployment", ""),
        "metric_values": evidence.get("metric_values", {}),
        "source": evidence.get("source", ""),
    }
    stages = {
        ExperimentStage.CONDITION.value: _stage(
            experiment_id,
            "completed" if any(condition.values()) else "pending",
            condition,
        ),
        ExperimentStage.EVIDENCE.value: _stage(
            experiment_id,
            "completed" if evidence else "pending",
            evidence,
        ),
        ExperimentStage.DIAGNOSIS.value: _stage(
            experiment_id,
            "completed" if diagnosis else "pending",
            {
                "diagnosis": diagnosis,
                "initial_decisions": report.get("initial_decisions", []),
            },
        ),
        ExperimentStage.CONSENSUS.value: _stage(
            experiment_id,
            _consensus_status(negotiation),
            {
                "peer_reviews": report.get("peer_reviews", []),
                "negotiation": negotiation,
                "selected_action": report.get("selected_action", {}),
            },
        ),
        ExperimentStage.SAFETY.value: _stage(
            experiment_id,
            _safety_status(safety),
            safety,
        ),
        ExperimentStage.EXECUTION.value: _stage(
            experiment_id,
            _execution_status(execution, safety),
            execution,
        ),
        ExperimentStage.RESULT.value: _stage(
            experiment_id,
            _result_status(final_status, recovery),
            {
                "recovery_monitoring": recovery,
                "post_execution_reviews": report.get(
                    "post_execution_reviews",
                    [],
                ),
                "agent_contributions": report.get("agent_contributions", {}),
                "final_status": final_status,
            },
        ),
    }
    created_at = str(
        report.get("created_at")
        or metadata.get("created_at")
        or datetime.now(UTC).isoformat()
    )
    artifacts = {
        str(key): str(value)
        for key, value in _mapping(report.get("artifacts")).items()
    }
    return ExperimentSession(
        experiment_id=experiment_id,
        created_at=created_at,
        mode=str(report.get("mode", "unknown")),
        guard_backend=str(metadata.get("guard_backend", "unknown")),
        status=final_status,
        protocol_profile=_freeze(_mapping(report.get("protocol_profile"))),
        condition=_freeze(condition),
        stages=_freeze(stages),
        active_agents=tuple(
            str(agent) for agent in report.get("active_agents", [])
        ),
        human_review_required=bool(
            report.get("human_review_required", False)
        ),
        artifacts=_freeze(artifacts),
    )


def _stage(
    experiment_id: str,
    status: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "status": status,
        "payload": dict(payload),
    }


def _consensus_status(negotiation: Mapping[str, Any]) -> str:
    if not negotiation:
        return "pending"
    consensus = str(negotiation.get("consensus", "")).lower()
    if consensus in {"approved", "not_required"}:
        return "completed"
    return "blocked"


def _safety_status(safety: Mapping[str, Any]) -> str:
    if not safety:
        return "pending"
    return "completed" if safety.get("valid") is True else "blocked"


def _execution_status(
    execution: Mapping[str, Any],
    safety: Mapping[str, Any],
) -> str:
    if not execution or safety.get("valid") is not True:
        return "pending"
    if execution.get("valid") is True:
        return "completed"
    return "failed"


def _result_status(
    final_status: str,
    recovery: Mapping[str, Any],
) -> str:
    if recovery:
        recovered = recovery.get(
            "recovered",
            recovery.get("recovery_success"),
        )
        return "completed" if recovered is True else "failed"
    if final_status in {"no_action_required", "recovered", "recovered_after_replan"}:
        return "completed"
    if final_status in {"cancelled", "interrupted", "blocked", "cleanup_failed"}:
        return final_status
    if final_status in {
        "safe_failure",
        "runtime_unavailable",
        "configuration_rejected",
    }:
        return "failed"
    if final_status in {"safe_stopped", "consensus_rejected"}:
        return "blocked"
    return "pending"


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset | set):
        return [_thaw(item) for item in sorted(value, key=repr)]
    return deepcopy(value)
