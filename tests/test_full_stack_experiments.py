from pathlib import Path

from aiops_k8s_agents.full_stack_experiments import (
    load_full_stack_experiment_plan,
)


def test_full_stack_experiment_plan_loads_fixed_environment_and_variables():
    plan = load_full_stack_experiment_plan(
        Path("config/full_stack_experiments.json")
    )

    assert plan.environment.name == "full-stack"
    assert "kube-prometheus-stack" in plan.environment.components
    assert "online-boutique-full" in plan.environment.components
    assert "chaos-mesh" in plan.environment.components
    assert {scenario.id for scenario in plan.scenarios} == {
        "cpu-stress",
        "memory-stress",
        "pod-kill",
        "network-delay",
    }
    assert {variation.variable for variation in plan.variations} == {
        "fault_type",
        "agent_policy",
        "llm_model",
        "reward_policy",
        "baseline",
    }


def test_full_stack_experiment_plan_rejects_duplicate_scenario_ids(tmp_path):
    config = tmp_path / "duplicate.json"
    config.write_text(
        """
{
  "environment": {
    "name": "full-stack",
    "components": ["kube-prometheus-stack"]
  },
  "scenarios": [
    {
      "id": "cpu-stress",
      "fault": "cpu-stress",
      "metric": "cpu",
      "query": "up",
      "threshold": 0.5,
      "service": "paymentservice",
      "chaos_manifest": "k8s/chaos/paymentservice-cpu-stress.yaml"
    },
    {
      "id": "cpu-stress",
      "fault": "cpu-stress",
      "metric": "cpu",
      "query": "up",
      "threshold": 0.5,
      "service": "paymentservice",
      "chaos_manifest": "k8s/chaos/paymentservice-cpu-stress.yaml"
    }
  ],
  "variations": []
}
""",
        encoding="utf-8",
    )

    try:
        load_full_stack_experiment_plan(config)
    except ValueError as exc:
        assert "duplicate scenario id" in str(exc)
    else:
        raise AssertionError("duplicate scenario id must be rejected")
