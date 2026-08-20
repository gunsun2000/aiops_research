from __future__ import annotations

import json
from collections.abc import MutableMapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import LegacyFederatedRoundPlanAdapter
from aiops_k8s_agents.partition_models import FederatedRoundPlan, PartitionExecutionPlan
from aiops_k8s_agents.partition_repository import (
    PartitionPlanRepository,
    SchedulingHandoff,
)
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry


def write_partition_report(
    report: Mapping[str, Any], artifact_root: str | Path
) -> Path:
    plan_id = str(report["plan"]["plan_id"])
    output_directory = Path(artifact_root).expanduser().resolve() / plan_id
    output_path = output_directory / "report.json"
    persisted_report = dict(report)

    if _is_independently_validated(persisted_report):
        handoff = _scheduling_handoff(persisted_report)
        persisted_report["scheduling_handoff"] = handoff
        if isinstance(report, MutableMapping):
            report["scheduling_handoff"] = handoff
        _write_json(output_path, persisted_report)
        repository = PartitionPlanRepository(artifact_root)
        version_path = repository.save(persisted_report)
        normalized_request, partition_intent = _derive_planning_artifacts(persisted_report)
        _write_json(version_path.parent / "normalized_request.json", normalized_request)
        _write_json(version_path.parent / "partition_intent.json", partition_intent)
        _write_json(version_path.parent / "scheduling_handoff.json", handoff)
    else:
        _write_json(output_path, persisted_report)
    return output_path


def _is_independently_validated(report: Mapping[str, Any]) -> bool:
    plan = report.get("plan")
    validation = report.get("validation")
    return (
        isinstance(plan, Mapping)
        and isinstance(validation, Mapping)
        and report.get("status") == "planned"
        and plan.get("valid") is True
        and validation.get("valid") is True
        and bool(str(plan.get("deterministic_signature") or "").strip())
    )


def _derive_planning_artifacts(report: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    round_plan = FederatedRoundPlan.from_dict(report["round_plan"])
    request = LegacyFederatedRoundPlanAdapter().adapt(round_plan)
    normalized_request = PartitionCommonProcessor().process(request)
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized_request.plan_type,
        normalized_request.approved_execution_mode.name,
    )
    return asdict(normalized_request), asdict(strategy.build_partition_intent(normalized_request))


def _scheduling_handoff(report: Mapping[str, Any]) -> dict[str, Any]:
    existing = report.get("scheduling_handoff")
    if isinstance(existing, Mapping):
        return dict(existing)
    return SchedulingHandoff.create(
        PartitionExecutionPlan.from_dict(report["plan"]),
        id_factory=lambda: f"scheduling-handoff-{uuid4().hex}",
        clock=lambda: datetime.now(timezone.utc).isoformat(),
    ).to_dict()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
