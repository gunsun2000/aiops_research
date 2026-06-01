from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from aiops_k8s_agents.models import ScaleAction

K8S_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class CommandValidationError(ValueError):
    """액션이나 자유 형식 명령어가 실행하기에 안전하지 않을 때 발생합니다."""


@dataclass(frozen=True)
class CommandValidator:
    allowed_namespaces: set[str]
    allowed_deployments: set[str]
    min_replicas: int = 1
    max_replicas: int = 5

    def validate_scale_action(self, action: ScaleAction) -> ScaleAction:
        self._validate_k8s_name("namespace", action.namespace)
        self._validate_k8s_name("deployment", action.deployment)
        if action.namespace not in self.allowed_namespaces:
            raise CommandValidationError(f"namespace가 allowlist에 없습니다: {action.namespace}")
        if action.deployment not in self.allowed_deployments:
            raise CommandValidationError(
                f"deployment가 allowlist에 없습니다: {action.deployment}"
            )
        if not isinstance(action.replicas, int):
            raise CommandValidationError("replicas는 정수여야 합니다")
        if action.replicas < self.min_replicas or action.replicas > self.max_replicas:
            raise CommandValidationError(
                f"replicas는 {self.min_replicas} 이상 {self.max_replicas} 이하여야 합니다"
            )
        return action

    def validate_command(self, command: str) -> ScaleAction:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise CommandValidationError(str(exc)) from exc

        if len(parts) != 7:
            raise CommandValidationError("명령어가 승인된 scale 템플릿과 일치해야 합니다")
        if parts[:3] != ["kubectl", "scale", "deployment"]:
            raise CommandValidationError("kubectl scale deployment만 허용됩니다")
        if not parts[4].startswith("--replicas="):
            raise CommandValidationError("replicas는 --replicas=<N> 형식이어야 합니다")
        if parts[5] != "-n":
            raise CommandValidationError("namespace는 -n <namespace> 형식이어야 합니다")

        replicas_text = parts[4].split("=", 1)[1]
        if not replicas_text.isdecimal():
            raise CommandValidationError("replicas는 양의 정수여야 합니다")

        action = ScaleAction(
            namespace=parts[6],
            deployment=parts[3],
            replicas=int(replicas_text),
            reason="명령어 텍스트에서 검증됨",
        )
        return self.validate_scale_action(action)

    @staticmethod
    def _validate_k8s_name(field: str, value: str) -> None:
        if not K8S_NAME_PATTERN.fullmatch(value):
            raise CommandValidationError(f"{field}가 유효한 Kubernetes 이름이 아닙니다: {value}")


def render_scale_command(action: ScaleAction) -> str:
    return (
        f"kubectl scale deployment {action.deployment} "
        f"--replicas={action.replicas} -n {action.namespace}"
    )
