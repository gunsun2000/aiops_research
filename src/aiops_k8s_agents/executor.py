from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from aiops_k8s_agents.models import (
    CommandResult,
    RecoveryAction,
    RecoveryActionKind,
    ScaleAction,
)
from aiops_k8s_agents.validator import (
    CommandValidationError,
    CommandValidator,
    validate_recovery_command,
    render_recovery_command,
    render_scale_command,
)

Runner = Callable[[list[str]], tuple[int, str, str]]
GoGuardRunner = Callable[[list[str], str, Path], tuple[int, str, str]]


class ExecutionMode(str, Enum):
    MOCK = "mock"
    DRY_RUN = "dry-run"
    REAL = "real"


class ExecutionBackend(str, Enum):
    PYTHON = "python"
    GO = "go"


def subprocess_runner(
    argv: list[str],
    timeout_seconds: float = 15.0,
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"command timed out after {timeout_seconds}s: {exc}"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def go_guard_subprocess_runner(
    argv: list[str],
    input_text: str,
    cwd: Path,
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            input=input_text,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


@dataclass
class KubernetesExecutor:
    validator: CommandValidator
    mode: ExecutionMode = ExecutionMode.MOCK
    runner: Runner = subprocess_runner
    backend: ExecutionBackend = ExecutionBackend.PYTHON
    go_guard_runner: GoGuardRunner = go_guard_subprocess_runner
    go_guard_dir: Path | None = None

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.backend, str):
            self.backend = ExecutionBackend(self.backend)

    def execute_scale(self, action: ScaleAction) -> CommandResult:
        validated = self.validator.validate_scale_action(action)
        command = render_scale_command(validated)

        if self.backend == ExecutionBackend.GO:
            return self._execute_with_go_guard(
                namespace=validated.namespace,
                deployment=validated.deployment,
                kind=RecoveryActionKind.SCALE_OUT,
                replicas=validated.replicas,
                fallback_command=command,
            )

        if self.mode == ExecutionMode.MOCK:
            return self._mock_result(command)

        argv = self._scale_argv(validated)
        if self.mode == ExecutionMode.DRY_RUN:
            argv = [*argv, "--dry-run=server"]
        return self._run(command, argv)

    def execute_recovery(self, action: RecoveryAction) -> CommandResult:
        validated = self.validator.validate_recovery_action(action)
        command = render_recovery_command(validated)

        if self.backend == ExecutionBackend.GO:
            return self._execute_with_go_guard(
                namespace=validated.namespace,
                deployment=validated.deployment,
                kind=validated.kind,
                replicas=validated.replicas,
                fallback_command=command,
            )

        if self.mode == ExecutionMode.MOCK:
            return self._mock_result(command)

        argv = self._recovery_argv(validated)
        if (
            self.mode == ExecutionMode.DRY_RUN
            and validated.kind != RecoveryActionKind.OBSERVE_ONLY
        ):
            argv = [*argv, "--dry-run=server"]
        return self._run(command, argv)

    def _mock_result(self, command: str) -> CommandResult:
        return CommandResult(
            command=command,
            mode=self.mode.value,
            valid=True,
            stdout="mock: 명령어를 검증했으며 실제 실행하지 않았습니다",
            stderr="",
        )

    def _run(self, command: str, argv: list[str]) -> CommandResult:
        return_code, stdout, stderr = self.runner(argv)
        return CommandResult(
            command=command,
            mode=self.mode.value,
            valid=return_code == 0,
            stdout=stdout,
            stderr=stderr,
        )

    def _execute_with_go_guard(
        self,
        namespace: str,
        deployment: str,
        kind: RecoveryActionKind,
        replicas: int | None,
        fallback_command: str,
    ) -> CommandResult:
        request = {
            "mode": self.mode.value,
            "namespace": namespace,
            "deployment": deployment,
            "action": kind.value,
            "replicas": replicas,
            "allowed_namespaces": sorted(self.validator.allowed_namespaces),
            "allowed_deployments": sorted(self.validator.allowed_deployments),
            "min_replicas": self.validator.min_replicas,
            "max_replicas": self.validator.max_replicas,
        }
        if replicas is None:
            request.pop("replicas")

        input_text = json.dumps(request, ensure_ascii=False, indent=2)
        return_code, stdout, stderr = self.go_guard_runner(
            ["go", "run", "./cmd/aiops-guard", "--input", "-"],
            input_text,
            self._go_guard_dir(),
        )
        result = self._parse_go_guard_result(
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            fallback_command=fallback_command,
        )
        return self._cross_validate_go_guard_result(result)

    def _parse_go_guard_result(
        self,
        return_code: int,
        stdout: str,
        stderr: str,
        fallback_command: str,
    ) -> CommandResult:
        metadata = {"guard_backend": "go", "go_guard": "aiops-guard"}
        if stdout:
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                return CommandResult(
                    command=fallback_command,
                    mode=self.mode.value,
                    valid=False,
                    stdout="",
                    stderr=f"Go guard returned invalid JSON: {stdout}",
                    metadata=metadata,
                )
            return CommandResult(
                command=str(data.get("command", "")),
                mode=str(data.get("mode", self.mode.value)),
                valid=bool(data.get("valid", False)) and return_code == 0,
                stdout=str(data.get("stdout", "")),
                stderr=str(data.get("stderr", stderr)),
                metadata=metadata,
            )
        return CommandResult(
            command=fallback_command,
            mode=self.mode.value,
            valid=False,
            stdout="",
            stderr=stderr or f"Go guard exited with code {return_code}",
            metadata=metadata,
        )

    def _cross_validate_go_guard_result(self, result: CommandResult) -> CommandResult:
        if not result.valid:
            return result
        try:
            validate_recovery_command(result.command, self.validator)
        except CommandValidationError as exc:
            return CommandResult(
                command=result.command,
                mode=result.mode,
                valid=False,
                stdout=result.stdout,
                stderr=f"Python-Go cross-check failed: {exc}",
                metadata=result.metadata,
            )
        return result

    def _go_guard_dir(self) -> Path:
        if self.go_guard_dir is not None:
            return self.go_guard_dir
        return Path(__file__).resolve().parents[2] / "go" / "aiops-guard"

    @staticmethod
    def _scale_argv(action: ScaleAction) -> list[str]:
        return [
            "kubectl",
            "scale",
            "deployment",
            action.deployment,
            f"--replicas={action.replicas}",
            "-n",
            action.namespace,
        ]

    @staticmethod
    def _recovery_argv(action: RecoveryAction) -> list[str]:
        if action.kind == RecoveryActionKind.OBSERVE_ONLY:
            return [
                "kubectl",
                "get",
                "deployment",
                action.deployment,
                "-n",
                action.namespace,
                "-o",
                "json",
            ]
        if action.kind == RecoveryActionKind.ROLLOUT_RESTART:
            return [
                "kubectl",
                "rollout",
                "restart",
                "deployment",
                action.deployment,
                "-n",
                action.namespace,
            ]
        if action.kind == RecoveryActionKind.SCALE_OUT and action.replicas is not None:
            return KubernetesExecutor._scale_argv(
                ScaleAction(
                    namespace=action.namespace,
                    deployment=action.deployment,
                    replicas=action.replicas,
                    reason=action.reason,
                )
            )
        raise ValueError("unsupported recovery action")
