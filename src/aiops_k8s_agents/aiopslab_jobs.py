from __future__ import annotations

import json
import re
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


_BENCHMARK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class AIOpsLabBenchmarkRequest:
    benchmark_id: str
    repetitions: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark_id, str):
            raise TypeError("benchmark_id must be a string")
        benchmark_id = self.benchmark_id.strip()
        if not _BENCHMARK_ID.fullmatch(benchmark_id):
            raise ValueError("benchmark_id must be a registered safe identifier")
        if (
            isinstance(self.repetitions, bool)
            or not isinstance(self.repetitions, int)
            or not 1 <= self.repetitions <= 12
        ):
            raise ValueError("repetitions must be an integer in 1..12")
        object.__setattr__(self, "benchmark_id", benchmark_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "repetitions": self.repetitions,
        }


@dataclass(frozen=True)
class AIOpsLabBenchmarkJob:
    job_id: str
    request: AIOpsLabBenchmarkRequest
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


class SQLiteAIOpsLabJobStore:
    """Durable AIOpsLab benchmark jobs kept separate from recovery jobs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def create(
        self,
        request: AIOpsLabBenchmarkRequest,
        *,
        job_id: str | None = None,
    ) -> AIOpsLabBenchmarkJob:
        if not isinstance(request, AIOpsLabBenchmarkRequest):
            raise TypeError("request must be an AIOpsLabBenchmarkRequest")
        job_id = (job_id or f"lab-{uuid4().hex}").strip()
        if not job_id:
            raise ValueError("job_id must not be empty")
        now = _now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO aiopslab_jobs (
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
                raise ValueError(f"benchmark job already exists: {job_id}") from exc
        return self._required(job_id)

    def get(self, job_id: str) -> AIOpsLabBenchmarkJob | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM aiopslab_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _job_from_row(row) if row is not None else None

    def list(self, limit: int = 50) -> tuple[AIOpsLabBenchmarkJob, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM aiopslab_jobs ORDER BY rowid DESC LIMIT ?",
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
    ) -> AIOpsLabBenchmarkJob:
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
                UPDATE aiopslab_jobs
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
        now = _now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO aiopslab_events (
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
                    f"benchmark event already exists: "
                    f"{event.experiment_id}/{event.sequence}"
                ) from exc
            connection.execute(
                """
                UPDATE aiopslab_jobs
                SET current_stage = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (event.stage.value, now, event.experiment_id),
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
                SELECT event_json FROM aiopslab_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence ASC
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
    ) -> AIOpsLabBenchmarkJob:
        status = ExperimentJobStatus(status)
        if not status.terminal:
            raise ValueError("result status must be terminal")
        self._required(job_id)
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE aiopslab_jobs
                SET status = ?, current_stage = ?, result_json = ?, error = ?,
                    updated_at = ?, finished_at = ?
                WHERE job_id = ?
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

    def request_cancel(self, job_id: str) -> AIOpsLabBenchmarkJob:
        existing = self._required(job_id)
        if existing.status.terminal:
            return existing
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE aiopslab_jobs
                SET status = ?, cancel_requested = 1, updated_at = ?
                WHERE job_id = ?
                """,
                (ExperimentJobStatus.CANCELLING.value, now, job_id),
            )
        return self._required(job_id)

    def delete(self, job_id: str) -> AIOpsLabBenchmarkJob:
        """Delete one terminal benchmark job and its persisted events."""

        with self._lock:
            existing = self._required(job_id)
            if not existing.status.terminal:
                raise ValueError("cannot delete an active benchmark job")
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM aiopslab_events WHERE job_id = ?",
                    (job_id,),
                )
                connection.execute(
                    "DELETE FROM aiopslab_jobs WHERE job_id = ?",
                    (job_id,),
                )
        return existing

    def delete_terminal_jobs(self) -> tuple[str, ...]:
        """Delete all terminal benchmark jobs and return their identifiers."""

        terminal_statuses = tuple(
            status.value for status in ExperimentJobStatus if status.terminal
        )
        placeholders = ", ".join("?" for _ in terminal_statuses)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT job_id FROM aiopslab_jobs
                WHERE status IN ({placeholders})
                ORDER BY rowid ASC
                """,
                terminal_statuses,
            ).fetchall()
            job_ids = tuple(row["job_id"] for row in rows)
            if job_ids:
                job_placeholders = ", ".join("?" for _ in job_ids)
                connection.execute(
                    f"DELETE FROM aiopslab_events WHERE job_id IN ({job_placeholders})",
                    job_ids,
                )
                connection.execute(
                    f"DELETE FROM aiopslab_jobs WHERE job_id IN ({job_placeholders})",
                    job_ids,
                )
        return job_ids

    def interrupt_nonterminal_jobs(self) -> tuple[str, ...]:
        statuses = (
            ExperimentJobStatus.QUEUED.value,
            ExperimentJobStatus.RUNNING.value,
            ExperimentJobStatus.CANCELLING.value,
        )
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id FROM aiopslab_jobs
                WHERE status IN (?, ?, ?)
                ORDER BY rowid ASC
                """,
                statuses,
            ).fetchall()
            job_ids = tuple(row["job_id"] for row in rows)
            if job_ids:
                now = _now()
                connection.execute(
                    """
                    UPDATE aiopslab_jobs
                    SET status = ?, current_stage = ?, updated_at = ?,
                        finished_at = ?, error = ?
                    WHERE status IN (?, ?, ?)
                    """,
                    (
                        ExperimentJobStatus.INTERRUPTED.value,
                        RuntimeStage.CLEANUP.value,
                        now,
                        now,
                        "server restarted while the benchmark was nonterminal",
                        *statuses,
                    ),
                )
        return job_ids

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS aiopslab_jobs (
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
                );
                CREATE TABLE IF NOT EXISTS aiopslab_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, sequence),
                    FOREIGN KEY (job_id)
                        REFERENCES aiopslab_jobs(job_id)
                        ON DELETE CASCADE
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _required(self, job_id: str) -> AIOpsLabBenchmarkJob:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"AIOpsLab benchmark job not found: {job_id}")
        return job


def _job_from_row(row: sqlite3.Row) -> AIOpsLabBenchmarkJob:
    request_data = json.loads(row["request_json"])
    request = AIOpsLabBenchmarkRequest(**request_data)
    result_data = json.loads(row["result_json"]) if row["result_json"] else None
    result = MappingProxyType(result_data) if result_data is not None else None
    return AIOpsLabBenchmarkJob(
        job_id=row["job_id"],
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
