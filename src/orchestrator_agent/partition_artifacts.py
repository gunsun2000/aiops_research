from __future__ import annotations

import hashlib
import json
from collections.abc import MutableMapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from orchestrator_agent.partition_common import PartitionCommonProcessor
from orchestrator_agent.partition_context import canonical_json
from orchestrator_agent.partition_coordination import (
    LegacyFederatedRoundPlanAdapter,
    PartitionPlanningRequest,
)
from orchestrator_agent.partition_models import FederatedRoundPlan
from orchestrator_agent.partition_repository import PartitionPlanRepository
from orchestrator_agent.partition_strategies import PartitionStrategyRegistry


def write_partition_report(
    report: Mapping[str, Any],
    artifact_root: str | Path,
    *,
    policy_path: str | Path | None = None,
    sidecars: Mapping[str, object] | None = None,
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
) -> Path:
    plan_id = str(report["plan"]["plan_id"])
    output_directory = Path(artifact_root).expanduser().resolve() / plan_id
    output_path = output_directory / "report.json"
    persisted_report = dict(report)

    if _is_v2_report(persisted_report):
        repository = PartitionPlanRepository(
            artifact_root,
            policy_path=policy_path,
            artifact_signing_key=artifact_signing_key,
            artifact_signing_key_file=artifact_signing_key_file,
        )
        normalized_request, partition_intent = _derive_planning_artifacts(
            persisted_report, policy_path=policy_path
        )
        repository_sidecars: dict[str, object] = {
            "normalized_request.json": normalized_request,
            "partition_intent.json": partition_intent,
            "candidate_ranking.json": dict(report["plan"]["selection"]),
        }
        if sidecars:
            repository_sidecars.update(sidecars)
        repository.save(
            persisted_report,
            sidecars=repository_sidecars,
            include_legacy_report=True,
        )
        if isinstance(report, MutableMapping):
            report["scheduling_handoff"] = persisted_report["scheduling_handoff"]
    else:
        _write_json(output_path, persisted_report)
    return output_path


def build_runtime_outcome_sidecar(report: Mapping[str, Any]) -> dict[str, object] | None:
    """Bind observed evaluation evidence to the selected persisted candidate."""
    evaluation = report.get("evaluation")
    plan = report.get("plan")
    if not isinstance(evaluation, Mapping) or evaluation.get("evidence_level") != "observed":
        return None
    if not isinstance(plan, Mapping):
        raise ValueError("observed runtime outcome requires a plan")
    selection = plan.get("selection")
    metrics = evaluation.get("metrics")
    components = evaluation.get("components")
    if not isinstance(selection, Mapping) or not isinstance(metrics, Mapping) or not isinstance(components, Mapping):
        raise ValueError("observed runtime outcome requires selection and evaluation details")
    payload: dict[str, object] = {
        "schema_version": "partition-runtime-outcome-v1",
        "plan_id": str(plan.get("plan_id") or "").strip(),
        "plan_version": plan.get("plan_version"),
        "selected_candidate_key": str(
            selection.get("final_selected_candidate_key") or ""
        ).strip(),
        "source": str(metrics.get("source") or "").strip(),
        "observed_at": str(metrics.get("observed_at") or "").strip(),
        "runtime_outcome_ref": str(metrics.get("runtime_outcome_ref") or "").strip(),
        "metrics": dict(metrics),
        "evaluation_reward": evaluation.get("reward"),
        "evaluation_components": dict(components),
    }
    if (
        not payload["plan_id"]
        or not isinstance(payload["plan_version"], int)
        or not payload["selected_candidate_key"]
        or not payload["source"]
        or not payload["observed_at"]
        or not payload["runtime_outcome_ref"]
    ):
        return None
    return {
        **payload,
        "payload_sha256": hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    }


def _is_v2_report(report: Mapping[str, Any]) -> bool:
    plan = report.get("plan")
    return (
        isinstance(plan, Mapping)
        and report.get("status") == "planned"
        and plan.get("valid") is True
        and bool(str(plan.get("deterministic_signature") or "").strip())
    )


def _derive_planning_artifacts(
    report: Mapping[str, Any], *, policy_path: str | Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = report.get("planning_request")
    if isinstance(request_payload, Mapping):
        request = PartitionPlanningRequest.from_dict(request_payload)
    else:
        round_plan = FederatedRoundPlan.from_dict(report["round_plan"])
        request = LegacyFederatedRoundPlanAdapter().adapt(round_plan)
    normalized_request = PartitionCommonProcessor().process(request)
    strategy = PartitionStrategyRegistry.default(
        None if policy_path is None else Path(policy_path)
    ).resolve(
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

