from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from aiops_k8s_agents.executor import ExecutionMode, KubernetesExecutor, subprocess_runner
from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot
from aiops_k8s_agents.models import RecoveryActionKind
from aiops_k8s_agents.models import RecoveryAction
from aiops_k8s_agents.prometheus import fetch_prometheus_query
from aiops_k8s_agents.validator import CommandValidator


KubectlRunner = Callable[[list[str]], tuple[int, str, str]]
MetricQuery = Callable[[str, str], float]
SnapshotCollector = Callable[[str, str], dict[str, Any]]
TreatmentRunner = Callable[..., dict[str, Any]]


class MetricDirection(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class RecoveryScenario:
    id: str
    namespace: str
    deployment: str
    chaos_manifest: str
    metric: str
    evidence_source: str
    metric_direction: MetricDirection
    fault_threshold: float
    recovery_threshold: float
    query: str | None = None
    query_env: str | None = None


@dataclass(frozen=True)
class RecoveryExperimentConfig:
    baseline_replicas: int
    scale_replicas: int
    fault_detection_timeout_seconds: int
    recovery_timeout_seconds: int
    poll_interval_seconds: int
    actions: tuple[str, ...]
    scenarios: tuple[RecoveryScenario, ...]


@dataclass(frozen=True)
class RecoveryTreatment:
    treatment_id: str
    scenario: RecoveryScenario
    action: RecoveryActionKind
    repetition: int


@dataclass(frozen=True)
class RecoveryExperimentRuntime:
    kubectl: KubectlRunner = subprocess_runner
    query_metric: MetricQuery = None  # type: ignore[assignment]
    snapshot: SnapshotCollector = collect_kubernetes_snapshot
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if self.query_metric is None:
            object.__setattr__(self, "query_metric", query_prometheus_scalar)


def load_recovery_experiment_config(
    path: str | Path,
) -> RecoveryExperimentConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    actions = tuple(str(value) for value in data["actions"])
    allowed_actions = {item.value for item in RecoveryActionKind}
    unknown_actions = sorted(set(actions) - allowed_actions)
    if unknown_actions:
        raise ValueError(f"unsupported recovery actions: {', '.join(unknown_actions)}")

    scenarios = tuple(_scenario_from_dict(item) for item in data["scenarios"])
    ids = [scenario.id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("recovery scenario ids must be unique")

    config = RecoveryExperimentConfig(
        baseline_replicas=int(data["baseline_replicas"]),
        scale_replicas=int(data["scale_replicas"]),
        fault_detection_timeout_seconds=int(
            data["fault_detection_timeout_seconds"]
        ),
        recovery_timeout_seconds=int(data["recovery_timeout_seconds"]),
        poll_interval_seconds=int(data["poll_interval_seconds"]),
        actions=actions,
        scenarios=scenarios,
    )
    if config.baseline_replicas < 1:
        raise ValueError("baseline_replicas must be positive")
    if config.scale_replicas <= config.baseline_replicas:
        raise ValueError("scale_replicas must exceed baseline_replicas")
    return config


def build_treatment_matrix(
    config: RecoveryExperimentConfig,
    repetitions: int,
) -> list[RecoveryTreatment]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    return [
        RecoveryTreatment(
            treatment_id=(
                f"{scenario.id}__{action}__repeat-{repetition:02d}"
            ),
            scenario=scenario,
            action=RecoveryActionKind(action),
            repetition=repetition,
        )
        for repetition in range(1, repetitions + 1)
        for scenario in config.scenarios
        for action in config.actions
    ]


def resolve_metric_query(
    scenario: RecoveryScenario,
    environ: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if environ is None else environ
    query = scenario.query
    if scenario.query_env:
        query = values.get(scenario.query_env)
        if not query:
            raise ValueError(
                f"{scenario.id} requires environment variable {scenario.query_env}"
            )
    if not query:
        raise ValueError(f"{scenario.id} has no metric query")
    if scenario.metric == "latency" and _is_prometheus_up_query(query):
        raise ValueError("network-delay requires real latency evidence, not max(up)")
    return query


def metric_is_faulted(
    value: float,
    threshold: float,
    direction: MetricDirection,
) -> bool:
    if direction == MetricDirection.HIGH:
        return value >= threshold
    return value <= threshold


def metric_is_recovered(
    value: float,
    threshold: float,
    direction: MetricDirection,
) -> bool:
    if direction == MetricDirection.HIGH:
        return value <= threshold
    return value >= threshold


def metric_improvement(
    fault_value: float,
    recovered_value: float,
    direction: MetricDirection,
) -> float:
    if direction == MetricDirection.HIGH:
        denominator = max(abs(fault_value), 1e-9)
        value = (fault_value - recovered_value) / denominator
    else:
        denominator = max(abs(recovered_value), 1.0)
        value = (recovered_value - fault_value) / denominator
    return round(min(max(value, 0.0), 1.0), 6)


def query_prometheus_scalar(base_url: str, query: str) -> float:
    response = fetch_prometheus_query(base_url, query)
    if response.get("status") != "success":
        raise ValueError("Prometheus query did not return success")
    results = response.get("data", {}).get("result", [])
    if not results:
        raise ValueError("Prometheus query returned no samples")
    value = results[0].get("value")
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("Prometheus sample has no scalar value")
    return float(value[1])


def run_recovery_treatment(
    treatment: RecoveryTreatment,
    config: RecoveryExperimentConfig,
    mode: str,
    prometheus_url: str,
    runtime: RecoveryExperimentRuntime | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    runtime = runtime or RecoveryExperimentRuntime()
    scenario = treatment.scenario
    action = RecoveryAction(
        namespace=scenario.namespace,
        deployment=scenario.deployment,
        kind=treatment.action,
        replicas=(
            config.scale_replicas
            if treatment.action == RecoveryActionKind.SCALE_OUT
            else None
        ),
        reason=f"real fault treatment: {scenario.id}",
    )
    record = _empty_treatment_record(treatment, action, mode)

    try:
        query = resolve_metric_query(scenario, environ)
        _reset_treatment(scenario, config, runtime)
        record["before"] = runtime.snapshot(
            scenario.namespace, scenario.deployment
        )
        record["metric_before_fault"] = _sample_evidence(
            runtime, scenario, prometheus_url, query
        )

        _kubectl_or_raise(
            runtime,
            ["kubectl", "apply", "-f", scenario.chaos_manifest],
        )
        fault_value, fault_seconds = _wait_for_evidence(
            runtime=runtime,
            scenario=scenario,
            prometheus_url=prometheus_url,
            query=query,
            timeout_seconds=config.fault_detection_timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
            predicate=lambda value: metric_is_faulted(
                value, scenario.fault_threshold, scenario.metric_direction
            ),
        )
        record["metric_at_fault"] = fault_value
        record["fault_detection_seconds"] = round(fault_seconds, 6)
        record["fault"] = runtime.snapshot(
            scenario.namespace, scenario.deployment
        )

        validator = CommandValidator(
            allowed_namespaces={scenario.namespace},
            allowed_deployments={scenario.deployment},
            min_replicas=config.baseline_replicas,
            max_replicas=config.scale_replicas,
        )
        executor = KubernetesExecutor(
            validator=validator,
            mode=ExecutionMode(mode),
            runner=runtime.kubectl,
        )
        result = executor.execute_recovery(action)
        record["command_result"] = {
            "command": result.command,
            "mode": result.mode,
            "valid": result.valid,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        record["safety_valid"] = bool(result.valid)
        record["command_count"] = (
            0 if treatment.action == RecoveryActionKind.OBSERVE_ONLY else 1
        )

        recovered_value, recovery_seconds = _wait_for_evidence(
            runtime=runtime,
            scenario=scenario,
            prometheus_url=prometheus_url,
            query=query,
            timeout_seconds=config.recovery_timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
            predicate=lambda value: metric_is_recovered(
                value, scenario.recovery_threshold, scenario.metric_direction
            ),
        )
        record["metric_after_action"] = recovered_value
        record["recovery_seconds"] = round(recovery_seconds, 6)
        record["after"] = runtime.snapshot(
            scenario.namespace, scenario.deployment
        )
        record["measurement_valid"] = True
        record["metric_improvement"] = metric_improvement(
            fault_value, recovered_value, scenario.metric_direction
        )
        record["availability_recovery"] = _availability_ratio(record["after"])
        record["replica_delta"] = (
            _desired_replicas(record["after"]) - config.baseline_replicas
        )
        record["recovery_success"] = bool(
            result.valid and record["availability_recovery"] >= 1.0
        )
    except Exception as exc:  # The record must survive failed treatments.
        record["error"] = str(exc)
    finally:
        try:
            _reset_treatment(scenario, config, runtime)
            record["cleanup_valid"] = True
        except Exception as cleanup_exc:
            record["cleanup_valid"] = False
            record["cleanup_error"] = str(cleanup_exc)
        record["finished_at"] = datetime.now(timezone.utc).isoformat()

    return record


def run_recovery_matrix(
    config: RecoveryExperimentConfig,
    repetitions: int,
    mode: str,
    prometheus_url: str,
    output_path: str | Path,
    treatment_runner: TreatmentRunner = run_recovery_treatment,
    runtime: RecoveryExperimentRuntime | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    treatments = build_treatment_matrix(config, repetitions)
    for scenario in config.scenarios:
        resolve_metric_query(scenario, environ)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("", encoding="utf-8")
    records: list[dict[str, Any]] = []
    with destination.open("a", encoding="utf-8") as file:
        for treatment in treatments:
            record = treatment_runner(
                treatment=treatment,
                config=config,
                mode=mode,
                prometheus_url=prometheus_url,
                runtime=runtime,
                environ=environ,
            )
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
            records.append(record)

    return {
        "command": "recovery-action-experiment",
        "mode": mode,
        "repetitions": repetitions,
        "total_treatments": len(records),
        "valid_measurements": sum(
            1 for record in records if record.get("measurement_valid")
        ),
        "successful_recoveries": sum(
            1 for record in records if record.get("recovery_success")
        ),
        "output": str(destination),
    }


def _wait_for_evidence(
    runtime: RecoveryExperimentRuntime,
    scenario: RecoveryScenario,
    prometheus_url: str,
    query: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
    predicate: Callable[[float], bool],
) -> tuple[float, float]:
    started = runtime.monotonic()
    last_error = "metric condition was not reached"
    while True:
        try:
            value = _sample_evidence(runtime, scenario, prometheus_url, query)
            if predicate(value):
                return value, runtime.monotonic() - started
            last_error = f"last metric value was {value}"
        except Exception as exc:
            last_error = str(exc)
        elapsed = runtime.monotonic() - started
        if elapsed >= timeout_seconds:
            raise ValueError(
                f"metric wait timed out after {timeout_seconds}s: {last_error}"
            )
        runtime.sleep(poll_interval_seconds)


def _sample_evidence(
    runtime: RecoveryExperimentRuntime,
    scenario: RecoveryScenario,
    prometheus_url: str,
    query: str,
) -> float:
    if scenario.evidence_source == "kubernetes_availability":
        snapshot = runtime.snapshot(scenario.namespace, scenario.deployment)
        status = snapshot.get("deployment_status", {})
        if not status.get("ok"):
            raise ValueError("Kubernetes deployment availability is unavailable")
        return float(status.get("available_replicas", 0) or 0)
    return runtime.query_metric(prometheus_url, query)


def _reset_treatment(
    scenario: RecoveryScenario,
    config: RecoveryExperimentConfig,
    runtime: RecoveryExperimentRuntime,
) -> None:
    _kubectl_or_raise(
        runtime,
        [
            "kubectl",
            "delete",
            "-f",
            scenario.chaos_manifest,
            "--ignore-not-found",
        ],
    )
    _kubectl_or_raise(
        runtime,
        [
            "kubectl",
            "scale",
            "deployment",
            scenario.deployment,
            f"--replicas={config.baseline_replicas}",
            "-n",
            scenario.namespace,
        ],
    )
    _kubectl_or_raise(
        runtime,
        [
            "kubectl",
            "rollout",
            "status",
            f"deployment/{scenario.deployment}",
            "-n",
            scenario.namespace,
            f"--timeout={config.recovery_timeout_seconds}s",
        ],
    )


def _kubectl_or_raise(
    runtime: RecoveryExperimentRuntime,
    argv: list[str],
) -> None:
    return_code, _stdout, stderr = runtime.kubectl(argv)
    if return_code != 0:
        raise RuntimeError(stderr or f"kubectl failed: {' '.join(argv)}")


def _empty_treatment_record(
    treatment: RecoveryTreatment,
    action: RecoveryAction,
    mode: str,
) -> dict[str, Any]:
    return {
        "treatment_id": treatment.treatment_id,
        "scenario": treatment.scenario.id,
        "repetition": treatment.repetition,
        "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "action": {
            "namespace": action.namespace,
            "deployment": action.deployment,
            "kind": action.kind.value,
            "replicas": action.replicas,
            "reason": action.reason,
        },
        "recovery_success": False,
        "availability_recovery": 0.0,
        "metric_improvement": 0.0,
        "recovery_seconds": 0.0,
        "replica_delta": 0,
        "command_count": 0,
        "safety_valid": False,
        "measurement_valid": False,
        "cleanup_valid": False,
        "error": "",
    }


def _availability_ratio(snapshot: dict[str, Any]) -> float:
    status = snapshot.get("deployment_status", {})
    desired = int(status.get("desired_replicas", 0) or 0)
    available = int(status.get("available_replicas", 0) or 0)
    if not status.get("ok") or desired < 1:
        return 0.0
    return round(min(max(available / desired, 0.0), 1.0), 6)


def _desired_replicas(snapshot: dict[str, Any]) -> int:
    status = snapshot.get("deployment_status", {})
    return int(status.get("desired_replicas", 0) or 0)


def _scenario_from_dict(data: dict[str, object]) -> RecoveryScenario:
    scenario = RecoveryScenario(
        id=str(data["id"]),
        namespace=str(data["namespace"]),
        deployment=str(data["deployment"]),
        chaos_manifest=str(data["chaos_manifest"]),
        metric=str(data["metric"]),
        evidence_source=str(data.get("evidence_source", "prometheus")),
        metric_direction=MetricDirection(str(data["metric_direction"])),
        fault_threshold=float(data["fault_threshold"]),
        recovery_threshold=float(data["recovery_threshold"]),
        query=None if data.get("query") is None else str(data["query"]),
        query_env=(
            None if data.get("query_env") is None else str(data["query_env"])
        ),
    )
    if scenario.metric == "latency" and scenario.query:
        if _is_prometheus_up_query(scenario.query):
            raise ValueError("network-delay requires real latency evidence, not max(up)")
    if not scenario.query and not scenario.query_env:
        raise ValueError(f"{scenario.id} must define query or query_env")
    if scenario.evidence_source not in {
        "prometheus",
        "kubernetes_availability",
    }:
        raise ValueError(
            f"unsupported evidence source for {scenario.id}: "
            f"{scenario.evidence_source}"
        )
    return scenario


def _is_prometheus_up_query(query: str) -> bool:
    compact = "".join(query.lower().split())
    return compact in {"up", "max(up)", "min(up)", "sum(up)"}
