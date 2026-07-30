from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

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

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover - exercised at runtime.
    raise RuntimeError(
        "Control Plane UI dependencies are not installed. "
        'Run: python -m pip install -e ".[ui]"'
    ) from exc


STATIC_DIR = project_root() / "ui" / "control_plane_static"

app = FastAPI(
    title="AIOps 4-Agent Control Plane",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "aiops-control-plane"}


@app.get("/api/overview")
def api_overview() -> dict[str, object]:
    return build_overview()


@app.get("/api/agents")
def api_agents() -> dict[str, object]:
    return {"agents": agent_cards()}


@app.get("/api/scenarios")
def api_scenarios() -> dict[str, object]:
    return {"scenarios": scenario_catalog()}


@app.get("/api/runs/latest")
def api_latest_recovery_run() -> dict[str, object]:
    latest = latest_recovery_run()
    if latest is None:
        return {"available": False}
    return {"available": True, "run": latest}


@app.post("/api/mock-alert")
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


@app.post("/api/mutual-supervision/mock")
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


@app.post("/api/experiments/mock")
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


@app.get("/api/experiments/{experiment_id}")
def api_experiment(experiment_id: str) -> dict[str, object]:
    session = get_experiment_session(experiment_id)
    if session is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return session.to_dict()


@app.get("/api/artifacts/{relative_path:path}")
def api_artifact(relative_path: str) -> FileResponse:
    try:
        path = artifact_path(relative_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


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
