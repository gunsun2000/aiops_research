from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiops_k8s_agents.agent_registry import load_agent_registry
from aiops_k8s_agents.coordinator import AIMCMPCoordinator
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.models import AlertEvent, CommandResult
from aiops_k8s_agents.validator import CommandValidator


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
        "scenarios": [
            "pod-kill",
            "cpu-stress",
            "memory-stress",
            "network-delay",
        ],
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
