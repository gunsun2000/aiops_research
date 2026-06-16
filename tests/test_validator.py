import pytest

from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind, ScaleAction
from aiops_k8s_agents.validator import (
    CommandValidationError,
    CommandValidator,
    validate_recovery_command,
    render_recovery_command,
    render_scale_command,
)


def test_renders_only_allowed_kubectl_scale_command():
    action = ScaleAction(
        namespace="online-boutique",
        deployment="paymentservice",
        replicas=3,
        reason="CPU usage is above threshold",
    )
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )

    validated = validator.validate_scale_action(action)

    assert render_scale_command(validated) == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )


@pytest.mark.parametrize(
    "action",
    [
        ScaleAction("prod", "paymentservice", 3, "namespace is not allowed"),
        ScaleAction("online-boutique", "frontend", 3, "deployment is not allowed"),
        ScaleAction("online-boutique", "paymentservice", 0, "replicas too low"),
        ScaleAction("online-boutique", "paymentservice", 99, "replicas too high"),
        ScaleAction("Online_Boutique", "paymentservice", 3, "bad namespace syntax"),
        ScaleAction("online-boutique", "payment_service", 3, "bad deployment syntax"),
    ],
)
def test_rejects_invalid_or_unsafe_scale_actions(action):
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )

    with pytest.raises(CommandValidationError):
        validator.validate_scale_action(action)


@pytest.mark.parametrize(
    "command",
    [
        "kubctll scale deployment paymentservice --replicas=3 -n online-boutique",
        "kubectl delete deployment paymentservice -n online-boutique",
        "kubectl scale deployment frontend --replicas=3 -n online-boutique",
        "kubectl scale deployment paymentservice --replicas=9 -n online-boutique",
    ],
)
def test_rejects_free_form_commands_that_do_not_match_allowlist(command):
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )

    with pytest.raises(CommandValidationError):
        validator.validate_command(command)


@pytest.mark.parametrize(
    ("kind", "replicas", "expected"),
    [
        (
            RecoveryActionKind.OBSERVE_ONLY,
            None,
            "kubectl get deployment paymentservice -n online-boutique -o json",
        ),
        (
            RecoveryActionKind.ROLLOUT_RESTART,
            None,
            "kubectl rollout restart deployment paymentservice -n online-boutique",
        ),
        (
            RecoveryActionKind.SCALE_OUT,
            3,
            "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
        ),
    ],
)
def test_validates_and_renders_bounded_recovery_actions(kind, replicas, expected):
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
    )
    action = RecoveryAction(
        namespace="online-boutique",
        deployment="paymentservice",
        kind=kind,
        replicas=replicas,
        reason="pilot candidate",
    )

    validated = validator.validate_recovery_action(action)

    assert render_recovery_command(validated) == expected


def test_recovery_action_rejects_missing_scale_replicas_and_non_allowlisted_target():
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
    )

    with pytest.raises(CommandValidationError):
        validator.validate_recovery_action(
            RecoveryAction(
                "online-boutique",
                "paymentservice",
                RecoveryActionKind.SCALE_OUT,
                reason="missing replicas",
            )
        )

    with pytest.raises(CommandValidationError):
        validator.validate_recovery_action(
            RecoveryAction(
                "online-boutique",
                "frontend",
                RecoveryActionKind.ROLLOUT_RESTART,
                reason="not allowlisted",
            )
        )


@pytest.mark.parametrize(
    ("command", "expected_kind", "expected_replicas"),
    [
        (
            "kubectl get deployment paymentservice -n online-boutique -o json",
            RecoveryActionKind.OBSERVE_ONLY,
            None,
        ),
        (
            "kubectl rollout restart deployment paymentservice -n online-boutique --dry-run=server",
            RecoveryActionKind.ROLLOUT_RESTART,
            None,
        ),
        (
            "kubectl scale deployment paymentservice --replicas=3 -n online-boutique --dry-run=server",
            RecoveryActionKind.SCALE_OUT,
            3,
        ),
    ],
)
def test_validates_recovery_commands_from_go_guard(
    command, expected_kind, expected_replicas
):
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )

    action = validate_recovery_command(command, validator)

    assert action.kind == expected_kind
    assert action.namespace == "online-boutique"
    assert action.deployment == "paymentservice"
    assert action.replicas == expected_replicas


@pytest.mark.parametrize(
    "command",
    [
        "kubectl get deployment paymentservice -n online-boutique",
        "kubectl rollout restart deployment paymentservice -n online-boutique --dry-run=client",
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique --dry-run=client",
        "kubectl rollout restart deployment frontend -n online-boutique --dry-run=server",
    ],
)
def test_rejects_recovery_commands_that_drift_from_go_contract(command):
    validator = CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )

    with pytest.raises(CommandValidationError):
        validate_recovery_command(command, validator)
