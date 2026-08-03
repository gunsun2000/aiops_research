from __future__ import annotations

import os
import subprocess
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
from aiops_k8s_agents.experiment_runtime_factory import build_experiment_runtime
from aiops_k8s_agents.experiment_runtime import RuntimePreflightResult
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.real_evidence import RuntimeConfiguration, load_runtime_configuration
from aiops_k8s_agents.research_protocol import load_protocol_profiles

try:
    from fastapi import APIRouter, FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover - exercised at runtime.
    raise RuntimeError(
        "Control Plane UI dependencies are not installed. "
        'Run: python -m pip install -e ".[ui]"'
    ) from exc


STATIC_DIR = project_root() / "ui" / "control_plane_static"

RuntimeProbe = Callable[[], bool | Mapping[str, Any]]


@dataclass(frozen=True)
class RuntimeApiState:
    configuration: RuntimeConfiguration
    protocol_profiles: Mapping[str, Any]
    runtime_factory: Callable[[], Any]
    connection_probes: Mapping[str, RuntimeProbe]


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


@router.get("/api/experiments/{experiment_id}")
def api_experiment(experiment_id: str) -> dict[str, object]:
    session = get_experiment_session(experiment_id)
    if session is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return session.to_dict()


@router.get("/api/artifacts/{relative_path:path}")
def api_artifact(relative_path: str) -> FileResponse:
    try:
        path = artifact_path(relative_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@router.get("/api/platform")
def api_platform(request: Request) -> dict[str, object]:
    state: RuntimeApiState = request.app.state.runtime_api
    configuration = state.configuration
    connection_result = api_connections(request)
    real_missing = connection_result["missing_prerequisites"]
    return {
        "api_version": "1.0",
        "runtime_boundary": "preflight_only",
        "capabilities": {
            "persistent_jobs": False,
            "real_runtime": True,
            "fault_injection_api": False,
            "kubernetes_mutation": False,
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
                "required_connections": _connection_names(state),
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
    connections: dict[str, dict[str, object]] = {}
    for name in _connection_names(state):
        try:
            result = state.connection_probes[name]()
            ready = result if isinstance(result, bool) else result.get("ready", False)
        except Exception:
            ready = False
        connections[name] = {
            "ready": bool(ready),
            "required_for_real": True,
        }
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
    if request.protocol_profile.strip() not in state.protocol_profiles:
        raise HTTPException(status_code=400, detail="protocol profile is not registered")

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
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    missing: list[str] = []
    preflight_payload: dict[str, object] | None = None
    if runtime_request.mode is ExecutionMode.REAL:
        connection_result = api_connections(http_request)
        missing = list(connection_result["missing_prerequisites"])
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


def _default_connection_probes(root: Path, prometheus_url: str) -> dict[str, RuntimeProbe]:
    return {
        "kubernetes": _default_probe(["kubectl", "get", "--raw=/version"]),
        "prometheus": _prometheus_probe(prometheus_url),
        "chaos_mesh": _default_probe(["kubectl", "api-resources"]),
        "autogen": lambda: (root / "config" / "protocol_profiles").is_dir(),
        "aiopslab": lambda: Path(os.environ.get("AIOPSLAB_ROOT", root / "AIOpsLab")).is_dir(),
        "artifact_directory": lambda: (root / "runs").is_dir(),
    }


def create_app(
    *,
    runtime_factory: Callable[[], Any] | None = None,
    connection_probes: Mapping[str, RuntimeProbe] | None = None,
    configuration_path: str | Path | None = None,
    prometheus_url: str | None = None,
) -> FastAPI:
    root = project_root()
    config_path = Path(configuration_path or root / "config" / "experiment_runtime.json")
    configuration = load_runtime_configuration(config_path)
    protocol_profiles = load_protocol_profiles(root / "config" / "protocol_profiles")
    factory = runtime_factory or (
        lambda: build_experiment_runtime(
            configuration_path=config_path,
            prometheus_url=prometheus_url or os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090"),
            event_sink=EmptyEventSink(),
        )
    )
    app_instance = FastAPI(
        title="AIOps 4-Agent Control Plane",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app_instance.state.runtime_api = RuntimeApiState(
        configuration=configuration,
        protocol_profiles=protocol_profiles,
        runtime_factory=factory,
        connection_probes=connection_probes or _default_connection_probes(
            root, prometheus_url or os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:9090")
        ),
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
