from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from orchestrator_agent.federated_coordination_adapter import (
    load_mapping_context_providers,
)
from orchestrator_agent.partition_models import PartitionContractError
from orchestrator_agent.partition_ranker_repository import PartitionRankerRepository
from orchestrator_agent.partition_repository import PartitionPlanRepository
from orchestrator_agent.partition_service import (
    run_federated_coordination_planning,
    run_partition_feedback,
    run_partition_planning,
)
from orchestrator_agent.partition_strategies import PartitionStrategyRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(
    *,
    policy_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
    example_root: str | Path | None = None,
    static_root: str | Path | None = None,
    ranker_root: str | Path | None = None,
) -> FastAPI:
    policy = Path(policy_path or PROJECT_ROOT / "config" / "model_partition_policy.json")
    artifacts = Path(artifact_root or PROJECT_ROOT / "runs" / "model-partition")
    examples = Path(example_root or PROJECT_ROOT / "config" / "examples")
    static = Path(static_root or PROJECT_ROOT / "ui")
    rankers = Path(ranker_root or artifacts / "rankers")
    repository = PartitionPlanRepository(artifacts, policy_path=policy)

    app = FastAPI(
        title="Orchestrator-Agent API",
        version="0.1.0",
        description="Model partition planning, validation, and bounded repartitioning.",
    )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "Orchestrator-Agent"}

    @app.get("/api/examples")
    def list_examples() -> dict[str, list[dict[str, str]]]:
        catalog = (
            ("fl-v04", "FL training", "federated_coordination_fl_v04.json"),
            ("sl-v04", "SL training", "federated_coordination_sl_v04.json"),
            (
                "inference-v04",
                "Distributed inference",
                "federated_coordination_inference_v04.json",
            ),
            ("native-inference", "Native inference request", "model_partition_inference_v2.json"),
            ("native-training", "Native training request", "model_partition_training_v2.json"),
        )
        return {
            "examples": [
                {"id": key, "name": name, "file": filename}
                for key, name, filename in catalog
                if (examples / filename).is_file()
            ]
        }

    @app.get("/api/examples/{example_id}")
    def get_example(example_id: str) -> dict[str, Any]:
        files = {item["id"]: item["file"] for item in list_examples()["examples"]}
        filename = files.get(example_id)
        if filename is None:
            raise HTTPException(status_code=404, detail="example not found")
        result = {"input": _read_json(examples / filename)}
        context_path = examples / "federated_coordination_context_v04.json"
        if example_id.endswith("v04") and context_path.is_file():
            result["context"] = _read_json(context_path)
        return result

    @app.post("/api/plans")
    def create_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
        request = payload.get("request", payload)
        if not isinstance(request, Mapping):
            raise HTTPException(status_code=400, detail="request must be a JSON object")
        return _partition_call(
            run_partition_planning,
            request,
            policy_path=policy,
            artifact_root=artifacts,
            observed=_mapping_or_none(payload.get("observed")),
            selection_mode=str(payload.get("selection_mode", "deterministic")),
            ranker_registry_root=rankers,
            ranker_model_version=_text_or_none(payload.get("ranker_model_version")),
        )

    @app.post("/api/coordination-plans")
    def create_coordination_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
        coordination = payload.get("coordination_plan")
        context = payload.get("context")
        if not isinstance(coordination, Mapping) or not isinstance(context, Mapping):
            raise HTTPException(
                status_code=400,
                detail="coordination_plan and context must be JSON objects",
            )
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(context, handle, ensure_ascii=False)
            context_path = Path(handle.name)
        try:
            participant_provider, model_provider = load_mapping_context_providers(
                context_path
            )
            return _partition_call(
                run_federated_coordination_planning,
                coordination,
                participant_provider=participant_provider,
                model_provider=model_provider,
                policy_path=policy,
                artifact_root=artifacts,
                observed=_mapping_or_none(payload.get("observed")),
                selection_mode=str(payload.get("selection_mode", "deterministic")),
                ranker_registry_root=rankers,
                ranker_model_version=_text_or_none(payload.get("ranker_model_version")),
            )
        finally:
            context_path.unlink(missing_ok=True)

    @app.get("/api/strategies")
    def list_strategies() -> dict[str, list[dict[str, Any]]]:
        registry = PartitionStrategyRegistry.default(policy)
        grouped: dict[str, dict[str, Any]] = {}
        for plan_type, mode, strategy in registry.entries:
            entry = grouped.setdefault(
                strategy.strategy_id,
                {
                    "strategy_id": strategy.strategy_id,
                    "strategy_version": strategy.strategy_version,
                    "plan_types": [],
                    "supported_modes": [],
                },
            )
            if plan_type not in entry["plan_types"]:
                entry["plan_types"].append(plan_type)
            if mode not in entry["supported_modes"]:
                entry["supported_modes"].append(mode)
        return {"strategies": list(grouped.values())}

    @app.get("/api/rankers")
    def list_rankers() -> dict[str, list[dict[str, Any]]]:
        if not rankers.exists():
            return {"rankers": []}
        return {
            "rankers": [artifact.to_dict() for artifact in PartitionRankerRepository(rankers).list()]
        }

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict[str, Any]:
        return _partition_call(repository.get, plan_id)

    @app.get("/api/plans/{plan_id}/history")
    def get_history(plan_id: str) -> dict[str, list[dict[str, Any]]]:
        return {"plans": list(_partition_call(repository.history, plan_id))}

    @app.post("/api/plans/{plan_id}/feedback")
    def feedback(plan_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _partition_call(
            run_partition_feedback,
            plan_id,
            payload,
            repository,
            policy,
            ranker_registry_root=rankers,
        )

    if static.is_dir():
        app.mount("/assets", StaticFiles(directory=static), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static / "index.html")

    return app


def _partition_call(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except PartitionContractError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return payload


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def main() -> None:
    import uvicorn

    host = os.environ.get("ORCHESTRATOR_BIND_ADDRESS", "127.0.0.1")
    port = int(os.environ.get("PORT", "18200"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
