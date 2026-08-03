from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.experiment_runtime_models import RuntimeEvent, RuntimeStage


@dataclass(frozen=True)
class RecoveryComparisonRequest:
    repetitions: int = 1
    mode: str = "mock"
    guard_backend: str = "python"

    def __post_init__(self) -> None:
        if (
            isinstance(self.repetitions, bool)
            or not isinstance(self.repetitions, int)
            or not 1 <= self.repetitions <= 3
        ):
            raise ValueError("repetitions must be an integer in 1..3")
        mode = str(self.mode).strip().lower()
        if mode not in {"mock", "real"}:
            raise ValueError("mode must be mock or real")
        guard_backend = str(self.guard_backend).strip().lower()
        if guard_backend not in {"python", "go"}:
            raise ValueError("guard_backend must be python or go")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "guard_backend", guard_backend)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repetitions": self.repetitions,
            "mode": self.mode,
            "guard_backend": self.guard_backend,
        }


@dataclass(frozen=True)
class RecoveryComparisonJob:
    job_id: str
    request: RecoveryComparisonRequest
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
            "job_id": self.job_id,
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


class SQLiteRecoveryComparisonJobStore:
    """Durable recovery-matrix jobs kept separate from single recovery jobs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def create(
        self,
        request: RecoveryComparisonRequest,
        *,
        job_id: str | None = None,
    ) -> RecoveryComparisonJob:
        if not isinstance(request, RecoveryComparisonRequest):
            raise TypeError("request must be a RecoveryComparisonRequest")
        job_id = (job_id or f"cmp-{uuid4().hex}").strip()
        if not job_id:
            raise ValueError("job_id must not be empty")
        now = _now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO recovery_comparison_jobs (
                        job_id, request_json, status, current_stage,
                        created_at, updated_at, cancel_requested, error
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, '')
                    """,
                    (
                        job_id,
                        _dump(request.to_dict()),
                        ExperimentJobStatus.QUEUED.value,
                        RuntimeStage.QUEUED.value,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"comparison job already exists: {job_id}") from exc
        return self._required(job_id)

    def get(self, job_id: str) -> RecoveryComparisonJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM recovery_comparison_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _job_from_row(row) if row is not None else None

    def list(self, limit: int = 50) -> tuple[RecoveryComparisonJob, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM recovery_comparison_jobs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def transition(
        self,
        job_id: str,
        status: ExperimentJobStatus | str,
        *,
        current_stage: str | None = None,
        error: str | None = None,
    ) -> RecoveryComparisonJob:
        status = ExperimentJobStatus(status)
        existing = self._required(job_id)
        now = _now()
        started_at = existing.started_at
        if status is ExperimentJobStatus.RUNNING and started_at is None:
            started_at = now
        finished_at = now if status.terminal else existing.finished_at
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE recovery_comparison_jobs
                SET status = ?, current_stage = ?, updated_at = ?,
                    started_at = ?, finished_at = ?, error = ?
                WHERE job_id = ?
                """,
                (
                    status.value,
                    current_stage or existing.current_stage,
                    now,
                    started_at,
                    finished_at,
                    existing.error if error is None else str(error),
                    job_id,
                ),
            )
        return self._required(job_id)

    def append_event(self, event: RuntimeEvent) -> RuntimeEvent:
        if not isinstance(event, RuntimeEvent):
            raise TypeError("event must be a RuntimeEvent")
        self._required(event.experiment_id)
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO recovery_comparison_events (
                        job_id, sequence, event_json, created_at
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
                    f"comparison event already exists: "
                    f"{event.experiment_id}/{event.sequence}"
                ) from exc
            connection.execute(
                """
                UPDATE recovery_comparison_jobs
                SET current_stage = ?, updated_at = ? WHERE job_id = ?
                """,
                (event.stage.value, _now(), event.experiment_id),
            )
        return event

    def events_after(
        self,
        job_id: str,
        sequence: int = 0,
    ) -> tuple[RuntimeEvent, ...]:
        self._required(job_id)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM recovery_comparison_events
                WHERE job_id = ? AND sequence > ? ORDER BY sequence ASC
                """,
                (job_id, sequence),
            ).fetchall()
        return tuple(_event_from_dict(json.loads(row["event_json"])) for row in rows)

    def set_result(
        self,
        job_id: str,
        *,
        status: ExperimentJobStatus | str,
        result: Mapping[str, Any],
        error: str = "",
    ) -> RecoveryComparisonJob:
        status = ExperimentJobStatus(status)
        if not status.terminal:
            raise ValueError("result status must be terminal")
        self._required(job_id)
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE recovery_comparison_jobs
                SET status = ?, current_stage = ?, result_json = ?, error = ?,
                    updated_at = ?, finished_at = ? WHERE job_id = ?
                """,
                (
                    status.value,
                    RuntimeStage.COMPLETED.value,
                    _dump(dict(result)),
                    str(error),
                    now,
                    now,
                    job_id,
                ),
            )
        return self._required(job_id)

    def request_cancel(self, job_id: str) -> RecoveryComparisonJob:
        existing = self._required(job_id)
        if existing.status.terminal:
            return existing
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE recovery_comparison_jobs
                SET status = ?, cancel_requested = 1, updated_at = ?
                WHERE job_id = ?
                """,
                (ExperimentJobStatus.CANCELLING.value, _now(), job_id),
            )
        return self._required(job_id)

    def interrupt_nonterminal_jobs(self) -> tuple[str, ...]:
        terminal = tuple(status.value for status in ExperimentJobStatus if status.terminal)
        placeholders = ",".join("?" for _ in terminal)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT job_id FROM recovery_comparison_jobs "
                f"WHERE status NOT IN ({placeholders}) ORDER BY rowid",
                terminal,
            ).fetchall()
            job_ids = tuple(str(row["job_id"]) for row in rows)
            now = _now()
            for job_id in job_ids:
                connection.execute(
                    """
                    UPDATE recovery_comparison_jobs
                    SET status = ?, current_stage = ?, error = ?,
                        updated_at = ?, finished_at = ? WHERE job_id = ?
                    """,
                    (
                        ExperimentJobStatus.INTERRUPTED.value,
                        RuntimeStage.COMPLETED.value,
                        "server restarted before comparison job completed",
                        now,
                        now,
                        job_id,
                    ),
                )
        return job_ids

    def _required(self, job_id: str) -> RecoveryComparisonJob:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS recovery_comparison_jobs (
                    job_id TEXT PRIMARY KEY,
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
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS recovery_comparison_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, sequence),
                    FOREIGN KEY (job_id) REFERENCES recovery_comparison_jobs(job_id)
                )
                """
            )


def _job_from_row(row: sqlite3.Row) -> RecoveryComparisonJob:
    request_data = json.loads(row["request_json"])
    result_data = json.loads(row["result_json"]) if row["result_json"] else None
    return RecoveryComparisonJob(
        job_id=str(row["job_id"]),
        request=RecoveryComparisonRequest(**request_data),
        status=ExperimentJobStatus(str(row["status"])),
        current_stage=str(row["current_stage"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        cancel_requested=bool(row["cancel_requested"]),
        result=(MappingProxyType(result_data) if result_data is not None else None),
        error=str(row["error"]),
    )


def _event_from_dict(data: Mapping[str, Any]) -> RuntimeEvent:
    return RuntimeEvent(
        experiment_id=str(data["experiment_id"]),
        sequence=int(data["sequence"]),
        stage=RuntimeStage(str(data["stage"])),
        status=str(data["status"]),
        message=str(data["message"]),
        created_at=str(data["created_at"]),
        payload=dict(data.get("payload", {})),
    )


def _dump(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()
