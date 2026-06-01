import json

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
