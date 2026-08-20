from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from aiops_k8s_agents.partition_models import (
    PartitionContractError,
    PartitionExecutionPlan,
)


@dataclass(frozen=True)
class SchedulingHandoff:
    handoff_id: str
    partition_plan_id: str
    partition_plan_version: int
    created_at: str
    status: str
    scheduler_ref: str | None

    @classmethod
    def create(
        cls,
        plan: PartitionExecutionPlan,
        *,
        id_factory: Callable[[], str],
        clock: Callable[[], str],
    ) -> SchedulingHandoff:
        status = "ready" if plan.valid and plan.handoff_status == "ready" else "blocked"
        return cls(
            id_factory(),
            plan.plan_id,
            plan.plan_version,
            clock(),
            status,
            None,
        )

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "handoff_id": self.handoff_id,
            "partition_plan_id": self.partition_plan_id,
            "partition_plan_version": self.partition_plan_version,
            "created_at": self.created_at,
            "status": self.status,
            "scheduler_ref": self.scheduler_ref,
        }


class PartitionPlanRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def save(self, report: Mapping[str, Any]) -> Path:
        plan = self._validated_plan(report)
        plan_id = str(plan["plan_id"])
        version = plan["plan_version"]
        plan_directory = self.root / plan_id
        latest_path = plan_directory / "latest.json"
        if latest_path.is_file():
            existing_plan = self._read_json(latest_path).get("plan", {})
            if existing_plan.get("plan_version") != version:
                raise PartitionContractError(
                    "plan_id_reused",
                    "each persisted partition plan version requires a unique plan_id",
                )
        version_path = plan_directory / "versions" / str(version) / "report.json"

        if version_path.exists():
            existing = self._read_json(version_path)
            if (
                existing.get("plan", {}).get("deterministic_signature")
                != plan["deterministic_signature"]
            ):
                raise PartitionContractError(
                    "plan_version_conflict",
                    "a different deterministic signature already exists for this plan version",
                )
            return version_path

        self._write_json(version_path, report)
        self._write_json(plan_directory / "latest.json", report)
        self._append_history(plan_directory, report, plan)
        return version_path

    def get(self, plan_id: str, version: int | None = None) -> dict[str, Any]:
        plan_directory = self.root / plan_id
        path = (
            plan_directory / "latest.json"
            if version is None
            else plan_directory / "versions" / str(version) / "report.json"
        )
        if not path.is_file():
            raise PartitionContractError(
                "plan_not_found", f"no persisted plan found for {plan_id}"
            )
        return self._read_json(path)

    def history(self, plan_id: str) -> tuple[dict[str, Any], ...]:
        lineage: list[dict[str, Any]] = []
        seen: set[str] = set()
        current_plan_id: str | None = plan_id
        while current_plan_id is not None:
            if current_plan_id in seen:
                raise PartitionContractError(
                    "plan_lineage_cycle", "partition plan lineage contains a cycle"
                )
            seen.add(current_plan_id)
            report = self.get(current_plan_id)
            lineage.append(report)
            parent_plan_id = report["plan"].get("parent_plan_id")
            current_plan_id = (
                None if parent_plan_id is None else str(parent_plan_id).strip() or None
            )
        return tuple(lineage)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _append_history(
        self,
        plan_directory: Path,
        report: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> None:
        path = plan_directory / "history.json"
        entries = self._read_json(path) if path.is_file() else []
        entries.append(
            {
                "plan_id": plan["plan_id"],
                "plan_version": plan["plan_version"],
                "parent_plan_id": plan.get("parent_plan_id"),
                "deterministic_signature": plan["deterministic_signature"],
                "status": report["status"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_json(path, entries)

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)

    @staticmethod
    def _validated_plan(report: Mapping[str, Any]) -> Mapping[str, Any]:
        plan = report.get("plan")
        validation = report.get("validation")
        if (
            not isinstance(plan, Mapping)
            or not isinstance(validation, Mapping)
            or report.get("status") != "planned"
            or plan.get("valid") is not True
            or validation.get("valid") is not True
        ):
            raise PartitionContractError(
                "unvalidated_partition_plan",
                "only independently validated planned reports may be persisted",
            )
        plan_id = str(plan.get("plan_id") or "").strip()
        signature = str(plan.get("deterministic_signature") or "").strip()
        version = plan.get("plan_version")
        if not plan_id or not signature or isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PartitionContractError(
                "invalid_contract",
                "plan_id, plan_version, and deterministic_signature are required",
            )
        return plan
