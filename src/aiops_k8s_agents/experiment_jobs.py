from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    RuntimeEvent,
    RuntimeStage,
)
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode


class ExperimentJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    @property
    def terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.FAILED,
            self.BLOCKED,
            self.CANCELLED,
            self.INTERRUPTED,
        }


@dataclass(frozen=True)
class ExperimentJob:
    experiment_id: str
    request: ExperimentRuntimeRequest
    status: ExperimentJobStatus
    current_stage: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    cancel_requested: bool = False
    result: Mapping[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "current_stage": self.current_stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
            "result": dict(self.result) if self.result is not None else None,
            "error": self.error,
        }


class SQLiteExperimentJobStore:
    """Durable source of truth for web experiment jobs and runtime events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def create(
        self,
        request: ExperimentRuntimeRequest,
        *,
        experiment_id: str | None = None,
    ) -> ExperimentJob:
        if not isinstance(request, ExperimentRuntimeRequest):
            raise TypeError("request must be an ExperimentRuntimeRequest")
        experiment_id = (experiment_id or f"exp-{uuid4().hex}").strip()
        if not experiment_id:
            raise ValueError("experiment_id must not be empty")
        now = _now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO experiment_jobs (
                        experiment_id, request_json, status, current_stage,
                        created_at, updated_at, cancel_requested, error
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, '')
                    """,
                    (
                        experiment_id,
                        _dump(request.to_dict()),
                        ExperimentJobStatus.QUEUED.value,
                        RuntimeStage.QUEUED.value,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"experiment already exists: {experiment_id}") from exc
        return self._required(experiment_id)

    def get(self, experiment_id: str) -> ExperimentJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiment_jobs WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return _job_from_row(row) if row is not None else None

    def list(self, limit: int = 50) -> tuple[ExperimentJob, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM experiment_jobs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def transition(
        self,
        experiment_id: str,
        status: ExperimentJobStatus | str,
        *,
        current_stage: str | None = None,
        error: str | None = None,
    ) -> ExperimentJob:
        status = ExperimentJobStatus(status)
        existing = self._required(experiment_id)
        now = _now()
        started_at = existing.started_at
        if status is ExperimentJobStatus.RUNNING and started_at is None:
            started_at = now
        finished_at = now if status.terminal else existing.finished_at
        stage = current_stage or existing.current_stage
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE experiment_jobs
                SET status = ?, current_stage = ?, updated_at = ?,
                    started_at = ?, finished_at = ?, error = ?
                WHERE experiment_id = ?
                """,
                (
                    status.value,
                    stage,
                    now,
                    started_at,
                    finished_at,
                    existing.error if error is None else str(error),
                    experiment_id,
                ),
            )
        return self._required(experiment_id)

    def append_event(self, event: RuntimeEvent) -> RuntimeEvent:
        if not isinstance(event, RuntimeEvent):
            raise TypeError("event must be a RuntimeEvent")
        self._required(event.experiment_id)
        now = _now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO experiment_events (
                        experiment_id, sequence, event_json, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        event.experiment_id,
                        event.sequence,
                        _dump(event.to_dict()),
                        event.created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"runtime event already exists: {event.experiment_id}/{event.sequence}"
                ) from exc
            connection.execute(
                """
                UPDATE experiment_jobs
                SET current_stage = ?, updated_at = ?
                WHERE experiment_id = ?
                """,
                (event.stage.value, now, event.experiment_id),
            )
        return event

    def events_after(
        self,
        experiment_id: str,
        sequence: int = 0,
    ) -> tuple[RuntimeEvent, ...]:
        self._required(experiment_id)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM experiment_events
                WHERE experiment_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (experiment_id, sequence),
            ).fetchall()
        return tuple(_event_from_dict(json.loads(row["event_json"])) for row in rows)

    def set_result(
        self,
        experiment_id: str,
        *,
        status: ExperimentJobStatus | str,
        result: Mapping[str, Any],
        error: str = "",
    ) -> ExperimentJob:
        status = ExperimentJobStatus(status)
        if not status.terminal:
            raise ValueError("result status must be terminal")
        self._required(experiment_id)
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE experiment_jobs
                SET status = ?, current_stage = ?, result_json = ?, error = ?,
                    updated_at = ?, finished_at = ?
                WHERE experiment_id = ?
                """,
                (
                    status.value,
                    RuntimeStage.COMPLETED.value,
                    _dump(dict(result)),
                    str(error),
                    now,
                    now,
                    experiment_id,
                ),
            )
        return self._required(experiment_id)

    def request_cancel(self, experiment_id: str) -> ExperimentJob:
        existing = self._required(experiment_id)
        if existing.status.terminal:
            return existing
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE experiment_jobs
                SET status = ?, cancel_requested = 1, updated_at = ?
                WHERE experiment_id = ?
                """,
                (ExperimentJobStatus.CANCELLING.value, now, experiment_id),
            )
        return self._required(experiment_id)

    def delete(self, experiment_id: str) -> ExperimentJob:
        existing = self._required(experiment_id)
        if not existing.status.terminal:
            raise ValueError("only terminal experiment jobs can be deleted")
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM experiment_jobs WHERE experiment_id = ?",
                (experiment_id,),
            )
        return existing

    def interrupt_nonterminal_jobs(self) -> tuple[str, ...]:
        statuses = (
            ExperimentJobStatus.QUEUED.value,
            ExperimentJobStatus.RUNNING.value,
            ExperimentJobStatus.CANCELLING.value,
        )
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT experiment_id FROM experiment_jobs
                WHERE status IN (?, ?, ?)
                ORDER BY rowid ASC
                """,
                statuses,
            ).fetchall()
            experiment_ids = tuple(row["experiment_id"] for row in rows)
            if experiment_ids:
                now = _now()
                connection.execute(
                    """
                    UPDATE experiment_jobs
                    SET status = ?, current_stage = ?, updated_at = ?,
                        finished_at = ?, error = ?
                    WHERE status IN (?, ?, ?)
                    """,
                    (
                        ExperimentJobStatus.INTERRUPTED.value,
                        RuntimeStage.CLEANUP.value,
                        now,
                        now,
                        "server restarted while the experiment was nonterminal",
                        *statuses,
                    ),
                )
        return experiment_ids

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS experiment_jobs (
                    experiment_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS experiment_events (
                    experiment_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (experiment_id, sequence),
                    FOREIGN KEY (experiment_id)
                        REFERENCES experiment_jobs(experiment_id)
                        ON DELETE CASCADE
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _required(self, experiment_id: str) -> ExperimentJob:
        job = self.get(experiment_id)
        if job is None:
            raise KeyError(f"experiment job not found: {experiment_id}")
        return job


def _job_from_row(row: sqlite3.Row) -> ExperimentJob:
    request = _request_from_dict(json.loads(row["request_json"]))
    result_data = json.loads(row["result_json"]) if row["result_json"] else None
    result = MappingProxyType(result_data) if result_data is not None else None
    return ExperimentJob(
        experiment_id=row["experiment_id"],
        request=request,
        status=ExperimentJobStatus(row["status"]),
        current_stage=row["current_stage"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        cancel_requested=bool(row["cancel_requested"]),
        result=result,
        error=row["error"],
    )


def _request_from_dict(data: Mapping[str, Any]) -> ExperimentRuntimeRequest:
    return ExperimentRuntimeRequest(
        scenario_id=data["scenario_id"],
        namespace=data["namespace"],
        deployment=data["deployment"],
        metric=data["metric"],
        threshold=data["threshold"],
        mode=ExecutionMode(data["mode"]),
        backend=ExecutionBackend(data["backend"]),
        protocol_profile=data["protocol_profile"],
        repetitions=data["repetitions"],
        controller=data.get("controller", "deterministic"),
        model=data.get("model", ""),
        incident_source=data.get("incident_source", "chaos_mesh"),
        benchmark_id=data.get("benchmark_id", ""),
        detection_context=data.get("detection_context", {}),
    )


def _event_from_dict(data: Mapping[str, Any]) -> RuntimeEvent:
    return RuntimeEvent(
        experiment_id=data["experiment_id"],
        sequence=data["sequence"],
        stage=RuntimeStage(data["stage"]),
        status=data["status"],
        message=data["message"],
        created_at=data["created_at"],
        payload=data.get("payload", {}),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
