from unittest.mock import Mock

import pytest

from aiops_k8s_agents.executor import ExecutionMode, KubernetesExecutor
from aiops_k8s_agents.models import ScaleAction
from aiops_k8s_agents.validator import CommandValidationError, CommandValidator


def test_mock_mode_validates_and_does_not_call_subprocess():
    runner = Mock()
    executor = KubernetesExecutor(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
        runner=runner,
    )

    result = executor.execute_scale(
        ScaleAction("online-boutique", "paymentservice", 3, "CPU above threshold")
    )

    assert result.valid is True
    assert result.mode == "mock"
    assert result.stdout == "mock: 명령어를 검증했으며 실제 실행하지 않았습니다"
    runner.assert_not_called()


def test_dry_run_mode_uses_same_rendered_command_with_server_dry_run():
    runner = Mock(return_value=(0, "deployment.apps/paymentservice scaled", ""))
    executor = KubernetesExecutor(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.DRY_RUN,
        runner=runner,
    )

    result = executor.execute_scale(
        ScaleAction("online-boutique", "paymentservice", 3, "CPU above threshold")
    )

    assert result.command == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )
    assert result.valid is True
    runner.assert_called_once_with(
        [
            "kubectl",
            "scale",
            "deployment",
            "paymentservice",
            "--replicas=3",
            "-n",
            "online-boutique",
            "--dry-run=server",
        ]
    )


def test_real_mode_refuses_to_run_invalid_actions():
    runner = Mock()
    executor = KubernetesExecutor(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.REAL,
        runner=runner,
    )

    with pytest.raises(CommandValidationError):
        executor.execute_scale(
            ScaleAction("online-boutique", "frontend", 3, "not allowlisted")
        )

    runner.assert_not_called()
