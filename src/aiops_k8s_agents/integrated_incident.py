from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any, Mapping

from aiops_k8s_agents.aiopslab_benchmark import (
    AIOpsLabBenchmarkCatalog,
    AIOpsLabExecutionResult,
)
from aiops_k8s_agents.aiopslab_results import summarize_aiopslab_reports
from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    RuntimeEvent,
    RuntimeStage,
)
from aiops_k8s_agents.executor import ExecutionMode


class AIOpsLabIncidentAdapter:
    """Normalizes AIOpsLab detection into the shared experiment evidence contract."""

    def __init__(
        self,
        catalog: AIOpsLabBenchmarkCatalog,
        executor: Any,
        *,
        artifact_root: str | Path,
    ) -> None:
        self.catalog = catalog
        self.executor = executor
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    def prepare(
        self,
        request: ExperimentRuntimeRequest,
        *,
        experiment_id: str,
        repetition: int,
        cancellation: Event,
        event_sink: Any,
    ) -> Mapping[str, Any]:
        if request.incident_source != "aiopslab":
            raise ValueError("AIOpsLab adapter requires aiopslab incident source")
        spec = self.catalog.resolve(request.benchmark_id)
        if spec.namespace != request.namespace or spec.service != request.deployment:
            raise ValueError("AIOpsLab benchmark target does not match experiment target")

        self._emit(
            event_sink,
            experiment_id,
            RuntimeStage.ANALYZING,
            "AIOpsLab detection started",
            {"benchmark_id": spec.benchmark_id, "repetition": repetition},
        )
        if request.mode is not ExecutionMode.REAL:
            context = {
                "source": "aiopslab",
                "evidence_boundary": "synthetic_mock",
                "benchmark_id": spec.benchmark_id,
                "problem_id": spec.problem_id,
                "anomaly_detected": True,
                "accuracy": "Synthetic",
                "ttd_seconds": 0.0,
                "steps": 3,
                "final_reward": 3.1,
                "events": (
                    "AIOpsLab synthetic detection context for mock/dry-run",
                ),
                "log_summary": (
                    "Synthetic AIOpsLab evidence; no external benchmark was executed."
                ),
            }
        else:
            readiness = self.executor.readiness()
            if not readiness.get("ready"):
                raise RuntimeError(
                    "; ".join(readiness.get("reasons", ()))
                    or "AIOpsLab runtime is unavailable"
                )
            reports_dir = (
                self.artifact_root
                / experiment_id
                / f"repeat-{repetition:02d}"
                / "aiopslab"
            )
            execution: AIOpsLabExecutionResult = self.executor.execute(
                spec,
                job_id=experiment_id,
                repetition=repetition,
                output_dir=reports_dir,
                cancellation=cancellation,
            )
            summary = summarize_aiopslab_reports(reports_dir)
            if not summary.records:
                raise RuntimeError("AIOpsLab detection report could not be normalized")
            record = summary.records[-1]
            context = {
                "source": "aiopslab",
                "evidence_boundary": "real_aiopslab",
                "benchmark_id": spec.benchmark_id,
                "problem_id": spec.problem_id,
                "anomaly_detected": record.detection_accuracy == "Correct",
                "accuracy": record.detection_accuracy,
                "ttd_seconds": record.ttd,
                "steps": record.steps,
                "final_reward": record.final_reward,
                "phase_coverage": record.phase_coverage,
                "metric_exported": record.metric_exported,
                "report_path": str(execution.report_path),
                "events": (
                    f"AIOpsLab detection accuracy={record.detection_accuracy}",
                    f"AIOpsLab final state={record.final_state}",
                ),
                "log_summary": (
                    f"AIOpsLab problem {spec.problem_id}; TTD={record.ttd}; "
                    f"steps={record.steps}"
                ),
            }
        self._emit(
            event_sink,
            experiment_id,
            RuntimeStage.COLLECTING_EVIDENCE,
            "AIOpsLab detection normalized",
            context,
        )
        return context

    @staticmethod
    def _emit(
        sink: Any,
        experiment_id: str,
        stage: RuntimeStage,
        message: str,
        payload: Mapping[str, Any],
    ) -> None:
        sink.emit(RuntimeEvent(
            experiment_id=experiment_id,
            sequence=0,
            stage=stage,
            status="completed" if stage is RuntimeStage.COLLECTING_EVIDENCE else "running",
            message=message,
            created_at=datetime.now(UTC).isoformat(),
            payload=payload,
        ))
