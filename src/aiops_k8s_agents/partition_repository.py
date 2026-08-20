from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from aiops_k8s_agents.partition_coordination import LegacyFederatedRoundPlanAdapter
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionContractError,
    PartitionExecutionPlan,
)
from aiops_k8s_agents.partition_validator import PartitionPlanValidator


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
    def __init__(
        self,
        root: str | Path,
        *,
        validation_runner: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self._validation_runner = validation_runner

    def save(
        self,
        report: Mapping[str, Any],
        *,
        sidecars: Mapping[str, object] | None = None,
        include_legacy_report: bool = False,
    ) -> Path:
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

        self._validate_lineage(plan)
        history = self._history_entries(plan_directory, report, plan)
        changes: dict[Path, object] = {}
        if include_legacy_report:
            changes[plan_directory / "report.json"] = report
        changes[version_path] = report
        changes[latest_path] = report
        changes[plan_directory / "history.json"] = history
        for name, value in (sidecars or {}).items():
            if Path(name).name != name:
                raise PartitionContractError(
                    "invalid_contract", "sidecar names must not include a path"
                )
            changes[version_path.parent / name] = value
        self._publish_transaction(changes)
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

    def _validated_plan(self, report: Mapping[str, Any]) -> Mapping[str, Any]:
        plan = report.get("plan")
        if (
            not isinstance(plan, Mapping)
            or report.get("status") != "planned"
            or plan.get("valid") is not True
        ):
            raise PartitionContractError(
                "unvalidated_partition_plan",
                "only independently validated planned reports may be persisted",
            )
        plan_id = str(plan.get("plan_id") or "").strip()
        signature = str(plan.get("deterministic_signature") or "").strip()
        version = plan.get("plan_version")
        if (
            not plan_id
            or not signature
            or isinstance(version, bool)
            or not isinstance(version, int)
            or version < 1
        ):
            raise PartitionContractError(
                "invalid_contract",
                "plan_id, plan_version, and deterministic_signature are required",
            )
        if not self._is_independently_valid(report):
            raise PartitionContractError(
                "independent_validation_failed",
                "the V2 partition validator did not independently approve this report",
            )
        return plan

    def _is_independently_valid(self, report: Mapping[str, Any]) -> bool:
        if self._validation_runner is not None:
            return bool(self._validation_runner(report))
        try:
            round_plan = FederatedRoundPlan.from_dict(report["round_plan"])
            plan = PartitionExecutionPlan.from_dict(report["plan"])
            request = LegacyFederatedRoundPlanAdapter().adapt(round_plan)
        except (KeyError, PartitionContractError, TypeError):
            return False
        validation = PartitionPlanValidator().validate(request, plan)
        return validation.valid or (
            request.legacy_input
            and set(validation.errors) == {"predicted_throughput_unverifiable"}
        )

    def _validate_lineage(self, plan: Mapping[str, Any]) -> None:
        version = plan["plan_version"]
        parent_plan_id = plan.get("parent_plan_id")
        if version == 1:
            if parent_plan_id is not None:
                raise PartitionContractError(
                    "non_immediate_parent_plan",
                    "the initial plan version must not declare a parent",
                )
            return
        parent_id = str(parent_plan_id or "").strip()
        if not parent_id:
            raise PartitionContractError(
                "orphan_parent_plan",
                "a non-initial plan version requires a persisted parent plan",
            )
        try:
            parent = self.get(parent_id)["plan"]
        except PartitionContractError as exc:
            if exc.code == "plan_not_found":
                raise PartitionContractError(
                    "orphan_parent_plan",
                    "parent_plan_id does not identify a persisted plan",
                ) from exc
            raise
        if parent.get("plan_version") != version - 1:
            raise PartitionContractError(
                "non_immediate_parent_plan",
                "parent_plan_id must identify the immediate preceding plan version",
            )
        if self._has_persisted_child(parent_id):
            raise PartitionContractError(
                "non_immediate_parent_plan",
                "parent_plan_id already has a persisted immediate successor",
            )

    def _has_persisted_child(self, parent_plan_id: str) -> bool:
        if not self.root.is_dir():
            return False
        for plan_directory in self.root.iterdir():
            latest_path = plan_directory / "latest.json"
            if not latest_path.is_file():
                continue
            child = self._read_json(latest_path).get("plan", {})
            if child.get("parent_plan_id") == parent_plan_id:
                return True
        return False

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _history_entries(
        self,
        plan_directory: Path,
        report: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
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
        return entries

    def _publish_transaction(self, changes: Mapping[Path, object]) -> None:
        transaction = self.root / f".partition-transaction-{uuid4().hex}"
        published: list[tuple[Path, Path | None]] = []
        try:
            transaction.mkdir(parents=True, exist_ok=False)
            staged: list[tuple[Path, Path]] = []
            for index, (target, value) in enumerate(changes.items()):
                staged_path = transaction / f"staged-{index}.json"
                staged_path.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                staged.append((target, staged_path))
            for index, (target, staged_path) in enumerate(staged):
                backup = None
                if target.is_file():
                    backup = transaction / f"backup-{index}.json"
                    shutil.copy2(target, backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                staged_path.replace(target)
                published.append((target, backup))
        except Exception:
            self._rollback(published, self.root)
            raise
        finally:
            shutil.rmtree(transaction, ignore_errors=True)

    @staticmethod
    def _rollback(
        published: list[tuple[Path, Path | None]], root: Path
    ) -> None:
        for target, backup in reversed(published):
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backup, target)
        for target, _ in reversed(published):
            directory = target.parent
            while directory != root:
                try:
                    directory.rmdir()
                except OSError:
                    break
                directory = directory.parent
