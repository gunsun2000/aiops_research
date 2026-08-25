from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from orchestrator_agent.partition_models import (
    PartitionContractError,
    PartitionExecutionPlan,
    PartitionFailure,
)


RUNTIME_FEEDBACK_SIGNALS = frozenset(
    {
        "device_unavailable",
        "transfer_failure",
        "latency_slo_violation",
        "placement_rejected",
    }
)


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise PartitionContractError(
            "feedback_context_required", f"feedback.{field} is required"
        )
    return value


@dataclass(frozen=True)
class PartitionRuntimeFeedback:
    signal: str
    source: str
    reason: str
    received_at: str
    plan_id: str
    plan_version: int
    device_id: str = ""
    source_device: str = ""
    target_device: str = ""
    candidate_id: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PartitionRuntimeFeedback:
        signal = _required_text(payload, "signal")
        if signal not in RUNTIME_FEEDBACK_SIGNALS:
            raise PartitionContractError(
                "unsupported_feedback_signal",
                f"unsupported feedback signal: {signal}",
            )
        received_at = _required_text(payload, "received_at")
        try:
            datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PartitionContractError(
                "invalid_feedback_timestamp",
                "feedback.received_at must be an ISO-8601 timestamp",
            ) from exc
        version = payload.get("plan_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PartitionContractError(
                "feedback_context_required",
                "feedback.plan_version must be a positive integer",
            )
        feedback = cls(
            signal=signal,
            source=_required_text(payload, "source"),
            reason=_required_text(payload, "reason"),
            received_at=received_at,
            plan_id=_required_text(payload, "plan_id"),
            plan_version=version,
            device_id=str(payload.get("device_id") or "").strip(),
            source_device=str(payload.get("source_device") or "").strip(),
            target_device=str(payload.get("target_device") or "").strip(),
            candidate_id=str(payload.get("candidate_id") or "").strip(),
        )
        if signal == "device_unavailable" and not feedback.device_id:
            raise PartitionContractError(
                "feedback_context_required",
                "device_unavailable requires device_id",
            )
        if signal == "transfer_failure" and (
            not feedback.source_device or not feedback.target_device
        ):
            raise PartitionContractError(
                "feedback_context_required",
                "transfer_failure requires source_device and target_device",
            )
        return feedback

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "source": self.source,
            "reason": self.reason,
            "received_at": self.received_at,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "device_id": self.device_id,
            "source_device": self.source_device,
            "target_device": self.target_device,
            "candidate_id": self.candidate_id,
        }

    def validate(self) -> PartitionRuntimeFeedback:
        """Reapply the wire contract to objects created outside ``from_dict``."""
        return self.from_dict(self.to_dict())


@dataclass(frozen=True)
class RepartitionDirective:
    exclusion_type: str
    excluded_devices: tuple[str, ...] = ()
    excluded_links: tuple[tuple[str, str], ...] = ()
    excluded_splits: tuple[tuple[int, ...], ...] = ()
    excluded_candidate_splits: tuple[tuple[int, ...], ...] = ()
    memory_limits: tuple[tuple[str, int], ...] = ()
    errors: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RepartitionDirective:
        def splits(name: str) -> tuple[tuple[int, ...], ...]:
            values = payload.get(name, [])
            if not isinstance(values, list):
                raise PartitionContractError("invalid_feedback_directive", f"{name} must be a list")
            return tuple(tuple(int(point) for point in split) for split in values)

        return cls(
            exclusion_type=str(payload.get("exclusion_type") or "").strip() or "none",
            excluded_devices=tuple(str(item) for item in payload.get("excluded_devices", [])),
            excluded_links=tuple(
                (str(link[0]), str(link[1]))
                for link in payload.get("excluded_links", [])
            ),
            excluded_splits=splits("excluded_splits"),
            excluded_candidate_splits=splits("excluded_candidate_splits"),
            memory_limits=tuple(
                (str(device_id), int(limit))
                for device_id, limit in payload.get("memory_limits", [])
            ),
            errors=tuple(str(item) for item in payload.get("errors", [])),
        )

    @classmethod
    def from_partition_failure(
        cls, failure: PartitionFailure, previous_plan: PartitionExecutionPlan
    ) -> RepartitionDirective:
        selected = previous_plan.selected_candidate
        if failure.signal == "device_unavailable":
            return cls("device", excluded_devices=(failure.device_id,))
        if failure.signal == "transfer_failure":
            return cls(
                "link", excluded_links=((failure.source_device, failure.target_device),)
            )
        if failure.signal == "latency_slo_violation" and selected is not None:
            return cls("split", excluded_splits=(selected.split_points,))
        if failure.signal == "memory_exceeded" and selected is not None:
            partition = next(
                (
                    item
                    for item in selected.partitions
                    if item.device_id == failure.device_id
                ),
                None,
            )
            if partition is not None:
                return cls(
                    "memory",
                    memory_limits=((failure.device_id, partition.memory_demand_bytes - 1),),
                )
            return cls("memory", errors=("failed_device_not_in_previous_plan",))
        return cls("none")

    def merge(self, newer: RepartitionDirective) -> RepartitionDirective:
        return RepartitionDirective(
            exclusion_type=newer.exclusion_type,
            excluded_devices=tuple(sorted(set(self.excluded_devices) | set(newer.excluded_devices))),
            excluded_links=tuple(sorted(set(self.excluded_links) | set(newer.excluded_links))),
            excluded_splits=tuple(sorted(set(self.excluded_splits) | set(newer.excluded_splits))),
            excluded_candidate_splits=tuple(
                sorted(
                    set(self.excluded_candidate_splits)
                    | set(newer.excluded_candidate_splits)
                )
            ),
            memory_limits=tuple(
                sorted((dict(self.memory_limits) | dict(newer.memory_limits)).items())
            ),
            errors=tuple(sorted(set(self.errors) | set(newer.errors))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exclusion_type": self.exclusion_type,
            "excluded_devices": list(self.excluded_devices),
            "excluded_links": [list(link) for link in self.excluded_links],
            "excluded_splits": [list(split) for split in self.excluded_splits],
            "excluded_candidate_splits": [
                list(split) for split in self.excluded_candidate_splits
            ],
            "memory_limits": [list(item) for item in self.memory_limits],
            "errors": list(self.errors),
        }


class PartitionFeedbackAnalyzer:
    def analyze(
        self,
        feedback: PartitionRuntimeFeedback,
        previous_plan: PartitionExecutionPlan,
    ) -> RepartitionDirective:
        feedback = feedback.validate()
        if (
            feedback.plan_id != previous_plan.plan_id
            or feedback.plan_version != previous_plan.plan_version
        ):
            raise PartitionContractError(
                "feedback_plan_mismatch",
                "feedback must identify the persisted plan version being replanned",
            )
        selected = previous_plan.selected_candidate
        if feedback.signal == "device_unavailable":
            return RepartitionDirective("device", excluded_devices=(feedback.device_id,))
        if feedback.signal == "transfer_failure":
            return RepartitionDirective(
                "link",
                excluded_links=((feedback.source_device, feedback.target_device),),
            )
        if selected is None:
            raise PartitionContractError(
                "feedback_plan_has_no_candidate",
                "feedback replanning requires a previously selected candidate",
            )
        if feedback.signal == "latency_slo_violation":
            return RepartitionDirective("split", excluded_splits=(selected.split_points,))
        if feedback.signal == "placement_rejected":
            return RepartitionDirective(
                "candidate", excluded_candidate_splits=(selected.split_points,)
            )
        raise PartitionContractError(
            "unsupported_feedback_signal",
            f"unsupported feedback signal: {feedback.signal}",
        )

