from __future__ import annotations

import json
import importlib.util
import logging
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from urllib.error import URLError
from urllib.request import urlopen

from aiops_k8s_agents.control_plane_data import (
    agent_cards,
    artifact_path,
    build_overview,
    get_experiment_session,
    latest_recovery_run,
    project_root,
    run_mock_alert,
    run_mutual_supervision_mock,
    run_scenario_experiment_mock,
    scenario_catalog,
)
from aiops_k8s_agents.aiopslab_benchmark import (
    AIOpsLabBenchmarkCatalog,
    AIOpsLabBenchmarkExecutor,
    resolve_aiopslab_python,
)
from aiops_k8s_agents.aiopslab_job_runner import AIOpsLabJobRunner
from aiops_k8s_agents.aiopslab_jobs import (
    AIOpsLabBenchmarkRequest,
    SQLiteAIOpsLabJobStore,
)
from aiops_k8s_agents.experiment_runtime_factory import build_experiment_runtime
from aiops_k8s_agents.experiment_runtime import RuntimePreflightResult
from aiops_k8s_agents.experiment_job_runner import ExperimentJobRunner
from aiops_k8s_agents.integrated_incident import AIOpsLabIncidentAdapter
from aiops_k8s_agents.experiment_jobs import SQLiteExperimentJobStore
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.real_evidence import RuntimeConfiguration, load_runtime_configuration
from aiops_k8s_agents.recovery_comparison_jobs import (
    RecoveryComparisonRequest,
    SQLiteRecoveryComparisonJobStore,
)
from aiops_k8s_agents.recovery_comparison_runner import (
    RecoveryComparisonExecutor,
    RecoveryComparisonJobRunner,
)
from aiops_k8s_agents.research_protocol import load_protocol_profiles
from aiops_k8s_agents.prometheus_port_forward import (
    PrometheusPortForwardManager,
)
from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_repository import PartitionPlanRepository
from aiops_k8s_agents.partition_service import (
    run_partition_feedback,
    run_partition_planning,
)
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry

try:
    from fastapi import APIRouter, FastAPI, HTTPException, Request
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        StreamingResponse,
    )
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover - exercised at runtime.
    raise RuntimeError(
        "Control Plane UI dependencies are not installed. "
        'Run: python -m pip install -e ".[ui]"'
    ) from exc


STATIC_DIR = project_root() / "ui" / "control_plane_static"
LOGGER = logging.getLogger(__name__)

RuntimeProbe = Callable[[], bool | Mapping[str, Any]]


@dataclass(frozen=True)
class RuntimeApiState:
    configuration: RuntimeConfiguration
    protocol_profiles: Mapping[str, Any]
    runtime_factory: Callable[[], Any]
    connection_probes: Mapping[str, RuntimeProbe]
    job_store: SQLiteExperimentJobStore
    job_runner: ExperimentJobRunner
    experiment_artifact_root: Path
    aiopslab_catalog: AIOpsLabBenchmarkCatalog
    aiopslab_executor: Any
    aiopslab_job_store: SQLiteAIOpsLabJobStore
    aiopslab_job_runner: AIOpsLabJobRunner
    aiopslab_artifact_root: Path
    recovery_comparison_executor: Any
    recovery_comparison_job_store: SQLiteRecoveryComparisonJobStore
    recovery_comparison_job_runner: RecoveryComparisonJobRunner
    recovery_comparison_artifact_root: Path
    model_partition_service: Callable[..., dict[str, Any]]
    model_partition_policy_path: Path
    model_partition_artifact_root: Path
    model_partition_repository: PartitionPlanRepository
    model_partition_example_path: Path


class EmptyEventSink:
    def emit(self, _event: Any) -> None:
        return None


router = APIRouter()


class MockAlertRequest(BaseModel):
    namespace: str = Field(default="online-boutique", min_length=1)
    deployment: str = Field(default="paymentservice", min_length=1)
    metric: str = Field(default="cpu", min_length=1)
    value: float = 95.0
    threshold: float = 80.0
    min_replicas: int = 1
    max_replicas: int = 5
    backend: Literal["python", "go"] = "python"


class ScenarioExperimentRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    backend: Literal["python", "go"] = "python"


class ExperimentValidationRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    deployment: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    threshold: float
    mode: Literal["mock", "dry-run", "real"] = "mock"
    backend: Literal["python", "go"] = "python"
    protocol_profile: str = Field(min_length=1)
    repetitions: int = Field(default=1, ge=1)
    controller: Literal["deterministic", "autogen"] = "deterministic"
    model: str = ""
    incident_source: Literal["chaos_mesh", "aiopslab"] = "chaos_mesh"
    benchmark_id: str = ""
    action_policy: Literal["baseline", "learned"] = "baseline"


class ExperimentCreateRequest(ExperimentValidationRequest):
    real_confirmation: str = ""


class AIOpsLabBenchmarkCreateRequest(BaseModel):
    benchmark_id: str = Field(min_length=1)
    repetitions: int = Field(default=1, ge=1, le=12)


class RecoveryComparisonCreateRequest(BaseModel):
    repetitions: int = Field(default=1, ge=1, le=3)
    mode: Literal["mock", "real"] = "mock"
    guard_backend: Literal["python", "go"] = "python"
    real_confirmation: str = ""


class ModelPartitionPlanRequest(BaseModel):
    round_plan: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    observed: dict[str, Any] | None = None
    previous_plan: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    replan_attempt: int = Field(default=1, ge=1)


@router.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "aiops-control-plane"}


@router.get("/api/overview")
def api_overview() -> dict[str, object]:
    return build_overview()


@router.get("/api/agents")
def api_agents() -> dict[str, object]:
    return {"agents": agent_cards()}


@router.get("/api/scenarios")
def api_scenarios() -> dict[str, object]:
    return {"scenarios": scenario_catalog()}


@router.get("/api/model-partition/examples")
def api_model_partition_examples(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        round_plan = json.loads(
            state.model_partition_example_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="model partition example is unavailable",
        ) from exc
    return {
        "examples": [
            {
                "id": "two-participant-transformer",
                "name": "Two-participant transformer partition",
                "round_plan": round_plan,
                "scope": {
                    "selects_execution_mode": False,
                    "requires_approved_upstream_mode": True,
                    "produces": "PartitionExecutionPlan",
                },
            }
        ]
    }


@router.post("/api/model-partition/plans", response_model=None)
def api_model_partition_plan(
    body: ModelPartitionPlanRequest,
    request: Request,
) -> dict[str, Any] | JSONResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    if (body.round_plan is None) == (body.request is None):
        return _partition_error_response(
            PartitionContractError(
                "invalid_partition_request",
                "exactly one of round_plan or request must be provided",
            )
        )
    if (body.previous_plan is None) != (body.failure is None):
        return _partition_error_response(
            PartitionContractError(
                "incomplete_replan_context",
                "previous_plan and failure must be provided together",
            )
        )
    try:
        return state.model_partition_service(
            body.request or body.round_plan,
            policy_path=state.model_partition_policy_path,
            artifact_root=state.model_partition_artifact_root,
            observed=body.observed,
            previous_plan_payload=body.previous_plan,
            failure_payload=body.failure,
            replan_attempt=body.replan_attempt,
        )
    except PartitionContractError as exc:
        return _partition_error_response(exc)
    except ValueError as exc:
        return _partition_error_response(
            PartitionContractError("invalid_partition_request", str(exc))
        )
    except Exception:
        LOGGER.exception("Unexpected model partition planning failure")
        return _partition_internal_error()


@router.get("/api/model-partition/strategies")
def api_model_partition_strategies(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    registry = PartitionStrategyRegistry.default(state.model_partition_policy_path)
    strategies: dict[tuple[str, str], dict[str, Any]] = {}
    for plan_type, mode, strategy in registry.entries:
        key = (plan_type, strategy.strategy_id)
        item = strategies.setdefault(
            key,
            {
                "plan_type": plan_type,
                "strategy_id": strategy.strategy_id,
                "strategy_version": strategy.strategy_version,
                "policy_version": strategy.policy_version,
                "supported_modes": [],
            },
        )
        item["supported_modes"].append(mode)
    return {"strategies": list(strategies.values())}


@router.get("/api/model-partition/plans/{plan_id}", response_model=None)
def api_model_partition_plan_by_id(
    plan_id: str, request: Request
) -> dict[str, Any] | JSONResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        return state.model_partition_repository.get(plan_id)
    except PartitionContractError as exc:
        return _partition_error_response(exc)
    except Exception:
        LOGGER.exception("Unexpected model partition plan retrieval failure")
        return _partition_internal_error(plan_id)


@router.get("/api/model-partition/plans/{plan_id}/history", response_model=None)
def api_model_partition_plan_history(
    plan_id: str, request: Request
) -> dict[str, object] | JSONResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        return {"plans": list(state.model_partition_repository.history(plan_id))}
    except PartitionContractError as exc:
        return _partition_error_response(exc)
    except Exception:
        LOGGER.exception("Unexpected model partition history retrieval failure")
        return _partition_internal_error(plan_id)


@router.post("/api/model-partition/plans/{plan_id}/feedback", response_model=None)
def api_model_partition_feedback(
    plan_id: str, body: dict[str, Any], request: Request
) -> dict[str, Any] | JSONResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        return run_partition_feedback(
            plan_id,
            body,
            state.model_partition_repository,
            state.model_partition_policy_path,
        )
    except PartitionContractError as exc:
        return _partition_error_response(exc)
    except (TypeError, ValueError):
        return _partition_error_response(
            PartitionContractError(
                "invalid_partition_request", "feedback must be a valid JSON object"
            )
        )
    except Exception:
        LOGGER.exception("Unexpected model partition feedback failure")
        return _partition_internal_error(plan_id)


def _partition_error_response(error: PartitionContractError) -> JSONResponse:
    status_code = (
        404
        if error.code == "plan_not_found"
        else 409
        if error.code
        in {
            "feedback_plan_mismatch",
            "non_current_feedback_plan",
            "orphan_parent_plan",
            "non_immediate_parent_plan",
            "plan_id_reused",
            "plan_version_conflict",
        }
        else 400
    )
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.code, "message": error.message},
    )


def _partition_internal_error(plan_id: str | None = None) -> JSONResponse:
    content: dict[str, str] = {
        "error_code": "internal_error",
        "message": "model partition request could not be completed",
    }
    if plan_id:
        content["plan_id"] = plan_id
    return JSONResponse(status_code=500, content=content)


@router.get("/api/runs/latest")
def api_latest_recovery_run() -> dict[str, object]:
    latest = latest_recovery_run()
    if latest is None:
        return {"available": False}
    return {"available": True, "run": latest}


@router.post("/api/mock-alert")
def api_mock_alert(request: MockAlertRequest) -> dict[str, object]:
    try:
        return run_mock_alert(
            namespace=request.namespace,
            deployment=request.deployment,
            metric=request.metric,
            value=request.value,
            threshold=request.threshold,
            min_replicas=request.min_replicas,
            max_replicas=request.max_replicas,
            backend=request.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/mutual-supervision/mock")
def api_mutual_supervision_mock(
    request: MockAlertRequest,
) -> dict[str, object]:
    try:
        return run_mutual_supervision_mock(
            namespace=request.namespace,
            deployment=request.deployment,
            metric=request.metric,
            value=request.value,
            threshold=request.threshold,
            min_replicas=request.min_replicas,
            max_replicas=request.max_replicas,
            backend=request.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/experiments/mock")
def api_experiment_mock(
    request: ScenarioExperimentRequest,
) -> dict[str, object]:
    try:
        session = run_scenario_experiment_mock(
            scenario_id=request.scenario_id,
            backend=request.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@router.post("/api/experiments", status_code=202)
def api_create_experiment(
    request: ExperimentCreateRequest,
    http_request: Request,
) -> dict[str, object]:
    if request.mode == "real":
        if os.environ.get("CONFIRM_REAL_RUN") != "YES":
            raise HTTPException(
                status_code=403,
                detail="real execution is disabled on this server",
            )
        if request.real_confirmation.strip() != "EXECUTE REAL EXPERIMENT":
            raise HTTPException(
                status_code=400,
                detail="real_confirmation must be exactly EXECUTE REAL EXPERIMENT",
            )
    validated = api_validate_experiment(request, http_request)
    runtime_request = _runtime_request(validated["resolved"])
    state: RuntimeApiState = http_request.app.state.runtime_api
    try:
        job = state.job_runner.submit(runtime_request)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict()


@router.get("/api/experiments")
def api_experiment_jobs(
    request: Request,
    limit: int = 50,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        jobs = state.job_store.list(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"jobs": [job.to_dict() for job in jobs]}


@router.get("/api/experiments/{experiment_id}")
def api_experiment(experiment_id: str, request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    job = state.job_store.get(experiment_id)
    if job is not None:
        payload = job.to_dict()
        payload["events"] = [
            event.to_dict()
            for event in state.job_store.events_after(experiment_id)
        ]
        return payload
    session = get_experiment_session(experiment_id)
    if session is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return session.to_dict()


@router.delete("/api/experiments/{experiment_id}")
def api_delete_experiment(experiment_id: str, request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    job = state.job_store.get(experiment_id)
    if job is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if not job.status.terminal:
        raise HTTPException(status_code=409, detail="experiment is not terminal")
    try:
        artifacts = _experiment_artifact_paths(state, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    deleted_count = 0
    for path in artifacts:
        if not path.exists() and not path.is_symlink():
            continue
        if not path.is_file() and not path.is_symlink():
            raise HTTPException(
                status_code=409,
                detail="experiment artifact is not a file",
            )
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail="experiment artifact could not be deleted",
            ) from exc
        deleted_count += 1
    try:
        state.job_store.delete(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="experiment is not terminal") from exc
    return {
        "deleted": True,
        "experiment_id": experiment_id,
        "artifacts_deleted": deleted_count,
    }


@router.post("/api/experiments/{experiment_id}/cancel", status_code=202)
def api_cancel_experiment(
    experiment_id: str,
    request: Request,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        job = state.job_runner.cancel(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    return job.to_dict()


@router.get("/api/experiments/{experiment_id}/events")
def api_experiment_events(
    experiment_id: str,
    request: Request,
) -> StreamingResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    if state.job_store.get(experiment_id) is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    raw_cursor = request.headers.get("last-event-id", "0").strip() or "0"
    try:
        cursor = int(raw_cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
    if cursor < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be non-negative")

    def stream():
        nonlocal cursor
        while True:
            events = state.job_runner.wait_for_events(
                experiment_id,
                after_sequence=cursor,
                timeout=10.0,
            )
            for event in events:
                cursor = event.sequence
                yield _sse("runtime", event.to_dict(), event_id=event.sequence)
            job = state.job_store.get(experiment_id)
            if job is None:
                return
            if job.status.terminal:
                yield _sse("job", job.to_dict())
                return
            if not events:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/artifacts/{relative_path:path}")
def api_artifact(relative_path: str) -> FileResponse:
    try:
        path = artifact_path(relative_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@router.get("/api/benchmarks/aiopslab")
def api_aiopslab_benchmarks(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    return {
        "benchmarks": state.aiopslab_catalog.to_public_list(),
        "runtime": state.aiopslab_executor.readiness(),
        "boundary": (
            "AIOpsLab detection benchmark; separate from Chaos Mesh recovery jobs"
        ),
    }


@router.post("/api/benchmarks/aiopslab/jobs", status_code=202)
def api_create_aiopslab_job(
    payload: AIOpsLabBenchmarkCreateRequest,
    request: Request,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        benchmark_request = AIOpsLabBenchmarkRequest(
            benchmark_id=payload.benchmark_id,
            repetitions=payload.repetitions,
        )
        spec = state.aiopslab_catalog.resolve(benchmark_request.benchmark_id)
        spec.validate_request(benchmark_request)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip("'")) from exc
    readiness = state.aiopslab_executor.readiness()
    if not readiness.get("ready"):
        reasons = readiness.get("reasons", ["AIOpsLab runtime unavailable"])
        raise HTTPException(status_code=503, detail="; ".join(reasons))
    job = state.aiopslab_job_runner.submit(benchmark_request)
    return _aiopslab_job_payload(state, job)


@router.get("/api/benchmarks/aiopslab/jobs")
def api_aiopslab_jobs(request: Request, limit: int = 50) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        jobs = state.aiopslab_job_store.list(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"jobs": [_aiopslab_job_payload(state, job) for job in jobs]}


@router.delete("/api/benchmarks/aiopslab/jobs")
def api_delete_aiopslab_jobs(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    jobs = state.aiopslab_job_store.list(limit=1_000_000)
    deleted_job_ids = state.aiopslab_job_store.delete_terminal_jobs()
    artifacts_deleted = sum(
        _delete_aiopslab_artifacts(state, job_id) for job_id in deleted_job_ids
    )
    return {
        "deleted_count": len(deleted_job_ids),
        "deleted_job_ids": list(deleted_job_ids),
        "artifacts_deleted_count": artifacts_deleted,
        "skipped_active_count": sum(not job.status.terminal for job in jobs),
    }


@router.delete("/api/benchmarks/aiopslab/jobs/{job_id}")
def api_delete_aiopslab_job(job_id: str, request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    job = state.aiopslab_job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AIOpsLab benchmark job not found")
    if not job.status.terminal:
        raise HTTPException(
            status_code=409,
            detail="active benchmark job cannot be deleted; cancel it first",
        )
    try:
        state.aiopslab_job_store.delete(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AIOpsLab benchmark job not found") from exc
    artifacts_deleted = _delete_aiopslab_artifacts(state, job_id)
    return {
        "deleted": True,
        "job_id": job_id,
        "artifacts_deleted": artifacts_deleted,
    }


@router.get("/api/benchmarks/aiopslab/jobs/{job_id}")
def api_aiopslab_job(job_id: str, request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    job = state.aiopslab_job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AIOpsLab benchmark job not found")
    payload = _aiopslab_job_payload(state, job)
    payload["events"] = [
        event.to_dict()
        for event in state.aiopslab_job_store.events_after(job_id)
    ]
    return payload


@router.post("/api/benchmarks/aiopslab/jobs/{job_id}/cancel", status_code=202)
def api_cancel_aiopslab_job(job_id: str, request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        job = state.aiopslab_job_runner.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="AIOpsLab benchmark job not found",
        ) from exc
    return _aiopslab_job_payload(state, job)


@router.get("/api/benchmarks/aiopslab/jobs/{job_id}/events")
def api_aiopslab_job_events(job_id: str, request: Request) -> StreamingResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    if state.aiopslab_job_store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="AIOpsLab benchmark job not found")
    raw_cursor = request.headers.get("last-event-id", "0").strip() or "0"
    try:
        cursor = int(raw_cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
    if cursor < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be non-negative")

    def stream():
        nonlocal cursor
        while True:
            events = state.aiopslab_job_runner.wait_for_events(
                job_id,
                after_sequence=cursor,
                timeout=10.0,
            )
            for event in events:
                cursor = event.sequence
                yield _sse("benchmark", event.to_dict(), event_id=event.sequence)
            job = state.aiopslab_job_store.get(job_id)
            if job is None:
                return
            if job.status.terminal:
                yield _sse("job", _aiopslab_job_payload(state, job))
                return
            if not events:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/benchmarks/aiopslab/jobs/{job_id}/artifacts/{artifact_name}")
def api_aiopslab_artifact(
    job_id: str,
    artifact_name: str,
    request: Request,
) -> FileResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    path = _aiopslab_artifact_path(state, job_id, artifact_name)
    return FileResponse(path)


@router.get("/api/comparisons/recovery")
def api_recovery_comparison(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    return {
        "matrix": {"scenarios": 4, "actions": 3, "max_repetitions": 3},
        "runtime_modes": {
            "mock": state.recovery_comparison_executor.readiness("mock"),
            "real": state.recovery_comparison_executor.readiness("real"),
        },
        "boundary": (
            "mock uses synthetic comparison outcomes; only Ubuntu real mode "
            "produces cluster experiment evidence"
        ),
    }


@router.post("/api/comparisons/recovery/jobs", status_code=202)
def api_create_recovery_comparison_job(
    payload: RecoveryComparisonCreateRequest,
    request: Request,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    if payload.mode == "real":
        if os.environ.get("CONFIRM_REAL_RUN") != "YES":
            raise HTTPException(
                status_code=403,
                detail="real comparison is disabled on this server",
            )
        if payload.real_confirmation.strip() != "EXECUTE REAL COMPARISON":
            raise HTTPException(
                status_code=400,
                detail="real_confirmation must be exactly EXECUTE REAL COMPARISON",
            )
    comparison_request = RecoveryComparisonRequest(
        repetitions=payload.repetitions,
        mode=payload.mode,
        guard_backend=payload.guard_backend,
    )
    readiness = state.recovery_comparison_executor.readiness(
        comparison_request.mode
    )
    if not readiness.get("ready"):
        reasons = readiness.get("reasons", ["comparison runtime unavailable"])
        raise HTTPException(status_code=503, detail="; ".join(reasons))
    job = state.recovery_comparison_job_runner.submit(comparison_request)
    return _recovery_comparison_job_payload(state, job)


@router.get("/api/comparisons/recovery/jobs")
def api_recovery_comparison_jobs(
    request: Request,
    limit: int = 50,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        jobs = state.recovery_comparison_job_store.list(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "jobs": [_recovery_comparison_job_payload(state, job) for job in jobs]
    }


@router.get("/api/comparisons/recovery/jobs/{job_id}")
def api_recovery_comparison_job(
    job_id: str,
    request: Request,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    job = state.recovery_comparison_job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="comparison job not found")
    payload = _recovery_comparison_job_payload(state, job)
    payload["events"] = [
        event.to_dict()
        for event in state.recovery_comparison_job_store.events_after(job_id)
    ]
    return payload


@router.post("/api/comparisons/recovery/jobs/{job_id}/cancel", status_code=202)
def api_cancel_recovery_comparison_job(
    job_id: str,
    request: Request,
) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    try:
        job = state.recovery_comparison_job_runner.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="comparison job not found") from exc
    return _recovery_comparison_job_payload(state, job)


@router.get("/api/comparisons/recovery/jobs/{job_id}/events")
def api_recovery_comparison_events(
    job_id: str,
    request: Request,
) -> StreamingResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    if state.recovery_comparison_job_store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="comparison job not found")
    raw_cursor = request.headers.get("last-event-id", "0").strip() or "0"
    try:
        cursor = int(raw_cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
    if cursor < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be non-negative")

    def stream():
        nonlocal cursor
        while True:
            events = state.recovery_comparison_job_runner.wait_for_events(
                job_id,
                after_sequence=cursor,
                timeout=10.0,
            )
            for event in events:
                cursor = event.sequence
                yield _sse("comparison", event.to_dict(), event_id=event.sequence)
            job = state.recovery_comparison_job_store.get(job_id)
            if job is None:
                return
            if job.status.terminal:
                yield _sse("job", _recovery_comparison_job_payload(state, job))
                return
            if not events:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/api/comparisons/recovery/jobs/{job_id}/artifacts/{artifact_name}"
)
def api_recovery_comparison_artifact(
    job_id: str,
    artifact_name: str,
    request: Request,
) -> FileResponse:
    state: RuntimeApiState = request.app.state.runtime_api
    return FileResponse(
        _recovery_comparison_artifact_path(state, job_id, artifact_name)
    )


@router.get("/api/platform")
def api_platform(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    configuration = state.configuration
    connection_result = api_connections(request)
    real_missing = connection_result["missing_prerequisites"]
    return {
        "api_version": "1.0",
        "runtime_boundary": "persistent_bounded_jobs",
        "capabilities": {
            "persistent_jobs": True,
            "real_runtime": True,
            "fault_injection_api": True,
            "kubernetes_mutation": True,
            "sse_events": True,
            "cancellation": True,
            "deletion": True,
            "restart_recovery": "interrupt_nonterminal",
        },
        "runtime_modes": {
            "mock": {"ready": True, "external_prerequisites": []},
            "dry-run": {"ready": True, "external_prerequisites": []},
            "real": {
                # A platform probe has no scenario request, so it cannot prove
                # the registered manifest/resource-kind preflight.
                "ready": False,
                "external_prerequisites": True,
                "request_specific_preflight_required": True,
                "required_connections": _required_real_connections(state),
                "missing_prerequisites": real_missing,
                "safety_bounds": {
                    "min_replicas": configuration.min_replicas,
                    "max_replicas": configuration.max_replicas,
                },
            },
        },
    }


@router.get("/api/connections")
def api_connections(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    port_forward = getattr(request.app.state, "prometheus_port_forward", None)
    if port_forward is not None:
        port_forward.ensure_running()
    connections: dict[str, dict[str, object]] = {}
    required = set(_required_real_connections(state))
    for name in _connection_names(state):
        try:
            result = state.connection_probes[name]()
            ready = result if isinstance(result, bool) else result.get("ready", False)
            details = (
                {
                    key: str(result[key])
                    for key in ("status", "reason")
                    if key in result
                }
                if isinstance(result, Mapping)
                else {}
            )
        except Exception:
            ready = False
            details = {"status": "probe_failed", "reason": "readiness probe failed"}
        connections[name] = {
            "ready": bool(ready),
            "required_for_real": name in required,
            **details,
        }
    if port_forward is not None:
        connections["prometheus"]["port_forward"] = port_forward.status()
    missing = [
        name for name, result in connections.items()
        if not result["ready"] and result["required_for_real"]
    ]
    return {
        "read_only": True,
        "connections": connections,
        "missing_prerequisites": missing,
    }


@router.post("/api/experiments/validate")
def api_validate_experiment(
    request: ExperimentValidationRequest,
    http_request: Request,
) -> dict[str, object]:
    state: RuntimeApiState = http_request.app.state.runtime_api
    configuration = state.configuration
    scenario = configuration.scenarios.get(request.scenario_id.strip())
    if scenario is None or not scenario.is_fully_validated:
        raise HTTPException(status_code=400, detail="unknown scenario")

    if request.namespace.strip() not in configuration.allowed_namespaces:
        raise HTTPException(status_code=400, detail="namespace is outside the runtime allowlist")
    if request.deployment.strip() not in configuration.allowed_deployments:
        raise HTTPException(status_code=400, detail="deployment is outside the runtime allowlist")
    if request.namespace.strip() != scenario.namespace or request.deployment.strip() != scenario.deployment:
        raise HTTPException(status_code=400, detail="request target does not match registered scenario")
    metric = request.metric.strip().lower().replace("-", "_")
    if metric != scenario.metric or metric not in configuration.metric_queries:
        raise HTTPException(status_code=400, detail="metric does not match the registered scenario")
    if request.threshold != scenario.threshold:
        raise HTTPException(status_code=400, detail="threshold does not match the registered scenario")
    if request.incident_source != scenario.incident_source:
        raise HTTPException(
            status_code=400,
            detail="incident source does not match the registered scenario",
        )
    if request.benchmark_id.strip() != scenario.benchmark_id:
        raise HTTPException(
            status_code=400,
            detail="benchmark does not match the registered scenario",
        )
    if request.protocol_profile.strip() not in state.protocol_profiles:
        raise HTTPException(status_code=400, detail="protocol profile is not registered")
    profile = state.protocol_profiles[request.protocol_profile.strip()]
    expected_runtime = {
        "deterministic": "deterministic",
        "autogen": "autogen-round-robin",
    }[request.controller]
    active_runtimes = {
        binding.runtime for binding in profile.agents if binding.enabled
    }
    if active_runtimes != {expected_runtime}:
        raise HTTPException(
            status_code=400,
            detail=(
                "controller does not match protocol profile: "
                f"{request.controller} requires {expected_runtime} agent bindings"
            ),
        )
    if request.controller == "autogen":
        autogen_connection = api_connections(http_request)["connections"].get(
            "autogen", {"ready": False}
        )
        if not autogen_connection.get("ready"):
            reason = autogen_connection.get("reason", "runtime prerequisites are missing")
            raise HTTPException(
                status_code=400,
                detail=f"AutoGen runtime is not ready: {reason}",
            )
        if not request.model.strip():
            raise HTTPException(
                status_code=400,
                detail="AutoGen controller requires a model",
            )

    try:
        runtime_request = ExperimentRuntimeRequest(
            scenario_id=request.scenario_id,
            namespace=request.namespace,
            deployment=request.deployment,
            metric=request.metric,
            threshold=request.threshold,
            mode=ExecutionMode(request.mode),
            backend=ExecutionBackend(request.backend),
            protocol_profile=request.protocol_profile,
            repetitions=request.repetitions,
            controller=request.controller,
            model=request.model,
            incident_source=request.incident_source,
            benchmark_id=request.benchmark_id,
            detection_context={"action_policy": request.action_policy},
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    missing: list[str] = []
    preflight_payload: dict[str, object] | None = None
    if runtime_request.mode is ExecutionMode.REAL:
        connection_result = api_connections(http_request)
        required_connections = _required_real_connections(
            state, runtime_request.incident_source
        )
        missing = [
            name
            for name in required_connections
            if not connection_result["connections"].get(name, {}).get("ready")
        ]
        try:
            runtime = state.runtime_factory()
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="runtime preflight failed",
            ) from exc
        preflight = getattr(runtime, "preflight", None)
        if not callable(preflight):
            raise HTTPException(
                status_code=400,
                detail="runtime preflight contract unavailable",
            )
        try:
            result = preflight(runtime_request)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="runtime preflight failed",
            ) from exc
        if not isinstance(result, RuntimePreflightResult):
            raise HTTPException(
                status_code=400,
                detail="runtime preflight contract returned an invalid result",
            )
        preflight_payload = result.to_dict()
        missing.extend(result.missing_prerequisites)
        missing = list(dict.fromkeys(missing))
        if not result.valid or missing:
            detail = "missing prerequisites: " + ", ".join(missing or [
                "runtime.preflight",
            ])
            raise HTTPException(status_code=400, detail=detail)

    return {
        "validated": True,
        "read_only": True,
        "resolved": runtime_request.to_dict(),
        "scenario": {
            "scenario_id": scenario.scenario_id,
            "namespace": scenario.namespace,
            "deployment": scenario.deployment,
            "metric": scenario.metric,
            "threshold": scenario.threshold,
            "manifest": scenario.manifest,
            "incident_source": scenario.incident_source,
            "benchmark_id": scenario.benchmark_id,
        },
        "mode": runtime_request.mode.value,
        "controller": "mutual_supervision",
        "safety_bounds": {
            "min_replicas": configuration.min_replicas,
            "max_replicas": configuration.max_replicas,
            "experiment_seconds": configuration.experiment_seconds,
        },
        "missing_prerequisites": missing,
        "preflight": preflight_payload,
    }


def _connection_names(state: RuntimeApiState) -> tuple[str, ...]:
    return tuple(state.connection_probes)


def _required_real_connections(
    state: RuntimeApiState,
    incident_source: str = "chaos_mesh",
) -> tuple[str, ...]:
    source_connection = "aiopslab" if incident_source == "aiopslab" else "chaos_mesh"
    required = ("kubernetes", "prometheus", source_connection, "artifact_directory")
    return tuple(name for name in required if name in state.connection_probes)


def _runtime_request(data: Mapping[str, Any]) -> ExperimentRuntimeRequest:
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
        detection_context={
            **dict(data.get("detection_context", {})),
            "action_policy": data.get(
                "action_policy",
                dict(data.get("detection_context", {})).get(
                    "action_policy", "baseline"
                ),
            ),
        },
    )


def _sse(event: str, payload: Mapping[str, Any], event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(
        "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    return "\n".join(lines) + "\n\n"


def _experiment_artifact_paths(state: RuntimeApiState, job: Any) -> tuple[Path, ...]:
    if job.result is None:
        return ()
    result = dict(job.result)
    attempts = result.get("attempts", [])
    if not isinstance(attempts, (list, tuple)):
        return ()
    candidates: list[str] = []
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        report = attempt.get("report", {})
        if not isinstance(report, Mapping):
            continue
        artifacts = report.get("artifacts", {})
        if not isinstance(artifacts, Mapping):
            continue
        for candidate in artifacts.values():
            if isinstance(candidate, (str, Path)) and str(candidate).strip():
                candidates.append(str(candidate).strip())

    allowed_root = state.experiment_artifact_root.expanduser().resolve()
    repo_root = project_root().resolve()
    paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        raw = Path(candidate).expanduser()
        path = (raw if raw.is_absolute() else repo_root / raw).resolve()
        try:
            path.relative_to(allowed_root)
        except ValueError as exc:
            raise ValueError("experiment artifact is outside the allowed root") from exc
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return tuple(paths)


def _aiopslab_job_payload(state: RuntimeApiState, job: Any) -> dict[str, Any]:
    payload = job.to_dict()
    result = payload.get("result")
    if not isinstance(result, Mapping):
        payload["artifact_urls"] = {}
        return payload
    artifact_urls: dict[str, str] = {}
    artifacts = result.get("artifacts", {})
    for name in ("markdown", "csv"):
        if isinstance(artifacts, Mapping) and artifacts.get(name):
            artifact_urls[name] = (
                f"/api/benchmarks/aiopslab/jobs/{job.job_id}/artifacts/{name}"
            )
    reports = result.get("reports", [])
    if isinstance(reports, list):
        for index, _ in enumerate(reports, start=1):
            key = f"report-{index}"
            artifact_urls[key] = (
                f"/api/benchmarks/aiopslab/jobs/{job.job_id}/artifacts/{key}"
            )
    payload["artifact_urls"] = artifact_urls
    return payload


def _aiopslab_artifact_path(
    state: RuntimeApiState,
    job_id: str,
    artifact_name: str,
) -> Path:
    job = state.aiopslab_job_store.get(job_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="AIOpsLab artifact not found")
    result = dict(job.result)
    candidate: str | None = None
    artifacts = result.get("artifacts", {})
    if artifact_name in {"markdown", "csv"} and isinstance(artifacts, Mapping):
        candidate = artifacts.get(artifact_name)
    elif artifact_name.startswith("report-"):
        try:
            index = int(artifact_name.removeprefix("report-")) - 1
            reports = result.get("reports", [])
            candidate = reports[index]
        except (ValueError, IndexError, TypeError):
            candidate = None
    if not candidate:
        raise HTTPException(status_code=404, detail="AIOpsLab artifact not found")
    path = Path(candidate).expanduser().resolve()
    allowed_root = (state.aiopslab_artifact_root / job_id).resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="AIOpsLab artifact not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="AIOpsLab artifact not found")
    return path


def _delete_aiopslab_artifacts(state: RuntimeApiState, job_id: str) -> bool:
    root = state.aiopslab_artifact_root.resolve()
    candidate = (root / job_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    if candidate == root or not candidate.exists():
        return False
    shutil.rmtree(candidate)
    return True


def _recovery_comparison_job_payload(
    state: RuntimeApiState,
    job: Any,
) -> dict[str, Any]:
    payload = job.to_dict()
    result = payload.get("result")
    artifact_urls: dict[str, str] = {}
    if isinstance(result, Mapping):
        artifacts = result.get("artifacts", {})
        if isinstance(artifacts, Mapping):
            for name, path in artifacts.items():
                if path:
                    artifact_urls[str(name)] = (
                        f"/api/comparisons/recovery/jobs/{job.job_id}"
                        f"/artifacts/{name}"
                    )
    payload["artifact_urls"] = artifact_urls
    return payload


def _recovery_comparison_artifact_path(
    state: RuntimeApiState,
    job_id: str,
    artifact_name: str,
) -> Path:
    job = state.recovery_comparison_job_store.get(job_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="comparison artifact not found")
    artifacts = dict(job.result).get("artifacts", {})
    candidate = artifacts.get(artifact_name) if isinstance(artifacts, Mapping) else None
    if not candidate:
        raise HTTPException(status_code=404, detail="comparison artifact not found")
    path = Path(str(candidate)).expanduser().resolve()
    allowed_root = (state.recovery_comparison_artifact_root / job_id).resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="comparison artifact not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="comparison artifact not found")
    return path


def _default_probe(command: list[str]) -> RuntimeProbe:
    def probe() -> bool:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    return probe


def _prometheus_probe(url: str) -> RuntimeProbe:
    def probe() -> bool:
        try:
            with urlopen(url.rstrip("/") + "/-/ready", timeout=3) as response:
                return 200 <= response.status < 300
        except (OSError, URLError):
            return False

    return probe


def _chaos_mesh_probe() -> bool:
    try:
        completed = subprocess.run(
            ["kubectl", "api-resources", "--api-group=chaos-mesh.org", "--no-headers"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    resources = completed.stdout.lower()
    return all(
        resource in resources
        for resource in ("networkchaos", "podchaos", "stresschaos")
    )


def _aiopslab_probe(root: Path) -> bool:
    aiopslab_root = Path(
        os.environ.get("AIOPSLAB_ROOT", root.parent / "external" / "AIOpsLab")
    ).expanduser()
    python_executable = os.environ.get("AIOPSLAB_PYTHON", "").strip()
    if not aiopslab_root.is_dir() or not python_executable:
        return False
    python_path = Path(python_executable).expanduser()
    if not python_path.is_file():
        return False
    try:
        completed = subprocess.run(
            [str(python_path), "-c", "import aiopslab, rich"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _default_connection_probes(root: Path, prometheus_url: str) -> dict[str, RuntimeProbe]:
    return {
        "kubernetes": _default_probe(["kubectl", "get", "--raw=/version"]),
        "prometheus": _prometheus_probe(prometheus_url),
        "chaos_mesh": _chaos_mesh_probe,
        "autogen": _autogen_probe,
        "aiopslab": lambda: _aiopslab_probe(root),
        "artifact_directory": lambda: (root / "runs").is_dir(),
    }


def _autogen_probe() -> Mapping[str, Any]:
    packages_ready = all(
        _module_available(name)
        for name in ("autogen_agentchat", "autogen_ext.models.openai")
    )
    credentials_ready = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_ADMIN_KEY")
    )
    if not packages_ready:
        return {
            "ready": False,
            "status": "missing_packages",
            "reason": "AutoGen OpenAI packages are not installed",
        }
    if not credentials_ready:
        return {
            "ready": False,
            "status": "missing_credentials",
            "reason": "OpenAI credentials are not configured",
        }
    return {"ready": True, "status": "ready", "reason": "AutoGen runtime is ready"}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


def create_app(
    *,
    runtime_factory: Callable[[], Any] | None = None,
    job_runtime_factory: Callable[[Any, Any, str], Any] | None = None,
    job_database_path: str | Path | None = None,
    experiment_artifact_root: str | Path | None = None,
    connection_probes: Mapping[str, RuntimeProbe] | None = None,
    configuration_path: str | Path | None = None,
    prometheus_url: str | None = None,
    autogen_decision_provider_factory: Callable[[str], Any] | None = None,
    autogen_model_client_factory: Callable[[str], Any] | None = None,
    aiopslab_catalog_path: str | Path | None = None,
    aiopslab_executor: Any | None = None,
    aiopslab_artifact_root: str | Path | None = None,
    aiopslab_job_id_factory: Callable[[], str] | None = None,
    recovery_comparison_executor: Any | None = None,
    recovery_comparison_artifact_root: str | Path | None = None,
    recovery_comparison_job_id_factory: Callable[[], str] | None = None,
    prometheus_port_forward_manager: Any | None = None,
    model_partition_service: Callable[..., dict[str, Any]] | None = None,
    model_partition_policy_path: str | Path | None = None,
    model_partition_artifact_root: str | Path | None = None,
    model_partition_example_path: str | Path | None = None,
) -> FastAPI:
    root = project_root()
    config_path = Path(configuration_path or root / "config" / "experiment_runtime.json")
    configuration = load_runtime_configuration(config_path)
    protocol_profiles = load_protocol_profiles(root / "config" / "protocol_profiles")
    effective_prometheus_url = (
        prometheus_url
        or os.environ.get("PROMETHEUS_URL")
        or "http://127.0.0.1:9091"
    )
    port_forward = prometheus_port_forward_manager
    if port_forward is None and connection_probes is None:
        port_forward = PrometheusPortForwardManager.from_environment(
            effective_prometheus_url
        )
    factory = runtime_factory or (
        lambda: build_experiment_runtime(
            configuration_path=config_path,
            prometheus_url=effective_prometheus_url,
            event_sink=EmptyEventSink(),
            autogen_decision_provider_factory=autogen_decision_provider_factory,
            autogen_model_client_factory=autogen_model_client_factory,
        )
    )
    database_path = Path(
        job_database_path
        or os.environ.get(
            "AIOPS_JOB_DATABASE",
            root / "runs" / "control-plane" / "experiment-jobs.sqlite3",
        )
    )
    experiment_artifacts = Path(
        experiment_artifact_root or root / "runs"
    ).expanduser().resolve()
    job_store = SQLiteExperimentJobStore(database_path)
    runtime_builder = job_runtime_factory or (
        lambda event_sink, cancellation_event, experiment_id: build_experiment_runtime(
            configuration_path=config_path,
            prometheus_url=effective_prometheus_url,
            event_sink=event_sink,
            experiment_id_factory=lambda: experiment_id,
            cancellation_event=cancellation_event,
            autogen_decision_provider_factory=autogen_decision_provider_factory,
            autogen_model_client_factory=autogen_model_client_factory,
        )
    )
    benchmark_catalog = AIOpsLabBenchmarkCatalog.from_path(
        aiopslab_catalog_path or root / "config" / "aiopslab_benchmarks.json"
    )
    benchmark_executor = aiopslab_executor or AIOpsLabBenchmarkExecutor(
        repo_root=root,
        aiopslab_root=os.environ.get(
            "AIOPSLAB_ROOT",
            root.parent / "external" / "AIOpsLab",
        ),
        python_executable=resolve_aiopslab_python(),
        kubeconfig=os.environ.get(
            "KUBECONFIG",
            root / "config" / "missing-kubeconfig",
        ),
    )
    benchmark_artifact_root = Path(
        aiopslab_artifact_root
        or root / "runs" / "control-plane" / "aiopslab"
    ).expanduser().resolve()
    integrated_incident_adapter = AIOpsLabIncidentAdapter(
        benchmark_catalog,
        benchmark_executor,
        artifact_root=benchmark_artifact_root,
    )
    job_runner = ExperimentJobRunner(
        job_store,
        runtime_builder,
        incident_adapter=integrated_incident_adapter,
    )
    aiopslab_job_store = SQLiteAIOpsLabJobStore(database_path)
    aiopslab_job_runner = AIOpsLabJobRunner(
        aiopslab_job_store,
        benchmark_catalog,
        benchmark_executor,
        artifact_root=benchmark_artifact_root,
        job_id_factory=aiopslab_job_id_factory,
    )
    comparison_executor = recovery_comparison_executor or RecoveryComparisonExecutor(
        repo_root=root,
        config_path=root / "config" / "recovery_action_experiments.json",
        prometheus_url=effective_prometheus_url,
        kubeconfig=os.environ.get(
            "KUBECONFIG",
            root / "config" / "missing-kubeconfig",
        ),
    )
    comparison_artifact_root = Path(
        recovery_comparison_artifact_root
        or root / "runs" / "control-plane" / "recovery-comparison"
    ).expanduser().resolve()
    recovery_comparison_job_store = SQLiteRecoveryComparisonJobStore(database_path)
    recovery_comparison_job_runner = RecoveryComparisonJobRunner(
        recovery_comparison_job_store,
        comparison_executor,
        artifact_root=comparison_artifact_root,
        job_id_factory=recovery_comparison_job_id_factory,
    )
    partition_policy_path = Path(
        model_partition_policy_path or root / "config" / "model_partition_policy.json"
    ).expanduser().resolve()
    partition_artifact_root = Path(
        model_partition_artifact_root
        or root / "runs" / "control-plane" / "model-partition"
    ).expanduser().resolve()
    partition_repository = PartitionPlanRepository(partition_artifact_root)
    partition_example_path = Path(
        model_partition_example_path
        or root / "config" / "examples" / "model_partition_job.json"
    ).expanduser().resolve()
    probes = dict(
        connection_probes
        or _default_connection_probes(
            root,
            effective_prometheus_url,
        )
    )
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if port_forward is not None:
            port_forward.start()
        try:
            yield
        finally:
            if port_forward is not None:
                port_forward.stop()
            job_runner.shutdown(wait=True)
            aiopslab_job_runner.shutdown(wait=True)
            recovery_comparison_job_runner.shutdown(wait=True)

    app_instance = FastAPI(
        title="AIOps 4-Agent Control Plane",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app_instance.state.prometheus_port_forward = port_forward
    app_instance.state.runtime_api = RuntimeApiState(
        configuration=configuration,
        protocol_profiles=protocol_profiles,
        runtime_factory=factory,
        connection_probes=probes,
        job_store=job_store,
        job_runner=job_runner,
        experiment_artifact_root=experiment_artifacts,
        aiopslab_catalog=benchmark_catalog,
        aiopslab_executor=benchmark_executor,
        aiopslab_job_store=aiopslab_job_store,
        aiopslab_job_runner=aiopslab_job_runner,
        aiopslab_artifact_root=benchmark_artifact_root,
        recovery_comparison_executor=comparison_executor,
        recovery_comparison_job_store=recovery_comparison_job_store,
        recovery_comparison_job_runner=recovery_comparison_job_runner,
        recovery_comparison_artifact_root=comparison_artifact_root,
        model_partition_service=model_partition_service or run_partition_planning,
        model_partition_policy_path=partition_policy_path,
        model_partition_artifact_root=partition_artifact_root,
        model_partition_repository=partition_repository,
        model_partition_example_path=partition_example_path,
    )
    app_instance.include_router(router)
    app_instance.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app_instance


app = create_app()


def main() -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            'uvicorn is not installed. Run: python -m pip install -e ".[ui]"'
        ) from exc

    host = os.environ.get("AIOPS_BIND_ADDRESS", "127.0.0.1")
    port = int(os.environ.get("PORT", "18080"))
    uvicorn.run(
        "aiops_k8s_agents.control_plane_web:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
