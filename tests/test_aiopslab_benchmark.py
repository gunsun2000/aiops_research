import json
from pathlib import Path
from threading import Event

import pytest

from aiops_k8s_agents.aiopslab_benchmark import (
    AIOpsLabBenchmarkCatalog,
    AIOpsLabBenchmarkExecutor,
    resolve_aiopslab_python,
    sanitize_benchmark_output,
)
from aiops_k8s_agents.aiopslab_jobs import AIOpsLabBenchmarkRequest


def _write_catalog(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {
                        "id": "hotel-reservation-detection-v1",
                        "title": "Hotel Reservation Detection",
                        "problem_id": "misconfig_app_hotel_res-detection-1",
                        "namespace": "test-hotel-reservation",
                        "service": "geo",
                        "metrics_duration_minutes": 10,
                        "max_steps": 8,
                        "timeout_seconds": 1800,
                        "max_repetitions": 12,
                        "subtitle": "호텔 예약 시스템",
                        "tag": "AIOpsLab",
                        "description": "호텔 예약 마이크로서비스 환경의 이상 탐지 성능을 평가합니다.",
                        "dataset_label": "AIOpsLab Dataset",
                        "icon": "▦",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _executor_fixture(tmp_path):
    catalog_path = tmp_path / "benchmarks.json"
    _write_catalog(catalog_path)
    spec = AIOpsLabBenchmarkCatalog.from_path(catalog_path).resolve(
        "hotel-reservation-detection-v1"
    )
    repo_root = tmp_path / "project"
    aiopslab_root = tmp_path / "external" / "AIOpsLab"
    kubeconfig = tmp_path / "kubeconfig.yaml"
    python = tmp_path / "python.exe"
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "scripts" / "server_aiopslab_auto_detection.py").write_text(
        "# runner", encoding="utf-8"
    )
    aiopslab_root.mkdir(parents=True)
    kubeconfig.write_text("apiVersion: v1", encoding="utf-8")
    python.write_text("binary", encoding="utf-8")
    executor = AIOpsLabBenchmarkExecutor(
        repo_root=repo_root,
        aiopslab_root=aiopslab_root,
        python_executable=python,
        kubeconfig=kubeconfig,
    )
    return executor, spec


def test_catalog_resolves_only_registered_benchmark_ids(tmp_path):
    path = tmp_path / "benchmarks.json"
    _write_catalog(path)
    catalog = AIOpsLabBenchmarkCatalog.from_path(path)

    spec = catalog.resolve("hotel-reservation-detection-v1")

    assert spec.problem_id == "misconfig_app_hotel_res-detection-1"
    assert spec.namespace == "test-hotel-reservation"
    assert catalog.to_public_list()[0]["id"] == spec.benchmark_id
    with pytest.raises(KeyError, match="not registered"):
        catalog.resolve("unknown-benchmark")


def test_catalog_exposes_hotel_reservation_ui_metadata_without_metrics(tmp_path):
    path = tmp_path / "benchmarks.json"
    _write_catalog(path)

    public = AIOpsLabBenchmarkCatalog.from_path(path).to_public_list()[0]

    assert public["subtitle"] == "호텔 예약 시스템"
    assert public["tag"] == "AIOpsLab"
    assert public["description"] == "호텔 예약 마이크로서비스 환경의 이상 탐지 성능을 평가합니다."
    assert public["dataset_label"] == "AIOpsLab Dataset"
    assert public["icon"] == "▦"
    for fabricated_metric in ("f1_score", "precision", "recall", "auc", "ui_metrics", "recent_result"):
        assert fabricated_metric not in public


def test_executor_builds_bounded_argv_from_server_owned_paths(tmp_path):
    executor, spec = _executor_fixture(tmp_path)

    command = executor.build_command(
        spec,
        output_dir=tmp_path / "artifacts" / "repeat-01",
    )

    assert isinstance(command, list)
    assert command[0] == str(executor.python_executable)
    assert "--problem-id" in command
    assert command[command.index("--problem-id") + 1] == spec.problem_id
    assert command[command.index("--aiopslab-root") + 1] == str(
        executor.aiopslab_root
    )
    assert command[command.index("--kubeconfig") + 1] == str(executor.kubeconfig)
    assert executor.readiness()["ready"] is True


def test_executor_rejects_missing_runtime_before_subprocess(tmp_path):
    executor = AIOpsLabBenchmarkExecutor(
        repo_root=tmp_path / "missing-project",
        aiopslab_root=tmp_path / "missing-aiopslab",
        python_executable=tmp_path / "missing-python",
        kubeconfig=tmp_path / "missing-kubeconfig",
    )

    readiness = executor.readiness()

    assert readiness["ready"] is False
    assert "AIOpsLab root" in " ".join(readiness["reasons"])


def test_resolve_aiopslab_python_prefers_explicit_environment_path(tmp_path):
    explicit = tmp_path / "explicit-python"
    explicit.write_text("python", encoding="utf-8")

    resolved = resolve_aiopslab_python(
        env={"AIOPSLAB_PYTHON": str(explicit)},
        home=tmp_path / "home",
        current_python=tmp_path / "current-python",
    )

    assert resolved == explicit.resolve()


def test_resolve_aiopslab_python_discovers_conda_environment_when_unset(tmp_path):
    discovered = tmp_path / "home" / "anaconda3" / "envs" / "aiopslab" / "bin" / "python"
    discovered.parent.mkdir(parents=True)
    discovered.write_text("python", encoding="utf-8")

    resolved = resolve_aiopslab_python(
        env={},
        home=tmp_path / "home",
        current_python=tmp_path / "current-python",
    )

    assert resolved == discovered.resolve()


def test_executor_rejects_repetition_above_registered_limit(tmp_path):
    path = tmp_path / "benchmarks.json"
    _write_catalog(path)
    spec = AIOpsLabBenchmarkCatalog.from_path(path).resolve(
        "hotel-reservation-detection-v1"
    )

    with pytest.raises(ValueError, match="maximum repetitions"):
        spec.validate_request(
            AIOpsLabBenchmarkRequest(spec.benchmark_id, repetitions=12),
            repetitions_override=13,
        )


def test_executor_attaches_evaluator_result_to_generated_report(tmp_path, monkeypatch):
    executor, spec = _executor_fixture(tmp_path)
    output_dir = tmp_path / "reports"

    class _FakeProcess:
        returncode = 0

        def __init__(self, *args, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "run_aiopslab_auto_detection.json").write_text(
                json.dumps(
                    {
                        "problem_id": spec.problem_id,
                        "namespace": spec.namespace,
                        "service": spec.service,
                        "decisions": [
                            {
                                "api_call": 'get_logs("test-hotel-reservation", "geo")',
                                "valid": True,
                                "metadata": {"referee": "approved", "reward_total": "1.55"},
                            },
                            {
                                "api_call": 'get_metrics("test-hotel-reservation", 10)',
                                "valid": True,
                                "metadata": {"referee": "approved", "reward_total": "3.10"},
                            },
                            {
                                "api_call": 'submit("Yes")',
                                "valid": True,
                                "metadata": {"referee": "approved", "reward_total": "3.10"},
                            },
                        ],
                        "aiopslab_results": {
                            "results": {
                                "Detection Accuracy": "Correct",
                                "TTD": 3.0,
                                "steps": 3,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return "completed", ""

        def terminate(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr("aiops_k8s_agents.aiopslab_benchmark.subprocess.Popen", _FakeProcess)

    execution = executor.execute(
        spec,
        job_id="lab-evaluator",
        repetition=1,
        output_dir=output_dir,
        cancellation=Event(),
    )

    report = json.loads(execution.report_path.read_text(encoding="utf-8"))
    assert report["evaluation"]["evaluator"] == "AIOpsLabEvaluatorAgent"
    assert report["evaluation"]["team_reward"] > 0.0
    assert set(report["evaluation"]["agent_rewards"]) == {
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
    assert all(
        "reward_total" not in decision["metadata"]
        for decision in report["decisions"]
    )


def test_sanitize_benchmark_output_redacts_credentials_and_paths():
    text = (
        "OPENAI_API_KEY=sk-secret-value "
        "C:\\Users\\researcher\\private\\kubeconfig.yaml"
    )

    sanitized = sanitize_benchmark_output(text)

    assert "sk-secret-value" not in sanitized
    assert "researcher" not in sanitized
    assert "[REDACTED]" in sanitized
