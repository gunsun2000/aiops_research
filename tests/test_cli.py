import json
from pathlib import Path

from aiops_k8s_agents.models import CommandResult
import aiops_k8s_agents.cli as cli
from aiops_k8s_agents.cli import main


def test_cli_mock_run_prints_command_json(capsys):
    exit_code = main(
        [
            "run",
            "--mode",
            "mock",
            "--namespace",
            "online-boutique",
            "--service",
            "paymentservice",
            "--metric",
            "cpu",
            "--value",
            "95",
            "--threshold",
            "80",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["command"] == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )
    assert output["metadata"]["coordinator"] == "AI-MCMP"


def test_cli_can_save_result_json_to_directory(tmp_path, capsys):
    exit_code = main(
        [
            "run",
            "--mode",
            "mock",
            "--namespace",
            "online-boutique",
            "--service",
            "paymentservice",
            "--metric",
            "cpu",
            "--value",
            "95",
            "--threshold",
            "80",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
            "--save-result-dir",
            str(tmp_path),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    saved_files = list(tmp_path.glob("*.json"))
    saved = json.loads(saved_files[0].read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(saved_files) == 1
    assert saved == output
    assert saved_files[0].name.endswith("_run_mock.json")


def test_cli_autogen_run_prints_groupchat_result(monkeypatch, capsys):
    async def fake_autogen_run(_args):
        return CommandResult(
            command="kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
            mode="mock",
            valid=True,
            stdout="mock: 명령어를 검증했으며 실제 실행하지 않았습니다",
            stderr="",
            metadata={
                "coordinator": "AI-MCMP",
                "autogen": "groupchat",
                "consensus": "approved",
                "reward_total": "3.05",
            },
        )

    monkeypatch.setattr(cli, "run_autogen_groupchat", fake_autogen_run)

    exit_code = main(
        [
            "autogen-run",
            "--mode",
            "mock",
            "--model",
            "gpt-4o-mini",
            "--namespace",
            "online-boutique",
            "--service",
            "paymentservice",
            "--metric",
            "cpu",
            "--value",
            "95",
            "--threshold",
            "80",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["metadata"]["autogen"] == "groupchat"
    assert output["metadata"]["reward_total"] == "3.05"


def test_cli_autogen_run_defaults_to_current_openai_model(monkeypatch, capsys):
    async def fake_autogen_run(args):
        assert args.model == "gpt-5.5"
        return CommandResult(
            command="kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
            mode="mock",
            valid=True,
            stdout="mock",
            stderr="",
            metadata={"autogen": "groupchat"},
        )

    monkeypatch.setattr(cli, "run_autogen_groupchat", fake_autogen_run)

    exit_code = main(
        [
            "autogen-run",
            "--mode",
            "mock",
            "--namespace",
            "online-boutique",
            "--service",
            "paymentservice",
            "--metric",
            "cpu",
            "--value",
            "95",
            "--threshold",
            "80",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True


def test_cli_autogen_run_can_show_agent_transcript(monkeypatch, capsys):
    from aiops_k8s_agents.autogen_groupchat import parse_autogen_decision

    class FakeProvider:
        transcript_lines = [
            "AIServiceHASupportAgent: action=ha_scale_out_required approved=True reward=0.90 reason=HA 복구 필요",
            "AIApplicationManagementAgent: action=app_scale_deployment approved=True reward=0.85 reason=replica 3개 확장",
            "AISemiconductorInfraOpsAgent: action=infra_capacity_approved approved=True reward=0.70 reason=자원 가능",
            "CostOptimizationAgent: action=cost_budget_approved approved=True reward=0.60 reason=비용 가능",
        ]

        def __init__(self, model_client):
            self.model_client = model_client

        async def __call__(self, _alert):
            return [
                parse_autogen_decision(
                    {
                        "agent": "AIServiceHASupportAgent",
                        "action": "ha_scale_out_required",
                        "reward": 0.90,
                        "approved": True,
                        "reason": "HA 복구 필요",
                    },
                    expected_agent="AIServiceHASupportAgent",
                ),
                parse_autogen_decision(
                    {
                        "agent": "AIApplicationManagementAgent",
                        "action": "app_scale_deployment",
                        "reward": 0.85,
                        "approved": True,
                        "reason": "replica 3개 확장",
                        "parameters": {
                            "namespace": "online-boutique",
                            "deployment": "paymentservice",
                            "replicas": "3",
                        },
                    },
                    expected_agent="AIApplicationManagementAgent",
                ),
                parse_autogen_decision(
                    {
                        "agent": "AISemiconductorInfraOpsAgent",
                        "action": "infra_capacity_approved",
                        "reward": 0.70,
                        "approved": True,
                        "reason": "자원 가능",
                    },
                    expected_agent="AISemiconductorInfraOpsAgent",
                ),
                parse_autogen_decision(
                    {
                        "agent": "CostOptimizationAgent",
                        "action": "cost_budget_approved",
                        "reward": 0.60,
                        "approved": True,
                        "reason": "비용 가능",
                    },
                    expected_agent="CostOptimizationAgent",
                ),
            ]

    monkeypatch.setattr(cli, "create_openai_model_client", lambda _model: object())
    monkeypatch.setattr(cli, "AutoGenRoundRobinDecisionProvider", FakeProvider)

    exit_code = main(
        [
            "autogen-run",
            "--mode",
            "mock",
            "--show-transcript",
            "--namespace",
            "online-boutique",
            "--service",
            "paymentservice",
            "--metric",
            "cpu",
            "--value",
            "95",
            "--threshold",
            "80",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["metadata"]["transcript"] == "\n".join(FakeProvider.transcript_lines)


def test_cli_executes_structured_recovery_action_in_mock_mode(capsys):
    exit_code = main(
        [
            "execute-recovery-action",
            "--mode",
            "mock",
            "--action",
            "rollout_restart",
            "--namespace",
            "online-boutique",
            "--deployment",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["command"] == (
        "kubectl rollout restart deployment paymentservice -n online-boutique"
    )


def test_cli_lists_registered_agents(capsys):
    exit_code = main(["list-agents", "--registry", "config/agent_registry.json"])

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["command"] == "list-agents"
    assert "AIApplicationManagementAgent" in [
        agent["name"] for agent in output["agents"]
    ]


def test_cli_validates_registered_agent_action(capsys):
    exit_code = main(
        [
            "validate-agent-action",
            "--registry",
            "config/agent_registry.json",
            "--agent",
            "AIApplicationManagementAgent",
            "--action",
            "app_scale_deployment",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["agent"] == "AIApplicationManagementAgent"


def test_cli_recommends_inference_placement(capsys):
    exit_code = main(
        [
            "recommend-inference-placement",
            "--config",
            "config/inference_optimization.json",
            "--workload",
            "llm-chat-inference",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["selected_resource"] == "gpu-vm-l4"
    assert output["action"] == "deploy_on_gpu_vm"


def test_cli_builds_inference_deployment_plan(capsys):
    exit_code = main(
        [
            "plan-inference-deployment",
            "--config",
            "config/inference_optimization.json",
            "--workload",
            "llm-chat-inference",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["selected_resource"] == "gpu-vm-l4"
    assert output["deployment_plan"]["kubernetes"]["namespace"] == "ai-inference"
    assert output["deployment_plan"]["kubernetes"]["resources"]["limits"][
        "nvidia.com/gpu"
    ] == "1"


def test_cli_selects_ops_llm_under_quality_policy(capsys):
    exit_code = main(
        [
            "select-ops-llm",
            "--config",
            "config/ops_llm_benchmark.json",
            "--policy",
            "quality_first",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["selected_model"] == "gpt-5.5"
    assert output["ranking"][0]["model"] == "gpt-5.5"


def test_cli_runs_service_operations_pipeline_in_mock_mode(capsys):
    exit_code = main(
        [
            "run-service-operations",
            "--mode",
            "mock",
            "--guard-backend",
            "go",
            "--llm-policy",
            "quality_first",
            "--workload",
            "llm-chat-inference",
            "--namespace",
            "online-boutique",
            "--deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["command"] == "run-service-operations"
    assert output["selected_llm"] == "gpt-5.5"
    assert output["selected_resource"] == "gpu-vm-l4"
    assert output["deployment_manifest"]["kind"] == "Deployment"
    assert output["deployment_dry_run"]["valid"] is True
    assert output["recovery_pipeline_ready"] is True
    assert output["guard_backend"] == "go"


def test_cli_lists_ops_llm_candidates(capsys):
    exit_code = main(
        [
            "list-ops-llm-candidates",
            "--config",
            "config/ops_llm_benchmark.json",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["command"] == "list-ops-llm-candidates"
    assert "gpt-5.5" in [candidate["model"] for candidate in output["candidates"]]


def test_cli_passes_go_guard_backend_to_recovery_executor(monkeypatch, capsys):
    captured = {}

    class FakeExecutor:
        def __init__(self, validator, mode, backend):
            captured["mode"] = mode.value
            captured["backend"] = backend.value

        def execute_recovery(self, action):
            return CommandResult(
                command="kubectl rollout restart deployment paymentservice -n online-boutique --dry-run=server",
                mode=captured["mode"],
                valid=True,
                stdout="deployment.apps/paymentservice restarted (server dry run)",
                stderr="",
                metadata={"guard_backend": captured["backend"]},
            )

    monkeypatch.setattr(cli, "KubernetesExecutor", FakeExecutor)

    exit_code = main(
        [
            "execute-recovery-action",
            "--mode",
            "dry-run",
            "--guard-backend",
            "go",
            "--action",
            "rollout_restart",
            "--namespace",
            "online-boutique",
            "--deployment",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["metadata"]["guard_backend"] == "go"
    assert captured == {"mode": "dry-run", "backend": "go"}


def test_cli_scores_recovery_outcomes_under_all_reward_policies(tmp_path, capsys):
    input_path = tmp_path / "outcomes.jsonl"
    records = [
        {
            "scenario": "cpu-stress",
            "action": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "kind": "scale_out",
                "replicas": 3,
                "reason": "pilot",
            },
            "recovery_success": True,
            "availability_recovery": 1.0,
            "metric_improvement": 0.95,
            "recovery_seconds": 10.0,
            "replica_delta": 2,
            "command_count": 1,
            "safety_valid": True,
            "measurement_valid": True,
        },
        {
            "scenario": "cpu-stress",
            "action": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "kind": "observe_only",
                "replicas": None,
                "reason": "pilot",
            },
            "recovery_success": True,
            "availability_recovery": 0.8,
            "metric_improvement": 0.6,
            "recovery_seconds": 50.0,
            "replica_delta": 0,
            "command_count": 0,
            "safety_valid": True,
            "measurement_valid": True,
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "analysis"

    exit_code = main(
        [
            "score-recovery-experiments",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["policies"]["ha_first"]["cpu-stress"]["selected_action"] == "scale_out"
    assert output["policies"]["cost_first"]["cpu-stress"]["selected_action"] == "observe_only"
    assert (output_dir / "reward_policy_comparison.json").exists()
    assert (output_dir / "reward_policy_comparison.csv").exists()
    assert (output_dir / "reward_policy_comparison.md").exists()


def test_cli_summarizes_recovery_statistics(tmp_path, capsys):
    input_path = tmp_path / "outcomes.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "scenario": "pod-kill",
                        "action": {
                            "namespace": "online-boutique",
                            "deployment": "paymentservice",
                            "kind": "observe_only",
                            "replicas": None,
                            "reason": "test",
                        },
                        "recovery_success": True,
                        "availability_recovery": 1.0,
                        "metric_improvement": 1.0,
                        "recovery_seconds": 8.0,
                        "replica_delta": 0,
                        "command_count": 0,
                        "safety_valid": True,
                        "measurement_valid": True,
                    }
                ),
                json.dumps(
                    {
                        "scenario": "pod-kill",
                        "action": {
                            "namespace": "online-boutique",
                            "deployment": "paymentservice",
                            "kind": "scale_out",
                            "replicas": 3,
                            "reason": "test",
                        },
                        "recovery_success": True,
                        "availability_recovery": 1.0,
                        "metric_improvement": 0.7,
                        "recovery_seconds": 20.0,
                        "replica_delta": 2,
                        "command_count": 1,
                        "safety_valid": True,
                        "measurement_valid": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "statistics"

    exit_code = main(
        [
            "summarize-recovery-statistics",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["overall"]["success_rate"] == 1.0
    assert (output_dir / "quantitative_summary.md").exists()
    assert (output_dir / "mean_recovery_seconds_by_action.svg").exists()
    assert (output_dir / "mean_recovery_seconds_by_action.png").exists()


def test_cli_runs_real_recovery_experiment_matrix(monkeypatch, tmp_path, capsys):
    def fake_run_matrix(**kwargs):
        assert kwargs["repetitions"] == 1
        assert kwargs["mode"] == "real"
        assert kwargs["prometheus_url"] == "http://127.0.0.1:9090"
        assert Path(kwargs["output_path"]).name == "outcomes.jsonl"
        return {
            "command": "recovery-action-experiment",
            "mode": "real",
            "repetitions": 1,
            "total_treatments": 12,
            "valid_measurements": 12,
            "successful_recoveries": 10,
            "output": str(kwargs["output_path"]),
        }

    monkeypatch.setattr(cli, "run_recovery_matrix", fake_run_matrix)
    output_path = tmp_path / "outcomes.jsonl"

    exit_code = main(
        [
            "run-recovery-experiments",
            "--config",
            "config/recovery_action_experiments.json",
            "--mode",
            "real",
            "--repetitions",
            "1",
            "--prometheus-url",
            "http://127.0.0.1:9090",
            "--output",
            str(output_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["total_treatments"] == 12
    assert output["valid_measurements"] == 12


def test_cli_reports_recovery_matrix_preflight_error_as_json(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        cli,
        "run_recovery_matrix",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("NETWORK_LATENCY_QUERY is required")
        ),
    )

    exit_code = main(
        [
            "run-recovery-experiments",
            "--config",
            "config/recovery_action_experiments.json",
            "--mode",
            "real",
            "--repetitions",
            "1",
            "--output",
            str(tmp_path / "outcomes.jsonl"),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["valid"] is False
    assert output["stderr"] == "NETWORK_LATENCY_QUERY is required"


def test_cli_autogen_run_returns_json_error_when_model_client_fails(monkeypatch, capsys):
    def fail_model_client(_model):
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다")

    monkeypatch.setattr(cli, "create_openai_model_client", fail_model_client)

    exit_code = main(
        [
            "autogen-run",
            "--mode",
            "mock",
            "--model",
            "gpt-4o-mini",
            "--namespace",
            "online-boutique",
            "--service",
            "paymentservice",
            "--metric",
            "cpu",
            "--value",
            "95",
            "--threshold",
            "80",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["valid"] is False
    assert output["stderr"] == "OPENAI_API_KEY가 설정되지 않았습니다"
    assert output["metadata"]["autogen"] == "groupchat"


def test_cli_autogen_prometheus_run_prints_groupchat_prometheus_result(monkeypatch, capsys):
    async def fake_autogen_prometheus_run(_args):
        return CommandResult(
            command="kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
            mode="dry-run",
            valid=True,
            stdout="deployment.apps/paymentservice scaled (server dry run)",
            stderr="",
            metadata={
                "coordinator": "AI-MCMP",
                "autogen": "groupchat",
                "consensus": "approved",
                "input_source": "prometheus",
            },
        )

    monkeypatch.setattr(
        cli,
        "run_autogen_prometheus_alert",
        fake_autogen_prometheus_run,
    )

    exit_code = main(
        [
            "autogen-prometheus-run",
            "--mode",
            "dry-run",
            "--prometheus-url",
            "http://127.0.0.1:9090",
            "--query",
            "up",
            "--metric",
            "cpu",
            "--threshold",
            "0.5",
            "--default-namespace",
            "online-boutique",
            "--default-service",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["metadata"]["autogen"] == "groupchat"
    assert output["metadata"]["input_source"] == "prometheus"


def test_cli_feedback_loop_records_prometheus_results(monkeypatch, capsys):
    def fake_prometheus_run(_args):
        return CommandResult(
            command="kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
            mode="dry-run",
            valid=True,
            stdout="deployment.apps/paymentservice scaled (server dry run)",
            stderr="",
            metadata={
                "coordinator": "AI-MCMP",
                "consensus": "approved",
                "input_source": "prometheus",
            },
        )

    monkeypatch.setattr(cli, "run_prometheus_alert", fake_prometheus_run)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

    exit_code = main(
        [
            "feedback-loop",
            "--mode",
            "dry-run",
            "--prometheus-url",
            "http://127.0.0.1:9090",
            "--query",
            "up",
            "--metric",
            "cpu",
            "--threshold",
            "0.5",
            "--default-namespace",
            "online-boutique",
            "--default-service",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
            "--iterations",
            "2",
            "--interval-seconds",
            "0",
            "--no-kubernetes-snapshot",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["command"] == "feedback-loop"
    assert output["iterations"] == 2
    assert output["passed"] == 2
    assert output["failed"] == 0
    assert output["records"][0]["result"]["valid"] is True


def test_cli_feedback_loop_reports_failed_iterations(monkeypatch, capsys):
    def fake_prometheus_run(_args):
        return CommandResult(
            command="",
            mode="dry-run",
            valid=False,
            stdout="",
            stderr="bad metric",
            metadata={"input_source": "prometheus"},
        )

    monkeypatch.setattr(cli, "run_prometheus_alert", fake_prometheus_run)

    exit_code = main(
        [
            "feedback-loop",
            "--mode",
            "dry-run",
            "--prometheus-url",
            "http://127.0.0.1:9090",
            "--query",
            "up",
            "--metric",
            "cpu",
            "--threshold",
            "0.5",
            "--default-namespace",
            "online-boutique",
            "--default-service",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
            "--iterations",
            "1",
            "--no-kubernetes-snapshot",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["failed"] == 1
    assert output["records"][0]["result"]["stderr"] == "bad metric"


def test_cli_summarize_aiopslab_runs_writes_report_files(tmp_path, capsys):
    report_path = tmp_path / "20260608_aiopslab_auto_detection.json"
    report_path.write_text(
        json.dumps(
            {
                "problem_id": "misconfig_app_hotel_res-detection-1",
                "namespace": "test-hotel-reservation",
                "service": "geo",
                "decisions": [
                    {
                        "step": 3,
                        "api_call": 'submit("Yes")',
                        "metadata": {"reward_total": "3.10"},
                        "observation_excerpt": (
                            "Metrics data exported to directory: /tmp/metric"
                        ),
                    }
                ],
                "aiopslab_results": {
                    "final_state": "SubmissionStatus.VALID_SUBMISSION",
                    "results": {
                        "Detection Accuracy": "Correct",
                        "TTD": 3.684,
                        "steps": 3,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    output_md = tmp_path / "summary.md"
    output_csv = tmp_path / "summary.csv"
    exit_code = main(
        [
            "summarize-aiopslab-runs",
            "--runs-dir",
            str(tmp_path),
            "--output-md",
            str(output_md),
            "--output-csv",
            str(output_csv),
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["total_runs"] == 1
    assert output["correct_runs"] == 1
    assert output["metric_success_runs"] == 1
    assert Path(output["output_md"]).exists()
    assert output_csv.exists()


def test_cli_lists_full_stack_experiment_matrix(capsys):
    exit_code = main(
        [
            "list-full-stack-experiments",
            "--config",
            "config/full_stack_experiments.json",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["environment"]["name"] == "full-stack"
    assert {scenario["id"] for scenario in output["scenarios"]} == {
        "cpu-stress",
        "memory-stress",
        "pod-kill",
        "network-delay",
    }


def test_cli_summarizes_full_stack_runs(tmp_path, capsys):
    scenario_dir = tmp_path / "pod-kill"
    scenario_dir.mkdir()
    (scenario_dir / "run_feedback_loop_real.json").write_text(
        json.dumps(
            {
                "command": "feedback-loop",
                "mode": "real",
                "iterations": 1,
                "passed": 1,
                "failed": 0,
                "autogen": False,
                "records": [
                    {
                        "before": {"deployment_status": {"desired_replicas": 1}},
                        "result": {
                            "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
                            "mode": "real",
                            "valid": True,
                            "metadata": {"reward_total": "3.05"},
                        },
                        "after": {"deployment_status": {"desired_replicas": 3}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "summarize-full-stack-runs",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["total_scenarios"] == 1
    assert output["successful_scenarios"] == 1
    assert output["real_scale_verified_scenarios"] == 1
    assert (tmp_path / "final_summary.md").exists()
    assert (tmp_path / "final_summary.csv").exists()
