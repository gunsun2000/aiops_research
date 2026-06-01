from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from aiops_k8s_agents.models import CommandResult, ScaleAction
from aiops_k8s_agents.validator import CommandValidator, render_scale_command

Runner = Callable[[list[str]], tuple[int, str, str]]


class ExecutionMode(str, Enum):
    MOCK = "mock"
    DRY_RUN = "dry-run"
    REAL = "real"


def subprocess_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
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

    def execute_scale(self, action: ScaleAction) -> CommandResult:
        validated = self.validator.validate_scale_action(action)
        command = render_scale_command(validated)

        if self.mode == ExecutionMode.MOCK:
            return CommandResult(
                command=command,
                mode=self.mode.value,
                valid=True,
                stdout="mock: 명령어를 검증했으며 실제 실행하지 않았습니다",
                stderr="",
            )

        argv = self._scale_argv(validated)
        if self.mode == ExecutionMode.DRY_RUN:
            argv = [*argv, "--dry-run=server"]

        return_code, stdout, stderr = self.runner(argv)
        return CommandResult(
            command=command,
            mode=self.mode.value,
            valid=return_code == 0,
            stdout=stdout,
            stderr=stderr,
        )

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
