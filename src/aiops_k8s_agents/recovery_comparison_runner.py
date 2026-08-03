from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Condition, Event, RLock, Thread
from typing import Any, Callable, Mapping
from uuid import uuid4

from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.experiment_runtime_models import RuntimeEvent, RuntimeStage
from aiops_k8s_agents.recovery_comparison_jobs import (
    RecoveryComparisonJob,
    RecoveryComparisonRequest,
    SQLiteRecoveryComparisonJobStore,
)
from aiops_k8s_agents.recovery_experiments import (
    analyze_recovery_outcomes,
    load_recovery_outcomes,
    write_recovery_analysis,
)
from aiops_k8s_agents.recovery_runner import (
    load_recovery_experiment_config,
    run_recovery_matrix,
    run_recovery_treatment,
)
from aiops_k8s_agents.recovery_statistics import (
    summarize_recovery_statistics,
    write_recovery_statistics,
)


ComparisonEmitter = Callable[[RuntimeStage, str, Mapping[str, Any]], None]


class RecoveryComparisonCancelled(RuntimeError):
    pass


class RecoveryComparisonExecutor:
    """Runs one bounded 4-scenario x 3-action comparison matrix."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        config_path: str | Path,
        prometheus_url: str | None = None,
        kubeconfig: str | Path | None = None,
        matrix_runner: Callable[..., dict[str, Any]] = run_recovery_matrix,
        treatment_runner: Callable[..., dict[str, Any]] = run_recovery_treatment,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.config_path = Path(config_path).expanduser().resolve()
        self.prometheus_url = (
            prometheus_url
            or os.environ.get("PROMETHEUS_URL")
            or "http://127.0.0.1:9091"
        )
        self.kubeconfig = Path(
            kubeconfig
            or os.environ.get("KUBECONFIG")
            or self.repo_root / "config" / "missing-kubeconfig"
        ).expanduser()
        self.matrix_runner = matrix_runner
        self.treatment_runner = treatment_runner
        self.environ = dict(os.environ if environ is None else environ)

    def readiness(self, mode: str = "mock") -> dict[str, Any]:
        mode = str(mode).strip().lower()
        if mode == "mock":
            return {
                "ready": True,
                "mode": "mock",
                "evidence_type": "synthetic_mock",
                "reasons": [],
            }
        reasons: list[str] = []
        if mode != "real":
            reasons.append("comparison mode must be mock or real")
        if not self.config_path.is_file():
            reasons.append(f"comparison config not found: {self.config_path}")
        if not self.kubeconfig.is_file():
            reasons.append(f"kubeconfig not found: {self.kubeconfig}")
        if shutil.which("kubectl") is None:
            reasons.append("kubectl executable not found")
        if not self.prometheus_url:
            reasons.append("PROMETHEUS_URL is not configured")
        if not self.environ.get("NETWORK_LATENCY_QUERY"):
            reasons.append("NETWORK_LATENCY_QUERY is not configured")
        return {
            "ready": not reasons,
            "mode": mode,
            "evidence_type": "real_cluster",
            "reasons": reasons,
        }

    def execute(
        self,
        *,
        job_id: str,
        request: RecoveryComparisonRequest,
        output_dir: str | Path,
        cancellation: Event,
        emit: ComparisonEmitter,
    ) -> dict[str, Any]:
        readiness = self.readiness(request.mode)
        if not readiness["ready"]:
            raise RuntimeError("; ".join(readiness["reasons"]))
        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        outcomes_path = destination / "outcomes.jsonl"
        total = request.repetitions * 4 * 3
        emit(
            RuntimeStage.PREFLIGHT,
            "Recovery comparison preflight completed",
            {
                "mode": request.mode,
                "evidence_type": readiness["evidence_type"],
                "total_treatments": total,
            },
        )
        if cancellation.is_set():
            raise RecoveryComparisonCancelled("comparison cancelled before execution")

        if request.mode == "mock":
            matrix = _write_synthetic_matrix(
                outcomes_path,
                repetitions=request.repetitions,
                cancellation=cancellation,
                emit=emit,
            )
        else:
            matrix = self._run_real_matrix(
                request=request,
                outcomes_path=outcomes_path,
                cancellation=cancellation,
                emit=emit,
            )
        if cancellation.is_set():
            raise RecoveryComparisonCancelled("comparison cancelled")

        emit(
            RuntimeStage.ANALYZING,
            "Generating reward analysis and quantitative charts",
            {"completed_treatments": matrix["total_treatments"]},
        )
        outcomes = load_recovery_outcomes(outcomes_path)
        analysis = analyze_recovery_outcomes(outcomes)
        analysis_dir = destination / "analysis"
        write_recovery_analysis(analysis, analysis_dir)
        statistics = summarize_recovery_statistics(outcomes_path)
        statistics_dir = destination / "statistics"
        write_recovery_statistics(statistics, statistics_dir)
        artifacts = _artifact_paths(destination)
        emit(
            RuntimeStage.COMPLETED,
            "Recovery comparison artifacts completed",
            {
                "completed_treatments": matrix["total_treatments"],
                "artifact_count": len(artifacts),
            },
        )
        return {
            "job_id": job_id,
            "mode": request.mode,
            "guard_backend": request.guard_backend,
            "evidence_type": readiness["evidence_type"],
            "total_treatments": matrix["total_treatments"],
            "valid_measurements": matrix["valid_measurements"],
            "successful_recoveries": matrix["successful_recoveries"],
            "statistics": statistics,
            "analysis": analysis,
            "artifacts": artifacts,
        }

    def _run_real_matrix(
        self,
        *,
        request: RecoveryComparisonRequest,
        outcomes_path: Path,
        cancellation: Event,
        emit: ComparisonEmitter,
    ) -> dict[str, Any]:
        config = load_recovery_experiment_config(self.config_path)
        completed = 0
        total = request.repetitions * len(config.scenarios) * len(config.actions)

        def tracked_treatment(**kwargs: Any) -> dict[str, Any]:
            nonlocal completed
            if cancellation.is_set():
                raise RecoveryComparisonCancelled("comparison cancelled")
            treatment = kwargs["treatment"]
            emit(
                RuntimeStage.INJECTING_FAULT,
                f"Running {treatment.treatment_id}",
                {
                    "treatment_id": treatment.treatment_id,
                    "completed_treatments": completed,
                    "total_treatments": total,
                },
            )
            record = self.treatment_runner(**kwargs)
            completed += 1
            emit(
                RuntimeStage.OBSERVING_RECOVERY,
                f"Completed {treatment.treatment_id}",
                {
                    "treatment_id": treatment.treatment_id,
                    "completed_treatments": completed,
                    "total_treatments": total,
                    "measurement_valid": bool(record.get("measurement_valid")),
                    "recovery_success": bool(record.get("recovery_success")),
                },
            )
            return record

        return self.matrix_runner(
            config=config,
            repetitions=request.repetitions,
            mode="real",
            guard_backend=request.guard_backend,
            prometheus_url=self.prometheus_url,
            output_path=outcomes_path,
            treatment_runner=tracked_treatment,
            environ=self.environ,
        )


class RecoveryComparisonJobRunner:
    def __init__(
        self,
        store: SQLiteRecoveryComparisonJobStore,
        executor: Any,
        *,
        artifact_root: str | Path,
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.executor = executor
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.job_id_factory = job_id_factory or (
            lambda: f"cmp-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        )
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._threads: dict[str, Thread] = {}
        self._cancellations: dict[str, Event] = {}
        self.store.interrupt_nonterminal_jobs()

    def submit(self, request: RecoveryComparisonRequest) -> RecoveryComparisonJob:
        job = self.store.create(request, job_id=self.job_id_factory())
        cancellation = Event()
        thread = Thread(
            target=self._run_job,
            args=(job.job_id, cancellation),
            name=f"aiops-comparison-{job.job_id}",
            daemon=True,
        )
        with self._condition:
            self._threads[job.job_id] = thread
            self._cancellations[job.job_id] = cancellation
            thread.start()
            self._condition.notify_all()
        return job

    def cancel(self, job_id: str) -> RecoveryComparisonJob:
        job = self.store.request_cancel(job_id)
        with self._condition:
            cancellation = self._cancellations.get(job_id)
            if cancellation is not None:
                cancellation.set()
            self._condition.notify_all()
        return job

    def wait_for_events(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 15.0,
    ) -> tuple[RuntimeEvent, ...]:
        events = self.store.events_after(job_id, after_sequence)
        if events:
            return events
        job = self.store.get(job_id)
        if job is None or job.status.terminal:
            return ()
        with self._condition:
            self._condition.wait(timeout=max(0.0, timeout))
        return self.store.events_after(job_id, after_sequence)

    def shutdown(self, wait: bool = True) -> None:
        with self._condition:
            active = tuple(self._threads.items())
            for job_id, _ in active:
                cancellation = self._cancellations.get(job_id)
                if cancellation is not None:
                    cancellation.set()
            self._condition.notify_all()
        if wait:
            for _, thread in active:
                thread.join(timeout=5.0)

    def _run_job(self, job_id: str, cancellation: Event) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        self.store.transition(job_id, ExperimentJobStatus.RUNNING)
        emitter = _ComparisonEventEmitter(job_id, self.store, self._notify)
        status = ExperimentJobStatus.COMPLETED
        result: dict[str, Any] = {}
        error = ""
        try:
            result = dict(
                self.executor.execute(
                    job_id=job_id,
                    request=job.request,
                    output_dir=self.artifact_root / job_id,
                    cancellation=cancellation,
                    emit=emitter.emit,
                )
            )
            if cancellation.is_set():
                status = ExperimentJobStatus.CANCELLED
        except RecoveryComparisonCancelled as exc:
            status = ExperimentJobStatus.CANCELLED
            error = str(exc)
        except Exception as exc:
            status = (
                ExperimentJobStatus.CANCELLED
                if cancellation.is_set()
                else ExperimentJobStatus.FAILED
            )
            error = str(exc)
        finally:
            self.store.set_result(job_id, status=status, result=result, error=error)
            with self._condition:
                self._threads.pop(job_id, None)
                self._cancellations.pop(job_id, None)
                self._condition.notify_all()

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()


class _ComparisonEventEmitter:
    def __init__(
        self,
        job_id: str,
        store: SQLiteRecoveryComparisonJobStore,
        notify: Callable[[], None],
    ) -> None:
        self.job_id = job_id
        self.store = store
        self.notify = notify
        self.sequence = 0

    def emit(
        self,
        stage: RuntimeStage,
        message: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.sequence += 1
        event = RuntimeEvent(
            experiment_id=self.job_id,
            sequence=self.sequence,
            stage=stage,
            status="completed" if stage is RuntimeStage.COMPLETED else "running",
            message=message,
            created_at=datetime.now(UTC).isoformat(),
            payload=dict(payload),
        )
        self.store.append_event(event)
        self.notify()


def _write_synthetic_matrix(
    path: Path,
    *,
    repetitions: int,
    cancellation: Event,
    emit: ComparisonEmitter,
) -> dict[str, Any]:
    scenarios = ("pod-kill", "cpu-stress", "memory-stress", "network-delay")
    actions = ("observe_only", "rollout_restart", "scale_out")
    success_patterns = {
        ("pod-kill", "observe_only"): (1, 1, 1),
        ("pod-kill", "rollout_restart"): (1, 1, 1),
        ("pod-kill", "scale_out"): (1, 1, 0),
        ("cpu-stress", "observe_only"): (1, 0, 0),
        ("cpu-stress", "rollout_restart"): (1, 1, 0),
        ("cpu-stress", "scale_out"): (1, 1, 1),
        ("memory-stress", "observe_only"): (0, 1, 0),
        ("memory-stress", "rollout_restart"): (1, 1, 1),
        ("memory-stress", "scale_out"): (1, 1, 0),
        ("network-delay", "observe_only"): (0, 1, 0),
        ("network-delay", "rollout_restart"): (1, 1, 1),
        ("network-delay", "scale_out"): (1, 0, 1),
    }
    recovery_seconds = {
        "observe_only": 14.0,
        "rollout_restart": 9.0,
        "scale_out": 11.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    total = repetitions * len(scenarios) * len(actions)
    with path.open("w", encoding="utf-8") as handle:
        for repetition in range(1, repetitions + 1):
            for scenario in scenarios:
                for action in actions:
                    if cancellation.is_set():
                        raise RecoveryComparisonCancelled("comparison cancelled")
                    success = success_patterns[(scenario, action)][repetition - 1]
                    seconds = recovery_seconds[action] + (repetition - 1) * 0.4
                    record = {
                        "treatment_id": f"{scenario}__{action}__repeat-{repetition:02d}",
                        "scenario": scenario,
                        "action": {
                            "namespace": "online-boutique",
                            "deployment": "paymentservice",
                            "kind": action,
                            "replicas": 3 if action == "scale_out" else None,
                            "reason": "synthetic mock comparison; not real evidence",
                        },
                        "recovery_success": float(success),
                        "availability_recovery": 0.95 if success else 0.35,
                        "metric_improvement": (
                            0.88 if success and action != "observe_only" else 0.62 * success
                        ),
                        "recovery_seconds": seconds if success else seconds * 1.8,
                        "replica_delta": 2 if action == "scale_out" else 0,
                        "command_count": 0 if action == "observe_only" else 1,
                        "safety_valid": True,
                        "measurement_valid": True,
                        "evidence_type": "synthetic_mock",
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    records.append(record)
                    emit(
                        RuntimeStage.OBSERVING_RECOVERY,
                        f"Synthetic treatment completed: {record['treatment_id']}",
                        {
                            "treatment_id": record["treatment_id"],
                            "completed_treatments": len(records),
                            "total_treatments": total,
                            "synthetic": True,
                        },
                    )
    return {
        "total_treatments": len(records),
        "valid_measurements": len(records),
        "successful_recoveries": sum(
            1 for record in records if record["recovery_success"]
        ),
    }


def _artifact_paths(root: Path) -> dict[str, str]:
    candidates = {
        "outcomes_jsonl": root / "outcomes.jsonl",
        "reward_markdown": root / "analysis" / "reward_policy_comparison.md",
        "reward_csv": root / "analysis" / "reward_policy_comparison.csv",
        "reward_json": root / "analysis" / "reward_policy_comparison.json",
        "quantitative_markdown": root / "statistics" / "quantitative_summary.md",
        "quantitative_json": root / "statistics" / "quantitative_summary.json",
        "scenario_action_csv": root / "statistics" / "scenario_action_statistics.csv",
        "policy_reward_csv": root / "statistics" / "policy_reward_statistics.csv",
        "success_rate_png": root / "statistics" / "success_rate_by_action.png",
        "success_rate_svg": root / "statistics" / "success_rate_by_action.svg",
        "recovery_seconds_png": root / "statistics" / "mean_recovery_seconds_by_action.png",
        "recovery_seconds_svg": root / "statistics" / "mean_recovery_seconds_by_action.svg",
        "reward_policy_png": root / "statistics" / "reward_by_policy.png",
        "reward_policy_svg": root / "statistics" / "reward_by_policy.svg",
    }
    return {name: str(path) for name, path in candidates.items() if path.is_file()}
