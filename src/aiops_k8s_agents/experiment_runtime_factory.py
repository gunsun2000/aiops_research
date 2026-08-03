from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from aiops_k8s_agents.agent_adapters import build_default_agent_adapter_registry
from aiops_k8s_agents.chaos_adapter import ChaosMeshAdapter
from aiops_k8s_agents.experiment_runtime import ExperimentRuntime
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
from aiops_k8s_agents.mutual_supervision_policy import load_mutual_supervision_policy
from aiops_k8s_agents.prometheus import PrometheusAdapter
from aiops_k8s_agents.real_evidence import (
    PrometheusKubernetesEvidenceProvider,
    RuntimeConfiguration,
    load_runtime_configuration,
)
from aiops_k8s_agents.recovery_monitor import KubernetesSnapshotRecoveryMonitor
from aiops_k8s_agents.research_protocol import load_protocol_profiles
from aiops_k8s_agents.validator import CommandValidator


CommandRunner = Callable[[list[str]], tuple[int, str, str]]
PrometheusFetcher = Callable[[str, str], dict[str, Any]]

_UI_FALLBACK = {
    "pod-kill": {
        "label": "Pod Kill",
        "value": 0.0,
        "desired_replicas": 1,
        "available_replicas": 0,
        "pod_statuses": ("Terminating",),
        "after_value": 1.0,
        "after_desired_replicas": 3,
        "after_available_replicas": 3,
        "after_pod_statuses": ("Running",),
        "signal": "ready / available replicas",
        "summary": "Registered pod recovery demonstration metadata.",
    },
    "cpu-stress": {
        "label": "CPU Stress",
        "value": 95.0,
        "signal": "container CPU usage",
        "summary": "Registered CPU stress demonstration metadata.",
    },
    "memory-stress": {
        "label": "Memory Stress",
        "value": 95.7,
        "signal": "working set / restart count",
        "summary": "Registered memory stress demonstration metadata.",
    },
    "network-delay": {
        "label": "Network Delay",
        "value": 0.234,
        "signal": "probe duration",
        "summary": "Registered network delay demonstration metadata.",
    },
}


def build_experiment_runtime(
    configuration_path: str | Path,
    prometheus_url: str,
    event_sink: Any,
    *,
    subprocess_runner: CommandRunner | None = None,
    prometheus_fetcher: PrometheusFetcher | None = None,
) -> ExperimentRuntime:
    """Build the admitted deterministic runtime without performing I/O.

    Injectable runners are deliberately limited to construction tests. Runtime
    admission still checks the exact production dependency types before run.
    """
    configuration = load_runtime_configuration(configuration_path)
    repository_root = Path(__file__).resolve().parents[2]
    config_root = repository_root / "config"
    protocol_profiles = load_protocol_profiles(config_root / "protocol_profiles")
    policy = load_mutual_supervision_policy(
        config_root / "mutual_supervision_policy.json"
    )
    validator = CommandValidator(
        allowed_namespaces=set(configuration.allowed_namespaces),
        allowed_deployments=set(configuration.allowed_deployments),
        min_replicas=configuration.min_replicas,
        max_replicas=configuration.max_replicas,
    )
    chaos = ChaosMeshAdapter(
        {
            scenario_id: scenario.manifest
            for scenario_id, scenario in configuration.scenarios.items()
        },
        runner=subprocess_runner,
        repository_root=repository_root,
        wait_timeout_seconds=configuration.timeouts["fault_ready_seconds"],
        command_timeout_seconds=configuration.timeouts["preflight_seconds"],
    )
    scenario_ids = tuple(sorted(configuration.scenarios))
    # Kept as a read-only construction surface for the runtime factory API.
    chaos.scenario_ids = scenario_ids

    def coordinator_factory(request: ExperimentRuntimeRequest) -> MutualSupervisionCoordinator:
        try:
            protocol = protocol_profiles[request.protocol_profile]
        except KeyError as exc:
            raise ValueError(
                f"protocol profile is not registered: {request.protocol_profile}"
            ) from exc
        prometheus = PrometheusAdapter(prometheus_url, fetcher=prometheus_fetcher)
        evidence = PrometheusKubernetesEvidenceProvider(
            prometheus=prometheus,
            metric_queries=configuration.metric_queries,
            requested_metric=request.metric,
            max_sample_age_seconds=configuration.max_sample_age_seconds,
        )
        recovery_monitor = KubernetesSnapshotRecoveryMonitor(
            evidence_provider=evidence,
            max_attempts=max(
                1,
                int(configuration.timeouts["recovery_seconds"] / 5),
            ),
            interval_seconds=5.0,
        )
        return MutualSupervisionCoordinator(
            validator=validator,
            evidence_provider=evidence,
            recovery_monitor=recovery_monitor,
            policy=policy,
            protocol=protocol,
            adapter_registry=build_default_agent_adapter_registry(),
            mode=ExecutionMode(request.mode),
            backend=ExecutionBackend(request.backend),
        )

    return ExperimentRuntime(
        configuration=configuration,
        chaos=chaos,
        coordinator_factory=coordinator_factory,
        event_sink=event_sink,
    )


def runtime_scenario_catalog(
    configuration: RuntimeConfiguration,
) -> list[dict[str, Any]]:
    """Return registered scenarios plus explicitly UI-only fallback fields."""
    catalog: list[dict[str, Any]] = []
    for scenario_id, scenario in configuration.scenarios.items():
        fallback = _UI_FALLBACK.get(scenario_id, {})
        item = dict(fallback)
        item.update(
            {
                "scenario_id": scenario.scenario_id,
                "namespace": scenario.namespace,
                "deployment": scenario.deployment,
                "metric": scenario.metric,
                "threshold": scenario.threshold,
                "manifest": scenario.manifest,
                "mode": "mock",
                "ui_fallback": bool(fallback),
            }
        )
        catalog.append(item)
    return catalog
