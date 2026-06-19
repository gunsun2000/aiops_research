from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from aiops_k8s_agents.agents import AIMCMPCoordinator
from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
from aiops_k8s_agents.cost_agent import CostOptimizationAgent
from aiops_k8s_agents.deployment_renderer import (
    DEPLOYMENT_DRY_RUN_COMMAND,
    render_deployment_manifest,
)
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
from aiops_k8s_agents.inference_optimizer import (
    build_inference_deployment_plan,
    load_inference_optimization_config,
    recommend_inference_placement,
)
from aiops_k8s_agents.models import AlertEvent
from aiops_k8s_agents.ops_llm_selection import (
    OpsLLMSelectionError,
    load_ops_llm_benchmark_config,
    select_ops_llm,
)
from aiops_k8s_agents.validator import CommandValidationError, CommandValidator

DEFAULT_OPS_LLM_CONFIG = Path("config/ops_llm_benchmark.json")
DEFAULT_INFERENCE_CONFIG = Path("config/inference_optimization.json")


@dataclass
class AIServiceOperationsPipeline:
    """Top-level AI service operations pipeline centered on the 4-Agent flow."""

    llm_config_path: str | Path = DEFAULT_OPS_LLM_CONFIG
    inference_config_path: str | Path = DEFAULT_INFERENCE_CONFIG
    mode: ExecutionMode = ExecutionMode.MOCK
    guard_backend: ExecutionBackend = ExecutionBackend.PYTHON
    allowed_namespaces: set[str] = field(default_factory=set)
    allowed_deployments: set[str] = field(default_factory=set)
    min_replicas: int = 1
    max_replicas: int = 5
    application_agent: AIApplicationManagementAgent = field(
        default_factory=AIApplicationManagementAgent
    )
    infrastructure_agent: AISemiconductorInfraOpsAgent = field(
        default_factory=AISemiconductorInfraOpsAgent
    )
    cost_agent: CostOptimizationAgent = field(default_factory=CostOptimizationAgent)

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.guard_backend, str):
            self.guard_backend = ExecutionBackend(self.guard_backend)

    def prepare_service(
        self,
        workload_id: str,
        llm_policy: str = "quality_first",
    ) -> dict[str, Any]:
        llm_result = self._select_llm(llm_policy)
        runtime_model = _runtime_model_from_selection(llm_result.to_dict())

        inference_config = load_inference_optimization_config(self.inference_config_path)
        placement = recommend_inference_placement(inference_config, workload_id)
        deployment_plan = build_inference_deployment_plan(inference_config, workload_id)
        manifest = render_deployment_manifest(deployment_plan)

        application_review = self.application_agent.plan_deployment(
            deployment_plan,
            placement_decision=placement,
        )
        infrastructure_review = self.infrastructure_agent.review_operation(
            placement_decision=placement
        )
        cost_review = self.cost_agent.review_operation(placement_decision=placement)
        deployment_dry_run = self._validate_deployment_manifest(manifest)

        return {
            "selected_llm": llm_result.selected_model,
            "autogen_runtime_model": runtime_model,
            "llm_selection": llm_result.to_dict(),
            "selected_resource": placement.selected_resource,
            "placement_decision": placement.to_dict(),
            "deployment_plan": deployment_plan.deployment_plan,
            "inference_deployment_plan": deployment_plan.to_dict(),
            "deployment_manifest": manifest,
            "deployment_dry_run": deployment_dry_run,
            "agent_reviews": {
                "application": asdict(application_review),
                "infrastructure": asdict(infrastructure_review),
                "cost": asdict(cost_review),
            },
        }

    def create_selected_autogen_model_client(
        self,
        workload_id: str,
        llm_policy: str,
        model_client_factory: Callable[[str], Any],
    ) -> Any:
        del workload_id
        llm_result = self._select_llm(llm_policy)
        return model_client_factory(_runtime_model_from_selection(llm_result.to_dict()))

    def operate_service(self, alert: AlertEvent | None = None) -> dict[str, Any]:
        if alert is None:
            return {
                "valid": True,
                "skipped": True,
                "reason": "no alert supplied; recovery pipeline readiness only",
            }

        validator = CommandValidator(
            allowed_namespaces=self.allowed_namespaces or {alert.namespace},
            allowed_deployments=self.allowed_deployments or {alert.service},
            min_replicas=self.min_replicas,
            max_replicas=self.max_replicas,
        )
        backend = (
            ExecutionBackend.PYTHON
            if self.mode is ExecutionMode.MOCK
            else self.guard_backend
        )
        coordinator = AIMCMPCoordinator(
            validator=validator,
            mode=self.mode,
            backend=backend,
        )
        try:
            result = coordinator.run(alert)
        except CommandValidationError as exc:
            return {
                "command": "",
                "mode": self.mode.value,
                "valid": False,
                "stdout": "",
                "stderr": str(exc),
                "metadata": {"coordinator": "AI-MCMP", "consensus": "rejected"},
            }
        return asdict(result)

    def run(
        self,
        workload_id: str,
        llm_policy: str = "quality_first",
        alert: AlertEvent | None = None,
    ) -> dict[str, Any]:
        preparation = self.prepare_service(
            workload_id=workload_id,
            llm_policy=llm_policy,
        )
        recovery = self.operate_service(alert=alert)
        reviews = preparation["agent_reviews"]
        reviews_approved = all(review["approved"] for review in reviews.values())
        ready = bool(
            preparation["deployment_dry_run"]["valid"]
            and reviews_approved
            and recovery.get("valid", False)
        )
        return {
            "command": "run-service-operations",
            "valid": ready,
            "selected_llm": preparation["selected_llm"],
            "autogen_runtime_model": preparation["autogen_runtime_model"],
            "selected_resource": preparation["selected_resource"],
            "deployment_plan": preparation["deployment_plan"],
            "inference_deployment_plan": preparation["inference_deployment_plan"],
            "deployment_manifest": preparation["deployment_manifest"],
            "deployment_dry_run": preparation["deployment_dry_run"],
            "agent_reviews": reviews,
            "recovery": recovery,
            "recovery_pipeline_ready": ready,
            "guard_backend": self.guard_backend.value,
            "metadata": {
                "llm_policy": llm_policy,
                "workload": workload_id,
                "mode": self.mode.value,
            },
        }

    def _select_llm(self, llm_policy: str):
        config = load_ops_llm_benchmark_config(self.llm_config_path)
        return select_ops_llm(config, policy_name=llm_policy)

    def _validate_deployment_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if self.mode is ExecutionMode.MOCK:
            return {
                "command": DEPLOYMENT_DRY_RUN_COMMAND,
                "mode": self.mode.value,
                "valid": True,
                "stdout": "mock: deployment manifest generated and not applied",
                "stderr": "",
            }

        completed = subprocess.run(
            DEPLOYMENT_DRY_RUN_COMMAND.split(),
            input=json.dumps(manifest, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "command": DEPLOYMENT_DRY_RUN_COMMAND,
            "mode": self.mode.value,
            "valid": completed.returncode == 0,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }


def _runtime_model_from_selection(selection: dict[str, Any]) -> str:
    selected_model = str(selection["selected_model"])
    if selected_model != "codex-cross-check-agent":
        return selected_model

    for candidate in selection.get("ranking", []):
        model = str(candidate.get("model", ""))
        if model and model != "codex-cross-check-agent":
            return model
    raise OpsLLMSelectionError("no runtime LLM model candidate is available")
