from __future__ import annotations

import json
from collections.abc import MutableMapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import (
    LegacyFederatedRoundPlanAdapter,
    PartitionPlanningRequest,
)
from aiops_k8s_agents.partition_models import FederatedRoundPlan
from aiops_k8s_agents.partition_repository import PartitionPlanRepository
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry


def write_partition_report(
    report: Mapping[str, Any], artifact_root: str | Path
) -> Path:
    plan_id = str(report["plan"]["plan_id"])
    output_directory = Path(artifact_root).expanduser().resolve() / plan_id
    output_path = output_directory / "report.json"
    persisted_report = dict(report)

    if _is_v2_report(persisted_report):
        repository = PartitionPlanRepository(artifact_root)
        normalized_request, partition_intent = _derive_planning_artifacts(persisted_report)
        repository.save(
            persisted_report,
            sidecars={
                "normalized_request.json": normalized_request,
                "partition_intent.json": partition_intent,
            },
            include_legacy_report=True,
        )
        if isinstance(report, MutableMapping):
            report["scheduling_handoff"] = persisted_report["scheduling_handoff"]
    else:
        _write_json(output_path, persisted_report)
    return output_path


def _is_v2_report(report: Mapping[str, Any]) -> bool:
    plan = report.get("plan")
    return (
        isinstance(plan, Mapping)
        and report.get("status") == "planned"
        and plan.get("valid") is True
        and bool(str(plan.get("deterministic_signature") or "").strip())
    )


def _derive_planning_artifacts(report: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = report.get("planning_request")
    if isinstance(request_payload, Mapping):
        request = PartitionPlanningRequest.from_dict(request_payload)
    else:
        round_plan = FederatedRoundPlan.from_dict(report["round_plan"])
        request = LegacyFederatedRoundPlanAdapter().adapt(round_plan)
    normalized_request = PartitionCommonProcessor().process(request)
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized_request.plan_type,
        normalized_request.approved_execution_mode.name,
    )
    return asdict(normalized_request), asdict(strategy.build_partition_intent(normalized_request))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
