from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from orchestrator_agent.federated_coordination_adapter import (
    FederatedCoordinationPlanV04,
    load_mapping_context_providers,
    participant_context_from_fca_snapshot,
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
from orchestrator_agent.scheduling_handoff import (
    SchedulingAgentClient,
    SchedulingDeliveryError,
    to_scheduling_request,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(
    *,
    policy_path: str | Path | None = None,
    artifact_root: str | Path | None = None,
    example_root: str | Path | None = None,
    static_root: str | Path | None = None,
    ranker_root: str | Path | None = None,
    context_path: str | Path | None = None,
    scheduler_url: str = "http://127.0.0.1:18300",
    scheduler_client: Any | None = None,
    scheduler_timeout_seconds: float = 30.0,
    handoff_output_path: str | Path | None = None,
    prepare_only: bool = False,
) -> FastAPI:
    policy = Path(policy_path or PROJECT_ROOT / "config" / "model_partition_policy.json")
    artifacts = Path(artifact_root or PROJECT_ROOT / "runs" / "model-partition")
    examples = Path(example_root or PROJECT_ROOT / "config" / "examples")
    static = Path(static_root or PROJECT_ROOT / "ui")
    rankers = Path(ranker_root or artifacts / "rankers")
    contexts = Path(
        context_path
        or os.environ.get(
            "ORCHESTRATOR_CONTEXT_PATH",
            PROJECT_ROOT
            / "config"
            / "examples"
            / "federated_coordination_context_v04.json",
        )
    )
    participant_provider, model_provider = load_mapping_context_providers(contexts)
    scheduler = scheduler_client or SchedulingAgentClient(
        scheduler_url, timeout_seconds=scheduler_timeout_seconds
    )
    handoff_path = Path(
        handoff_output_path
        or PROJECT_ROOT / "runs" / "scheduling-agent" / "latest.json"
    )
    live_jobs: dict[str, tuple[str, dict[str, Any]]] = {}
    live_lock = RLock()
    repository = PartitionPlanRepository(artifacts, policy_path=policy)

    app = FastAPI(
        title="Orchestrator-Agent API",
        version="0.1.0",
        description="Model partition planning, validation, and bounded repartitioning.",
    )

    @app.get("/healthz")
    @app.get("/api/v1/orchestrator/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "Orchestrator-Agent"}

    @app.post("/api/v1/orchestrator/plans")
    def create_live_coordination_plan(payload: Mapping[str, Any]) -> JSONResponse:
        try:
            parsed = FederatedCoordinationPlanV04.from_dict(payload)
            signature = _signature(payload)
            with live_lock:
                existing = live_jobs.get(parsed.plan_id)
                if existing is not None:
                    if existing[0] != signature:
                        return _agent_error(
                            409,
                            "PLAN_CONFLICT",
                            "coordination plan ID was reused with different input",
                        )
                    return JSONResponse(
                        status_code=200 if prepare_only else 202,
                        content=existing[1],
                        headers={
                            "X-Scheduling-Delivery": (
                                "prepared" if prepare_only else "accepted"
                            )
                        },
                    )
                live_participant_provider = participant_provider
                if isinstance(payload.get("system_snapshot"), Mapping):
                    dynamic_context = participant_context_from_fca_snapshot(parsed)
                    from orchestrator_agent.federated_coordination_adapter import (
                        MappingParticipantContextProvider,
                    )

                    live_participant_provider = MappingParticipantContextProvider(
                        dynamic_context
                    )
                report = run_federated_coordination_planning(
                    payload,
                    participant_provider=live_participant_provider,
                    model_provider=model_provider,
                    policy_path=policy,
                    artifact_root=artifacts,
                )
                scheduling_request = to_scheduling_request(report, payload)
                _write_json_atomic(scheduling_request, handoff_path)
                if not prepare_only:
                    scheduler.submit(
                        scheduling_request,
                        request_id=scheduling_request["request_id"],
                    )
                live_jobs[parsed.plan_id] = (signature, scheduling_request)
                return JSONResponse(
                    status_code=200 if prepare_only else 202,
                    content=scheduling_request,
                    headers={
                        "X-Scheduling-Delivery": (
                            "prepared" if prepare_only else "accepted"
                        )
                    },
                )
        except PartitionContractError as exc:
            return _agent_error(422, exc.code, exc.message)
        except SchedulingDeliveryError as exc:
            return _agent_error(
                503 if exc.retryable else 502,
                "SCHEDULING_AGENT_DELIVERY_FAILED",
                str(exc),
                retryable=exc.retryable,
            )
        except OSError as exc:
            return _agent_error(500, "HANDOFF_WRITE_FAILED", str(exc))

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

    @app.get("/api/plans")
    def list_plans() -> dict[str, list[dict[str, Any]]]:
        return {"plans": list(_partition_call(repository.list_summaries))}

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict[str, Any]:
        return _partition_call(repository.get, plan_id)

    @app.get("/api/plans/{plan_id}/download")
    def download_plan(plan_id: str) -> JSONResponse:
        report = _partition_call(repository.get, plan_id)
        safe_plan_id = "".join(
            character if character.isalnum() or character in "-_." else "_"
            for character in plan_id
        )
        return JSONResponse(
            content=report,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{safe_plan_id or "partition-plan"}.json"'
                )
            },
        )

    @app.get("/api/plans/{plan_id}/history")
    def get_history(plan_id: str) -> dict[str, list[dict[str, Any]]]:
        return {"plans": list(_partition_call(repository.history, plan_id))}

    @app.delete("/api/plans/{plan_id}")
    def delete_plan(plan_id: str) -> dict[str, str | bool]:
        _partition_call(repository.delete, plan_id)
        return {"deleted": True, "plan_id": plan_id}

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


def _signature(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_json_atomic(payload: Mapping[str, Any], target: Path) -> None:
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, target)


def _agent_error(
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": {},
            }
        },
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("ORCHESTRATOR_BIND_ADDRESS", "127.0.0.1")
    port = int(os.environ.get("PORT", "18200"))
    uvicorn.run(
        create_app(
            scheduler_url=os.environ.get(
                "SCHEDULING_AGENT_URL", "http://127.0.0.1:18300"
            ),
            scheduler_timeout_seconds=float(
                os.environ.get("SCHEDULING_AGENT_TIMEOUT_SECONDS", "30")
            ),
            handoff_output_path=os.environ.get("SCHEDULING_AGENT_INPUT_PATH"),
            prepare_only=os.environ.get("ORCHESTRATOR_PREPARE_ONLY", "").lower()
            in {"1", "true", "yes"},
        ),
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
