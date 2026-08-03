import json
from pathlib import Path

import pytest

from aiops_k8s_agents.aiopslab_benchmark import (
    AIOpsLabBenchmarkCatalog,
    AIOpsLabBenchmarkExecutor,
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
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


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


def test_executor_builds_bounded_argv_from_server_owned_paths(tmp_path):
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

    command = executor.build_command(
        spec,
        output_dir=tmp_path / "artifacts" / "repeat-01",
    )

    assert isinstance(command, list)
    assert command[0] == str(python.resolve())
    assert "--problem-id" in command
    assert command[command.index("--problem-id") + 1] == spec.problem_id
    assert command[command.index("--aiopslab-root") + 1] == str(
        aiopslab_root.resolve()
    )
    assert command[command.index("--kubeconfig") + 1] == str(kubeconfig.resolve())
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


def test_sanitize_benchmark_output_redacts_credentials_and_paths():
    text = (
        "OPENAI_API_KEY=sk-secret-value "
        "C:\\Users\\researcher\\private\\kubeconfig.yaml"
    )

    sanitized = sanitize_benchmark_output(text)

    assert "sk-secret-value" not in sanitized
    assert "researcher" not in sanitized
    assert "[REDACTED]" in sanitized

