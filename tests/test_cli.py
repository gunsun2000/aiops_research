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
