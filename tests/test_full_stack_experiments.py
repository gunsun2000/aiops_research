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

    network_delay = scenarios["network-delay"]
    assert network_delay.metric == "latency"
    assert network_delay.query == "max(up)"


def test_full_stack_feedback_loop_script_keeps_promql_out_of_parameter_expansion():
    script = Path("scripts/server_full_stack_feedback_loop.sh").read_text(
        encoding="utf-8"
    )

    assert 'QUERY="${QUERY:-' not in script
    assert 'image!=""}[2m]' in script
    assert "max(kube_deployment_status_replicas_available" in script
    assert "kube_pod_container_status_restarts_total" in script
    assert 'set_default QUERY "max(up)"' in script
    assert 'set_default QUERY "up"' not in script
    assert "wait_for_prometheus" in script


def test_full_stack_matrix_continues_to_cleanup_after_scenario_failure():
    script = Path("scripts/server_full_stack_experiment_matrix.sh").read_text(
        encoding="utf-8"
    )

    assert "matrix_failed=0" in script
    assert "if !" in script
    assert "ACTION=delete SCENARIO=\"$scenario\"" in script
    assert "failed_scenarios" in script


def test_full_stack_matrix_resets_each_scenario_before_and_after_execution():
    script = Path("scripts/server_full_stack_experiment_matrix.sh").read_text(
        encoding="utf-8"
    )

    assert 'SCENARIO="$scenario" bash scripts/server_full_stack_reset.sh' in script
    assert script.count("server_full_stack_reset.sh") >= 2


def test_final_real_script_requires_confirmation_and_private_kind_context():
    script = Path("scripts/server_finalize_research.sh").read_text(
        encoding="utf-8"
    )

    assert 'CONFIRM_REAL_RUN:-' in script
    assert 'CONFIRM_REAL_RUN=YES' in script
    assert "ALLOW_NON_KIND_REAL" in script
    assert 'MODE=real' in script
    assert "summarize-full-stack-runs" in script


def test_final_real_script_keeps_summary_generation_after_scenario_failures():
    script = Path("scripts/server_finalize_research.sh").read_text(
        encoding="utf-8"
    )

    assert 'ALLOW_SCENARIO_FAILURES="${ALLOW_SCENARIO_FAILURES:-1}"' in script
    assert "matrix_status=$?" in script
    assert "find \"$RUN_DIR\" -name '*feedback_loop_report.json'" in script
    assert "Final experiment matrix reported scenario failures" in script


def test_progress_wrapper_exists_for_long_running_commands():
    script = Path("scripts/run_with_progress.sh").read_text(encoding="utf-8")

    assert "--label" in script
    assert "still working" in script
    assert "elapsed" in script
    assert "wait \"$child_pid\"" in script


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
