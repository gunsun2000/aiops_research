from pathlib import Path

from aiops_k8s_agents.agent_decision_policy import default_agent_decision_policy


def test_default_agent_decision_policy_does_not_depend_on_current_working_directory(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    policy = default_agent_decision_policy()

    assert policy.version
    assert policy.metric_policies
