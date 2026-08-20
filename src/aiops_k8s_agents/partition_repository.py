from __future__ import annotations

import json
import os
import shutil
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping
from uuid import uuid4

from aiops_k8s_agents.partition_coordination import LegacyFederatedRoundPlanAdapter
from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionContractError,
    PartitionExecutionPlan,
)
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry
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
    _COMMIT_FILE = "commit.json"
    _PENDING_FILE = "pending.json"
    _TRANSACTION_PREFIX = ".partition-transaction-"
    _STAGING_PREFIX = ".partition-staging-"
    _BACKUP_PREFIX = ".partition-backup-"
    _RESERVED_SIDECARS = frozenset(
        {
            "report.json",
            "latest.json",
            "history.json",
            "scheduling_handoff.json",
            _COMMIT_FILE,
            _PENDING_FILE,
        }
    )

    def __init__(
        self, root: str | Path, *, policy_path: str | Path | None = None
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self._policy_path = None if policy_path is None else Path(policy_path)
        self._fault_injector: Callable[[str], None] | None = None
        self._recover_incomplete_transactions()

    def save(
        self,
        report: Mapping[str, Any],
        *,
        sidecars: Mapping[str, object] | None = None,
        include_legacy_report: bool = False,
    ) -> Path:
        self._recover_incomplete_transactions()
        plan = self._plan_identity(report)
        plan_id = str(plan["plan_id"])
        version = plan["plan_version"]
        plan_directory = self.root / plan_id
        latest_path = plan_directory / "latest.json"
        version_path = plan_directory / "versions" / str(version) / "report.json"
        normalized_sidecars = self._normalize_sidecars(sidecars)

        if self._is_committed(plan_directory) and latest_path.is_file():
            existing_plan = self._read_json(latest_path).get("plan", {})
            if existing_plan.get("plan_version") != version:
                raise PartitionContractError(
                    "plan_id_reused",
                    "each persisted partition plan version requires a unique plan_id",
                )
        if self._is_committed(plan_directory) and version_path.is_file():
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

        self._validate_plan(report, plan)
        self._validate_lineage(plan)
        persisted_report = self._with_canonical_handoff(report)
        history = self._history_entries(plan_directory, persisted_report, plan)
        self._publish_plan_directory(
            plan_directory,
            version_path,
            persisted_report,
            history,
            normalized_sidecars,
            include_legacy_report,
        )
        if isinstance(report, MutableMapping):
            report["scheduling_handoff"] = persisted_report["scheduling_handoff"]
        return version_path

    def get(self, plan_id: str, version: int | None = None) -> dict[str, Any]:
        self._recover_incomplete_transactions()
        plan_directory = self.root / plan_id
        path = (
            plan_directory / "latest.json"
            if version is None
            else plan_directory / "versions" / str(version) / "report.json"
        )
        if not self._is_committed(plan_directory) or not path.is_file():
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

    def is_current_leaf(self, plan_id: str) -> bool:
        """Return whether a persisted plan has no immediate successor."""
        self.get(plan_id)
        return not self._has_persisted_child(plan_id)

    def _plan_identity(self, report: Mapping[str, Any]) -> Mapping[str, Any]:
        plan = report.get("plan")
        if not isinstance(plan, Mapping):
            raise PartitionContractError("invalid_contract", "plan must be an object")
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
        return plan

    def _validate_plan(
        self, report: Mapping[str, Any], plan: Mapping[str, Any]
    ) -> None:
        if report.get("status") != "planned" or plan.get("valid") is not True:
            raise PartitionContractError(
                "unvalidated_partition_plan",
                "only independently validated planned reports may be persisted",
            )
        if not self._is_independently_valid(report):
            raise PartitionContractError(
                "independent_validation_failed",
                "the V2 partition validator did not independently approve this report",
            )

    def _is_independently_valid(self, report: Mapping[str, Any]) -> bool:
        try:
            round_plan = FederatedRoundPlan.from_dict(report["round_plan"])
            plan = PartitionExecutionPlan.from_dict(report["plan"])
            request_payload = report.get("planning_request")
            if isinstance(request_payload, Mapping):
                request = PartitionPlanningRequest.from_dict(request_payload)
                normalized = PartitionCommonProcessor().process(request)
                expected_round_plan = FederatedRoundPlan(
                    job_id=normalized.job_id,
                    model_id=normalized.model_id,
                    execution_mode=normalized.approved_execution_mode,
                    layers=normalized.layers,
                    participants=normalized.participants,
                    devices=normalized.devices,
                    network_links=normalized.network_links,
                    constraints=normalized.constraints,
                )
                if round_plan != expected_round_plan:
                    return False
            else:
                request = LegacyFederatedRoundPlanAdapter().adapt(round_plan)
        except (KeyError, PartitionContractError, TypeError):
            return False
        validation = PartitionPlanValidator(
            strategy_registry=PartitionStrategyRegistry.default(self._policy_path)
        ).validate(request, plan)
        return validation.valid or (
            request.legacy_input
            and set(validation.errors) == {"predicted_throughput_unverifiable"}
        )

    def _with_canonical_handoff(self, report: Mapping[str, Any]) -> dict[str, Any]:
        persisted_report = dict(report)
        plan = PartitionExecutionPlan.from_dict(report["plan"])
        persisted_report["scheduling_handoff"] = SchedulingHandoff.create(
            plan,
            id_factory=lambda: f"scheduling-handoff-{uuid4().hex}",
            clock=lambda: datetime.now(timezone.utc).isoformat(),
        ).to_dict()
        return persisted_report

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
            if not self._is_committed(plan_directory):
                continue
            latest_path = plan_directory / "latest.json"
            if not latest_path.is_file():
                continue
            child = self._read_json(latest_path).get("plan", {})
            if child.get("parent_plan_id") == parent_plan_id:
                return True
        return False

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

    def _publish_plan_directory(
        self,
        plan_directory: Path,
        version_path: Path,
        report: Mapping[str, Any],
        history: list[dict[str, Any]],
        sidecars: Sequence[tuple[tuple[str, ...], object]],
        include_legacy_report: bool,
    ) -> None:
        transaction_id = uuid4().hex
        transaction_root = self.root / f"{self._STAGING_PREFIX}{transaction_id}"
        staged_plan_directory = transaction_root / plan_directory.name
        backup_directory = self.root / f"{self._BACKUP_PREFIX}{transaction_id}"
        transaction_marker = self.root / f"{self._TRANSACTION_PREFIX}{transaction_id}.json"
        transaction_started = False
        try:
            if plan_directory.is_dir():
                shutil.copytree(plan_directory, staged_plan_directory)
            elif plan_directory.exists():
                raise PartitionContractError(
                    "invalid_contract", "a partition plan path must be a directory"
                )
            self._remove_staged_repository_metadata(
                staged_plan_directory,
                preserve_legacy_report=not include_legacy_report,
            )
            self._write_json(staged_plan_directory / self._PENDING_FILE, {"pending": True})
            if include_legacy_report:
                self._write_json(staged_plan_directory / "report.json", report)
            relative_version_path = version_path.relative_to(plan_directory)
            self._write_json(staged_plan_directory / relative_version_path, report)
            self._write_json(staged_plan_directory / "latest.json", report)
            self._write_json(staged_plan_directory / "history.json", history)
            self._write_json(
                staged_plan_directory / "versions" / str(report["plan"]["plan_version"]) / "scheduling_handoff.json",
                report["scheduling_handoff"],
            )
            for segments, value in sidecars:
                self._write_json(
                    staged_plan_directory
                    / "versions"
                    / str(report["plan"]["plan_version"])
                    / Path(*segments),
                    value,
                )
            self._fsync_directory(staged_plan_directory)
            plan_directory.parent.mkdir(parents=True, exist_ok=True)
            self._write_transaction_marker(
                transaction_marker,
                {
                    "backup_directory": backup_directory.name,
                    "had_previous_directory": plan_directory.exists(),
                    "plan_directory": plan_directory.name,
                    "staging_directory": transaction_root.name,
                },
            )
            transaction_started = True
            if plan_directory.exists():
                plan_directory.replace(backup_directory)
                self._fsync_directory(self.root)
                self._inject_fault("after_plan_directory_backup")
            staged_plan_directory.replace(plan_directory)
            self._fsync_directory(self.root)
            self._inject_fault("after_plan_directory_replace")
            self._write_commit_marker(plan_directory)
            (plan_directory / self._PENDING_FILE).unlink(missing_ok=True)
            self._fsync_directory(plan_directory)
            self._remove_transaction_artifacts(
                transaction_marker, transaction_root, backup_directory
            )
        finally:
            if not transaction_started:
                shutil.rmtree(transaction_root, ignore_errors=True)

    def _write_commit_marker(self, plan_directory: Path) -> None:
        marker = plan_directory / self._COMMIT_FILE
        temporary = plan_directory / f".{self._COMMIT_FILE}.{uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps({"committed": True}, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._fsync_file(temporary)
        temporary.replace(marker)
        self._fsync_directory(plan_directory)

    def _recover_incomplete_transactions(self) -> None:
        if not self.root.is_dir():
            return
        for marker in self.root.glob(f"{self._TRANSACTION_PREFIX}*.json"):
            self._recover_transaction(marker)
        for path in self.root.iterdir():
            if path.name.startswith(self._STAGING_PREFIX):
                shutil.rmtree(path, ignore_errors=True)
                continue
            if (
                path.is_dir()
                and (path / self._PENDING_FILE).is_file()
                and not (path / self._COMMIT_FILE).is_file()
            ):
                shutil.rmtree(path, ignore_errors=True)

    def _is_committed(self, plan_directory: Path) -> bool:
        return (plan_directory / self._COMMIT_FILE).is_file()

    def _normalize_sidecars(
        self, sidecars: Mapping[str, object] | None
    ) -> tuple[tuple[tuple[str, ...], object], ...]:
        normalized_sidecars: list[tuple[tuple[str, ...], object]] = []
        seen_names: set[tuple[str, ...]] = set()
        reserved_names = {name.casefold() for name in self._RESERVED_SIDECARS}
        for name, value in (sidecars or {}).items():
            if not isinstance(name, str) or PureWindowsPath(name).drive or name.startswith(
                ("/", "\\")
            ):
                raise PartitionContractError(
                    "invalid_contract", "sidecar names must be relative paths"
                )
            segments = tuple(name.replace("\\", "/").split("/"))
            normalized_segments = tuple(
                segment.rstrip(" .").casefold() for segment in segments
            )
            if (
                not segments
                or any(
                    not segment
                    or segment in {".", ".."}
                    or not normalized_segment
                    for segment, normalized_segment in zip(
                        segments, normalized_segments, strict=True
                    )
                )
            ):
                raise PartitionContractError(
                    "invalid_contract", "sidecar names must contain safe path segments"
                )
            if any(segment in reserved_names for segment in normalized_segments):
                raise PartitionContractError(
                    "reserved_sidecar_name", f"{name} is managed by the repository"
                )
            if normalized_segments in seen_names:
                raise PartitionContractError(
                    "sidecar_name_collision",
                    "sidecar names must be unique under Windows path normalization",
                )
            seen_names.add(normalized_segments)
            normalized_sidecars.append((segments, value))
        return tuple(normalized_sidecars)

    def _remove_staged_repository_metadata(
        self,
        staged_plan_directory: Path,
        *,
        preserve_legacy_report: bool,
    ) -> None:
        if not staged_plan_directory.exists():
            return
        reserved_root_files = {
            "report.json",
            "latest.json",
            "history.json",
            self._COMMIT_FILE,
            self._PENDING_FILE,
        }
        for path in staged_plan_directory.iterdir():
            if path.is_file() and path.name.rstrip(" .").casefold() in reserved_root_files:
                if preserve_legacy_report and path.name == "report.json":
                    continue
                path.unlink()

    def _write_transaction_marker(
        self, marker: Path, transaction: Mapping[str, object]
    ) -> None:
        marker.parent.mkdir(parents=True, exist_ok=True)
        temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(transaction, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._fsync_file(temporary)
        temporary.replace(marker)
        self._fsync_directory(marker.parent)

    def _recover_transaction(self, marker: Path) -> None:
        try:
            transaction = self._read_json(marker)
            plan_name = self._transaction_path_name(transaction, "plan_directory")
            staging_name = self._transaction_path_name(transaction, "staging_directory")
            backup_name = self._transaction_path_name(transaction, "backup_directory")
            had_previous_directory = transaction["had_previous_directory"] is True
        except (KeyError, PartitionContractError, TypeError, json.JSONDecodeError):
            return

        plan_directory = self.root / plan_name
        staging_directory = self.root / staging_name
        backup_directory = self.root / backup_name
        if self._is_committed(plan_directory):
            self._remove_transaction_artifacts(
                marker, staging_directory, backup_directory
            )
            return
        if had_previous_directory and backup_directory.exists():
            if plan_directory.exists():
                shutil.rmtree(plan_directory, ignore_errors=True)
            backup_directory.replace(plan_directory)
            self._fsync_directory(self.root)
        elif not had_previous_directory and plan_directory.exists():
            shutil.rmtree(plan_directory, ignore_errors=True)
        self._remove_transaction_artifacts(marker, staging_directory, backup_directory)

    @staticmethod
    def _transaction_path_name(transaction: Mapping[str, Any], key: str) -> str:
        name = transaction.get(key)
        if not isinstance(name, str) or Path(name).name != name:
            raise PartitionContractError(
                "invalid_contract", "transaction marker contains an invalid path"
            )
        return name

    def _remove_transaction_artifacts(
        self, marker: Path, staging_directory: Path, backup_directory: Path
    ) -> None:
        shutil.rmtree(staging_directory, ignore_errors=True)
        shutil.rmtree(backup_directory, ignore_errors=True)
        marker.unlink(missing_ok=True)
        self._fsync_directory(self.root)

    def _inject_fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        PartitionPlanRepository._fsync_file(path)

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
