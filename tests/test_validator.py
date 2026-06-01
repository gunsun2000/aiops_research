import pytest

from aiops_k8s_agents.models import ScaleAction
from aiops_k8s_agents.validator import (
    CommandValidationError,
    CommandValidator,
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
