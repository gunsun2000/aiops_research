from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from aiops_k8s_agents.agent_registry import load_agent_registry
from aiops_k8s_agents.coordinator import AIMCMPCoordinator
from aiops_k8s_agents.evidence import (
    EvidenceSnapshot,
    FakeEvidenceProvider,
    SequencedEvidenceProvider,
)
from aiops_k8s_agents.experiment_session import (
    ExperimentSession,
    InMemoryExperimentSessionStore,
    normalize_experiment_session,
)
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.models import AlertEvent, CommandResult
from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
from aiops_k8s_agents.mutual_supervision_policy import (
    load_mutual_supervision_policy,
)
from aiops_k8s_agents.recovery_monitor import FakeRecoveryMonitor
from aiops_k8s_agents.validator import CommandValidator


_SCENARIOS = MappingProxyType(
    {
        "pod-kill": {
            "scenario_id": "pod-kill",
            "label": "Pod Kill",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric": "availability",
            "value": 0.0,
            "threshold": 1.0,
            "desired_replicas": 1,
            "available_replicas": 0,
            "pod_statuses": ("Terminating",),
            "after_value": 1.0,
            "after_desired_replicas": 3,
            "after_available_replicas": 3,
            "after_pod_statuses": ("Running",),
            "signal": "ready / available replicas",
            "summary": (
                "Pod 종료 상태에서 Kubernetes 자체 복구와 "
                "4-Agent 추가 조치 판단을 비교합니다."
            ),
            "mode": "mock",
        },
        "cpu-stress": {
            "scenario_id": "cpu-stress",
            "label": "CPU Stress",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric": "cpu",
            "value": 95.0,
            "threshold": 80.0,
            "signal": "container CPU usage",
            "summary": (
                "CPU 포화 Evidence에 대해 역할별 판단과 "
                "bounded recovery Action을 검증합니다."
            ),
            "mode": "mock",
        },
        "memory-stress": {
            "scenario_id": "memory-stress",
            "label": "Memory Stress",
            "namespace": "online-boutique",
            "deployment": "checkoutservice",
            "metric": "memory",
            "value": 95.7,
            "threshold": 80.0,
            "signal": "working set / restart count",
            "summary": (
                "메모리 포화와 OOM 위험에 대한 Agent 합의와 "
                "복구 Action을 검증합니다."
            ),
            "mode": "mock",
        },
        "network-delay": {
            "scenario_id": "network-delay",
            "label": "Network Delay",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric": "latency",
            "value": 0.234,
            "threshold": 0.1,
            "signal": "probe duration",
            "summary": (
                "서비스 지연 Evidence에 대한 원인 진단과 "
                "복구 후 평가 흐름을 검증합니다."
            ),
            "mode": "mock",
        },
    }
)
_EXPERIMENT_SESSIONS = InMemoryExperimentSessionStore(max_sessions=50)


def project_root() -> Path:
    configured = os.environ.get("AIOPS_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def build_overview(root: Path | None = None) -> dict[str, Any]:
    repo = root or project_root()
    latest_recovery = latest_recovery_run(repo)
    latest_final = latest_final_run(repo)
    return {
        "project": "AIOps 4-Agent Control Plane",
        "tagline": "Safety-bounded Kubernetes recovery research interface",
        "root": str(repo),
        "execution_modes": ["mock", "dry-run", "real"],
        "default_mode": "mock",
        "safety_layers": [
            "Agent Registry",
            "Action / Reward cross-check",
            "Python Validator",
            "Optional Go Guard",
            "Kubernetes dry-run",
            "Post-action recovery monitor",
        ],
        "scenarios": [item["scenario_id"] for item in scenario_catalog()],
        "actions": ["observe_only", "rollout_restart", "scale_out"],
        "latest_recovery_run": latest_recovery,
        "latest_final_run": latest_final,
        "health": {
            "agent_registry": (repo / "config" / "agent_registry.json").exists(),
            "recovery_config": (
                repo / "config" / "recovery_action_experiments.json"
            ).exists(),
            "chaos_manifests": (repo / "k8s" / "chaos").exists(),
            "runs_dir": (repo / "runs").exists(),
        },
    }


def agent_cards(root: Path | None = None) -> list[dict[str, Any]]:
    repo = root or project_root()
    registry = load_agent_registry(repo / "config" / "agent_registry.json")
    return [
        {
            "name": profile.name,
            "label": profile.korean_name,
            "role": profile.role,
            "responsibilities": list(profile.responsibilities),
            "bounded_actions": list(profile.bounded_actions),
            "reward_signals": list(profile.reward_signals),
            "enabled": profile.enabled,
        }
        for profile in registry.agents.values()
    ]


def latest_recovery_run(root: Path | None = None) -> dict[str, Any] | None:
    repo = root or project_root()
    latest = _latest_child_dir(repo / "runs" / "recovery-action-pilot")
    if latest is None:
        return None
    outcomes = latest / "outcomes.jsonl"
    statistics_dir = latest / "statistics"
    return {
        "name": latest.name,
        "path": _relative_path(latest, repo),
        "outcome_count": _count_jsonl(outcomes),
        "has_reward_policy": (
            latest / "analysis" / "reward_policy_comparison.md"
        ).exists(),
        "has_statistics": statistics_dir.exists(),
        "statistics_files": [
            _relative_path(path, repo)
            for path in sorted(statistics_dir.glob("*"))
            if path.is_file()
        ],
        "reward_policy_excerpt": _read_text_excerpt(
            latest / "analysis" / "reward_policy_comparison.md",
            limit=3500,
        ),
        "quantitative_summary_excerpt": _read_text_excerpt(
            statistics_dir / "quantitative_summary.md",
            limit=3500,
        ),
    }


def latest_final_run(root: Path | None = None) -> dict[str, Any] | None:
    repo = root or project_root()
    latest = _latest_child_dir(repo / "runs" / "final-real")
    if latest is None:
        return None
    return {
        "name": latest.name,
        "path": _relative_path(latest, repo),
        "summary_excerpt": _read_text_excerpt(latest / "final_summary.md", limit=3000),
        "summary_exists": (latest / "final_summary.md").exists(),
    }


def run_mock_alert(
    *,
    namespace: str,
    deployment: str,
    metric: str,
    value: float,
    threshold: float,
    min_replicas: int = 1,
    max_replicas: int = 5,
    backend: str = "python",
) -> dict[str, Any]:
    execution_backend = ExecutionBackend.GO if backend == "go" else ExecutionBackend.PYTHON
    validator = CommandValidator(
        allowed_namespaces={namespace},
        allowed_deployments={deployment},
        min_replicas=min_replicas,
        max_replicas=max_replicas,
    )
    coordinator = AIMCMPCoordinator(
        validator=validator,
        mode=ExecutionMode.MOCK,
        backend=execution_backend,
    )
    result = coordinator.run(
        AlertEvent(
            namespace=namespace,
            service=deployment,
            metric=metric,
            value=value,
            threshold=threshold,
            message=f"{deployment} {metric} value={value} threshold={threshold}",
        )
    )
    return {
        "result": command_result_to_dict(result),
        "agent_reviews": parse_agent_reviews(result.metadata),
    }


def run_mutual_supervision_mock(
    *,
    namespace: str,
    deployment: str,
    metric: str,
    value: float,
    threshold: float,
    min_replicas: int = 1,
    max_replicas: int = 5,
    backend: str = "python",
    desired_replicas: int = 1,
    available_replicas: int = 1,
    pod_statuses: tuple[str, ...] = ("Running",),
    after_evidence: EvidenceSnapshot | None = None,
) -> dict[str, Any]:
    repo = project_root()
    execution_backend = (
        ExecutionBackend.GO
        if backend == "go"
        else ExecutionBackend.PYTHON
    )
    normalized_metric = metric.strip().lower().replace("-", "_")
    before_evidence = EvidenceSnapshot(
        namespace=namespace,
        deployment=deployment,
        metric_values={normalized_metric: value},
        desired_replicas=desired_replicas,
        available_replicas=available_replicas,
        pod_statuses=pod_statuses,
        events=("control-plane mutual-supervision mock",),
        source="control-plane-fake",
    )
    evidence_provider = (
        SequencedEvidenceProvider((before_evidence, after_evidence))
        if after_evidence is not None
        else FakeEvidenceProvider(before_evidence)
    )
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={namespace},
            allowed_deployments={deployment},
            min_replicas=min_replicas,
            max_replicas=max_replicas,
        ),
        evidence_provider=evidence_provider,
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        policy=load_mutual_supervision_policy(
            repo / "config" / "mutual_supervision_policy.json"
        ),
        mode=ExecutionMode.MOCK,
        backend=execution_backend,
    )
    return coordinator.run(
        namespace=namespace,
        deployment=deployment,
        metric=normalized_metric,
        threshold=threshold,
    )


def scenario_catalog() -> list[dict[str, Any]]:
    return [dict(definition) for definition in _SCENARIOS.values()]


def run_scenario_experiment_mock(
    *,
    scenario_id: str,
    backend: str = "python",
) -> ExperimentSession:
    normalized_id = scenario_id.strip().lower()
    definition = _SCENARIOS.get(normalized_id)
    if definition is None:
        raise ValueError(f"unknown scenario: {scenario_id}")

    report = run_mutual_supervision_mock(
        namespace=str(definition["namespace"]),
        deployment=str(definition["deployment"]),
        metric=str(definition["metric"]),
        value=float(definition["value"]),
        threshold=float(definition["threshold"]),
        backend=backend,
        desired_replicas=int(definition.get("desired_replicas", 1)),
        available_replicas=int(definition.get("available_replicas", 1)),
        pod_statuses=tuple(
            str(status)
            for status in definition.get("pod_statuses", ("Running",))
        ),
        after_evidence=_scenario_after_evidence(definition),
    )
    evidence = dict(report.get("evidence", {}))
    evidence["scenario"] = normalized_id
    report["evidence"] = evidence
    report["artifacts"] = {
        "scenario_manifest": (
            f"k8s/chaos/{_scenario_manifest_name(normalized_id)}"
        )
    }
    session = normalize_experiment_session(report)
    return _EXPERIMENT_SESSIONS.put(session)


def get_experiment_session(
    experiment_id: str,
) -> ExperimentSession | None:
    return _EXPERIMENT_SESSIONS.get(experiment_id)


def command_result_to_dict(result: CommandResult) -> dict[str, Any]:
    return asdict(result)


def parse_agent_reviews(metadata: dict[str, str]) -> list[dict[str, Any]]:
    agents = _split_csv(metadata.get("agents", ""))
    decisions = _split_pairs(metadata.get("decisions", ""))
    actions = _split_pairs(metadata.get("actions", ""))
    rewards = _split_pairs(metadata.get("rewards", ""))
    reviews: list[dict[str, Any]] = []
    for agent in agents:
        reviews.append(
            {
                "agent": agent,
                "decision": decisions.get(agent, ""),
                "action": actions.get(agent, ""),
                "reward": _optional_float(rewards.get(agent, "")),
            }
        )
    return reviews


def artifact_path(relative_path: str, root: Path | None = None) -> Path:
    repo = root or project_root()
    candidate = (repo / relative_path).resolve()
    allowed_roots = [
        (repo / "runs").resolve(),
        (repo / "docs").resolve(),
        (repo / "docs" / "assets").resolve(),
    ]
    if not any(candidate == base or base in candidate.parents for base in allowed_roots):
        raise ValueError("artifact path is outside allowed directories")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(relative_path)
    return candidate


def _latest_child_dir(path: Path) -> Path | None:
    if not path.exists():
        return None
    children = [child for child in path.iterdir() if child.is_dir()]
    if not children:
        return None
    return sorted(children, key=lambda child: (child.name, child.stat().st_mtime))[-1]


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


def _read_text_excerpt(path: Path, *, limit: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_pairs(value: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in value.split("|"):
        if ":" not in item:
            continue
        key, raw_value = item.split(":", 1)
        pairs[key.strip()] = raw_value.strip()
    return pairs


def _optional_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _scenario_manifest_name(scenario_id: str) -> str:
    names = {
        "pod-kill": "paymentservice-pod-kill.yaml",
        "cpu-stress": "paymentservice-cpu-stress.yaml",
        "memory-stress": "checkoutservice-memory-stress.yaml",
        "network-delay": "paymentservice-network-delay.yaml",
    }
    return names[scenario_id]


def _scenario_after_evidence(
    definition: Mapping[str, Any],
) -> EvidenceSnapshot | None:
    if "after_available_replicas" not in definition:
        return None
    metric = str(definition["metric"])
    return EvidenceSnapshot(
        namespace=str(definition["namespace"]),
        deployment=str(definition["deployment"]),
        metric_values={
            metric: float(definition.get("after_value", definition["value"]))
        },
        desired_replicas=int(
            definition.get(
                "after_desired_replicas",
                definition.get("desired_replicas", 1),
            )
        ),
        available_replicas=int(definition["after_available_replicas"]),
        pod_statuses=tuple(
            str(status)
            for status in definition.get("after_pod_statuses", ("Running",))
        ),
        events=("control-plane mock recovery observed",),
        source="control-plane-fake",
    )
