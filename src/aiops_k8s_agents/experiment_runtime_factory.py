from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from aiops_k8s_agents.agent_adapters import (
    AgentAdapterRegistry,
    DeterministicApplicationAdapter,
    DeterministicCostAdapter,
    DeterministicHAAdapter,
    DeterministicInfrastructureAdapter,
    build_default_agent_adapter_registry,
)
from aiops_k8s_agents.chaos_adapter import ChaosMeshAdapter
from aiops_k8s_agents.autogen_groupchat import (
    AutoGenProtocolAdapter,
    build_autogen_agent_adapter_registry,
    create_openai_model_client,
)
from aiops_k8s_agents.evidence import EvidenceSnapshot, FakeEvidenceProvider
from aiops_k8s_agents.experiment_runtime import (
    CoordinatorAdmission,
    CoordinatorAdmissionValidator,
    ExperimentRuntime,
    default_experiment_id,
)
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot
from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
from aiops_k8s_agents.mutual_supervision_policy import load_mutual_supervision_policy
from aiops_k8s_agents.prometheus import PrometheusAdapter
from aiops_k8s_agents.real_evidence import (
    PrometheusKubernetesEvidenceProvider,
    RuntimeConfiguration,
    load_runtime_configuration,
)
from aiops_k8s_agents.recovery_monitor import (
    FakeRecoveryMonitor,
    KubernetesSnapshotRecoveryMonitor,
)
from aiops_k8s_agents.research_protocol import load_protocol_profiles
from aiops_k8s_agents.validator import CommandValidator


CommandRunner = Callable[[list[str]], tuple[int, str, str]]
PrometheusFetcher = Callable[[str, str], dict[str, Any]]
KubernetesCollector = Callable[..., dict[str, Any]]

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
    kubernetes_collector: KubernetesCollector | None = None,
    experiment_id_factory: Callable[[], str] | None = None,
    cancellation_event: Any | None = None,
    autogen_decision_provider_factory: Callable[[str], Any] | None = None,
    autogen_model_client_factory: Callable[[str], Any] | None = None,
) -> ExperimentRuntime:
    """Build an admitted deterministic or AutoGen runtime without performing I/O.

    Mock uses deterministic in-memory evidence and recovery only. Dry-run uses
    the same non-live evidence boundary while preserving the existing dry-run
    action executor. Real alone constructs live providers and remains subject
    to the exact production admission validator.
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
        expected_runtime = {
            "deterministic": "deterministic",
            "autogen": "autogen-round-robin",
        }[request.controller]
        active_runtimes = {
            binding.runtime for binding in protocol.agents if binding.enabled
        }
        if active_runtimes != {expected_runtime}:
            raise ValueError(
                "controller does not match protocol profile: "
                f"{request.controller} requires {expected_runtime} agent bindings"
            )
        if request.controller == "autogen":
            if not request.model:
                raise ValueError("AutoGen controller requires a model")
            if autogen_decision_provider_factory is not None:
                adapter_registry = build_autogen_agent_adapter_registry(
                    decision_provider=autogen_decision_provider_factory(request.model)
                )
            else:
                model_client_factory = (
                    autogen_model_client_factory or create_openai_model_client
                )
                adapter_registry = build_autogen_agent_adapter_registry(
                    model_client=model_client_factory(request.model)
                )
        else:
            adapter_registry = build_default_agent_adapter_registry()
        if request.mode == ExecutionMode.REAL:
            prometheus = PrometheusAdapter(prometheus_url, fetcher=prometheus_fetcher)
            evidence = PrometheusKubernetesEvidenceProvider(
                prometheus=prometheus,
                metric_queries=configuration.metric_queries,
                requested_metric=request.metric,
                kubernetes_collector=(
                    kubernetes_collector or collect_kubernetes_snapshot
                ),
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
        else:
            evidence = _deterministic_evidence_provider(request)
            recovery_monitor = FakeRecoveryMonitor(default_success=True)
        return MutualSupervisionCoordinator(
            validator=validator,
            evidence_provider=evidence,
            recovery_monitor=recovery_monitor,
            policy=policy,
            protocol=protocol,
            adapter_registry=adapter_registry,
            mode=ExecutionMode(request.mode),
            backend=ExecutionBackend(request.backend),
        )

    return ExperimentRuntime(
        configuration=configuration,
        chaos=chaos,
        coordinator_factory=coordinator_factory,
        event_sink=event_sink,
        experiment_id_factory=experiment_id_factory or default_experiment_id,
        cancellation_event=cancellation_event,
        admission_validator=_FactoryCoordinatorAdmissionValidator(),
    )


class _FactoryCoordinatorAdmissionValidator:
    """Route real admission unchanged and admit only exact non-live test doubles."""

    def __init__(self) -> None:
        self._real = CoordinatorAdmissionValidator()

    def validate(
        self,
        coordinator: Any,
        request: ExperimentRuntimeRequest,
        configuration: RuntimeConfiguration,
    ) -> CoordinatorAdmission:
        if request.mode == ExecutionMode.REAL:
            return self._real.validate(coordinator, request, configuration)
        if type(coordinator) is not MutualSupervisionCoordinator:
            raise ValueError("non-real coordinator is not registered")
        if coordinator.mode != request.mode or coordinator.backend != request.backend:
            raise ValueError("non-real coordinator mode/backend does not match request")
        if type(coordinator.evidence_provider) is not FakeEvidenceProvider:
            raise ValueError("non-real evidence provider must be deterministic")
        if type(coordinator.recovery_monitor) is not FakeRecoveryMonitor:
            raise ValueError("non-real recovery monitor must not access a cluster")
        if coordinator.protocol.profile_id != request.protocol_profile:
            raise ValueError("non-real protocol profile does not match request")
        if type(coordinator.adapter_registry) is not AgentAdapterRegistry:
            raise ValueError("non-real agent registry is unsupported")
        expected_adapters = (
            (
                AutoGenProtocolAdapter,
                AutoGenProtocolAdapter,
                AutoGenProtocolAdapter,
                AutoGenProtocolAdapter,
            )
            if request.controller == "autogen"
            else (
                DeterministicHAAdapter,
                DeterministicApplicationAdapter,
                DeterministicInfrastructureAdapter,
                DeterministicCostAdapter,
            )
        )
        if tuple(type(adapter) for adapter in coordinator.adapters.values()) != expected_adapters:
            raise ValueError("non-real agent stage is unsupported")
        return CoordinatorAdmission(
            executor_timeout_seconds=15.0,
            evidence_timeout_seconds=1.0,
            stage_timeouts={
                name: float(configuration.timeouts[name])
                for name in (
                    "preflight_seconds",
                    "fault_ready_seconds",
                    "recovery_seconds",
                    "cleanup_seconds",
                )
            },
        )


def _deterministic_evidence_provider(
    request: ExperimentRuntimeRequest,
) -> FakeEvidenceProvider:
    availability_fault = request.metric == "availability"
    value = (
        0.0
        if availability_fault
        else request.threshold + max(abs(request.threshold) * 0.1, 1.0)
    )
    return FakeEvidenceProvider(
        EvidenceSnapshot(
            namespace=request.namespace,
            deployment=request.deployment,
            metric_values={request.metric: value},
            desired_replicas=1,
            available_replicas=0 if availability_fault else 1,
            pod_statuses=("Pending",) if availability_fault else ("Running",),
            events=(f"{request.mode.value} deterministic factory evidence",),
            source=f"factory-{request.mode.value}",
        )
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
