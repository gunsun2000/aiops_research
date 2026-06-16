from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind, ScaleAction

K8S_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class CommandValidationError(ValueError):
    """Raised when a structured action or command is unsafe to execute."""


@dataclass(frozen=True)
class CommandValidator:
    allowed_namespaces: set[str]
    allowed_deployments: set[str]
    min_replicas: int = 1
    max_replicas: int = 5

    def validate_scale_action(self, action: ScaleAction) -> ScaleAction:
        self._validate_target(action.namespace, action.deployment)
        self._validate_replicas(action.replicas)
        return action

    def validate_recovery_action(self, action: RecoveryAction) -> RecoveryAction:
        self._validate_target(action.namespace, action.deployment)
        if not isinstance(action.kind, RecoveryActionKind):
            raise CommandValidationError("recovery action kind is not allowed")
        if action.kind == RecoveryActionKind.SCALE_OUT:
            if action.replicas is None:
                raise CommandValidationError("scale_out requires replicas")
            self._validate_replicas(action.replicas)
        elif action.replicas is not None:
            raise CommandValidationError("only scale_out accepts replicas")
        return action

    def validate_command(self, command: str) -> ScaleAction:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise CommandValidationError(str(exc)) from exc

        if len(parts) not in {7, 8}:
            raise CommandValidationError("command must match the approved scale template")
        if parts[:3] != ["kubectl", "scale", "deployment"]:
            raise CommandValidationError("only kubectl scale deployment is allowed")
        if not parts[4].startswith("--replicas="):
            raise CommandValidationError("replicas must use --replicas=<N>")
        if parts[5] != "-n":
            raise CommandValidationError("namespace must use -n <namespace>")
        if len(parts) == 8 and parts[7] != "--dry-run=server":
            raise CommandValidationError("dry-run must use --dry-run=server")

        replicas_text = parts[4].split("=", 1)[1]
        if not replicas_text.isdecimal():
            raise CommandValidationError("replicas must be a positive integer")

        action = ScaleAction(
            namespace=parts[6],
            deployment=parts[3],
            replicas=int(replicas_text),
            reason="validated from an approved command template",
        )
        return self.validate_scale_action(action)

    def _validate_target(self, namespace: str, deployment: str) -> None:
        self._validate_k8s_name("namespace", namespace)
        self._validate_k8s_name("deployment", deployment)
        if namespace not in self.allowed_namespaces:
            raise CommandValidationError(f"namespace is not allowlisted: {namespace}")
        if deployment not in self.allowed_deployments:
            raise CommandValidationError(f"deployment is not allowlisted: {deployment}")

    def _validate_replicas(self, replicas: object) -> None:
        if not isinstance(replicas, int):
            raise CommandValidationError("replicas must be an integer")
        if replicas < self.min_replicas or replicas > self.max_replicas:
            raise CommandValidationError(
                f"replicas must be between {self.min_replicas} and {self.max_replicas}"
            )

    @staticmethod
    def _validate_k8s_name(field: str, value: str) -> None:
        if not K8S_NAME_PATTERN.fullmatch(value):
            raise CommandValidationError(
                f"{field} is not a valid Kubernetes name: {value}"
            )


def render_scale_command(action: ScaleAction) -> str:
    return (
        f"kubectl scale deployment {action.deployment} "
        f"--replicas={action.replicas} -n {action.namespace}"
    )


def render_recovery_command(action: RecoveryAction) -> str:
    if action.kind == RecoveryActionKind.OBSERVE_ONLY:
        return (
            f"kubectl get deployment {action.deployment} "
            f"-n {action.namespace} -o json"
        )
    if action.kind == RecoveryActionKind.ROLLOUT_RESTART:
        return (
            f"kubectl rollout restart deployment {action.deployment} "
            f"-n {action.namespace}"
        )
    if action.kind == RecoveryActionKind.SCALE_OUT and action.replicas is not None:
        return render_scale_command(
            ScaleAction(
                namespace=action.namespace,
                deployment=action.deployment,
                replicas=action.replicas,
                reason=action.reason,
            )
        )
    raise CommandValidationError("unsupported recovery action")


def validate_recovery_command(
    command: str, validator: CommandValidator
) -> RecoveryAction:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise CommandValidationError(str(exc)) from exc

    if _is_observe_command(parts):
        action = RecoveryAction(
            namespace=parts[5],
            deployment=parts[3],
            kind=RecoveryActionKind.OBSERVE_ONLY,
            reason="validated from an approved observe command template",
        )
        return validator.validate_recovery_action(action)

    if _is_rollout_restart_command(parts):
        action = RecoveryAction(
            namespace=parts[6],
            deployment=parts[4],
            kind=RecoveryActionKind.ROLLOUT_RESTART,
            reason="validated from an approved rollout restart command template",
        )
        return validator.validate_recovery_action(action)

    if _is_scale_command(parts):
        scale_action = validator.validate_command(command)
        return RecoveryAction(
            namespace=scale_action.namespace,
            deployment=scale_action.deployment,
            kind=RecoveryActionKind.SCALE_OUT,
            replicas=scale_action.replicas,
            reason="validated from an approved scale command template",
        )

    raise CommandValidationError("command must match an approved recovery template")


def _is_observe_command(parts: list[str]) -> bool:
    return (
        len(parts) == 8
        and parts[:3] == ["kubectl", "get", "deployment"]
        and parts[4] == "-n"
        and parts[6:] == ["-o", "json"]
    )


def _is_rollout_restart_command(parts: list[str]) -> bool:
    if len(parts) not in {7, 8}:
        return False
    if parts[:4] != ["kubectl", "rollout", "restart", "deployment"]:
        return False
    if parts[5] != "-n":
        return False
    return len(parts) == 7 or parts[7] == "--dry-run=server"


def _is_scale_command(parts: list[str]) -> bool:
    return (
        len(parts) in {7, 8}
        and parts[:3] == ["kubectl", "scale", "deployment"]
        and parts[4].startswith("--replicas=")
        and parts[5] == "-n"
        and (len(parts) == 7 or parts[7] == "--dry-run=server")
    )
