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


def test_full_stack_queries_are_safe_for_feedback_loop_defaults():
    plan = load_full_stack_experiment_plan(
        Path("config/full_stack_experiments.json")
    )
    scenarios = {scenario.id: scenario for scenario in plan.scenarios}

    cpu_query = scenarios["cpu-stress"].query
    assert 'image!=""}[2m]' in cpu_query
    assert 'image!=""[2m]' not in cpu_query

    pod_kill_query = scenarios["pod-kill"].query
    assert pod_kill_query.startswith("max(")
    assert "kube_deployment_status_replicas_available" in pod_kill_query
    assert 'deployment="paymentservice"' in pod_kill_query

    memory_stress = scenarios["memory-stress"]
    assert memory_stress.metric == "restart_count"
    assert memory_stress.threshold == 0.5
    assert "kube_pod_container_status_restarts_total" in memory_stress.query
    assert 'pod=~"checkoutservice-.*"' in memory_stress.query


def test_full_stack_feedback_loop_script_keeps_promql_out_of_parameter_expansion():
    script = Path("scripts/server_full_stack_feedback_loop.sh").read_text(
        encoding="utf-8"
    )

    assert 'QUERY="${QUERY:-' not in script
    assert 'image!=""}[2m]' in script
    assert "max(kube_deployment_status_replicas_available" in script
    assert "kube_pod_container_status_restarts_total" in script
    assert "wait_for_prometheus" in script


def test_full_stack_matrix_continues_to_cleanup_after_scenario_failure():
    script = Path("scripts/server_full_stack_experiment_matrix.sh").read_text(
        encoding="utf-8"
    )

    assert "matrix_failed=0" in script
    assert "if !" in script
    assert "ACTION=delete SCENARIO=\"$scenario\"" in script
    assert "failed_scenarios" in script


def test_full_stack_setup_script_has_reset_and_rollout_diagnostics():
    script = Path("scripts/server_full_stack_setup.sh").read_text(
        encoding="utf-8"
    )

    assert "RESET_ONLINE_BOUTIQUE" in script
    assert "ALLOW_PARTIAL_ROLLOUT" in script
    assert "kubectl describe deployment" in script
    assert "kubectl logs" in script


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
