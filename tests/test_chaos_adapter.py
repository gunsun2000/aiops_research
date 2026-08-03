from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from aiops_k8s_agents.chaos_adapter import ChaosMeshAdapter
from aiops_k8s_agents.real_evidence import load_runtime_configuration


def _manifest(tmp_path, name="cpu.yaml"):
    path = tmp_path / "k8s" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("kind: StressChaos\n", encoding="utf-8")
    return path


def test_chaos_adapter_applies_waits_and_deletes_registered_manifest(tmp_path):
    manifest = _manifest(tmp_path)
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["kubectl", "api-resources"]:
            return 0, "stresschaos networkchaos", ""
        return 0, "ok", ""

    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest},
        runner=runner,
        sleeper=lambda _seconds: None,
        repository_root=tmp_path,
    )
    assert adapter.preflight().valid is True
    application = adapter.inject("cpu-stress")
    cleanup = adapter.cleanup(application)

    assert application.valid is True
    assert application.cleanup_required is True
    assert cleanup.valid is True
    assert ["kubectl", "apply", "-f", str(manifest)] in calls
    assert ["kubectl", "wait", "--for=condition=AllInjected", "-f", str(manifest), "--timeout=60s"] in calls
    assert ["kubectl", "delete", "-f", str(manifest), "--ignore-not-found"] in calls


def test_chaos_adapter_rejects_unknown_scenario():
    adapter = ChaosMeshAdapter(scenarios={}, runner=lambda _argv: (0, "", ""))

    with pytest.raises(ValueError, match="unknown chaos scenario"):
        adapter.inject("disk-corruption")


def test_chaos_adapter_rejects_manifest_outside_k8s_root(tmp_path):
    manifest = tmp_path / "outside.yaml"
    manifest.write_text("kind: StressChaos\n", encoding="utf-8")
    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest},
        runner=lambda _argv: (0, "stresschaos", ""),
        repository_root=tmp_path,
    )

    result = adapter.preflight()

    assert result.valid is False
    assert "under" in result.stderr


def test_chaos_adapter_reports_missing_manifest_during_preflight(tmp_path):
    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": tmp_path / "k8s" / "missing.yaml"},
        runner=lambda _argv: (0, "stresschaos", ""),
        repository_root=tmp_path,
    )

    result = adapter.preflight()

    assert result.valid is False
    assert "does not exist" in result.stderr


def test_chaos_adapter_cleanup_is_idempotent_and_keeps_delete_failure_visible(tmp_path):
    manifest = _manifest(tmp_path)
    delete_calls = []

    def runner(argv):
        if argv[1] == "delete":
            delete_calls.append(argv)
            return 1, "", "delete failed"
        if argv[1] == "api-resources":
            return 0, "stresschaos", ""
        return 0, "ok", ""

    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest},
        runner=runner,
        repository_root=tmp_path,
    )
    application = adapter.inject("cpu-stress")

    first = adapter.cleanup(application)
    second = adapter.cleanup(application)

    assert first.valid is False
    assert second.valid is False
    assert first.cleanup_required is True
    assert len(delete_calls) == 2
    assert all(call[-1] == "--ignore-not-found" for call in delete_calls)


def test_chaos_adapter_rejects_manifest_under_arbitrary_supplied_root(tmp_path):
    manifest = tmp_path / "custom-root" / "k8s" / "cpu.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("kind: StressChaos\n", encoding="utf-8")

    result = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest},
        runner=lambda _argv: (0, "stresschaos", ""),
        repository_root=tmp_path,
    ).preflight()

    assert result.valid is False
    assert "under" in result.stderr


def test_chaos_adapter_default_registered_manifests_pass_local_preflight(tmp_path):
    configuration = load_runtime_configuration("config/experiment_runtime.json")
    adapter = ChaosMeshAdapter(
        scenarios=configuration.scenarios,
        runner=lambda argv: (0, "podchaos stresschaos networkchaos", "")
        if argv[:2] == ["kubectl", "api-resources"]
        else (0, "ok", ""),
    )

    result = adapter.preflight()

    assert result.valid is True


def test_chaos_adapter_returns_cleanup_required_after_wait_timeout(tmp_path):
    manifest = _manifest(tmp_path)
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[1] == "wait":
            raise subprocess.TimeoutExpired(argv, 60)
        return 0, "apply-out", "apply-err"

    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest}, runner=runner, repository_root=tmp_path
    )
    application = adapter.inject("cpu-stress")

    assert application.valid is False
    assert application.cleanup_required is True
    assert "timed out" in application.stderr
    assert calls[0][:2] == ["kubectl", "apply"]
    assert calls[1][:2] == ["kubectl", "wait"]


def test_chaos_adapter_preserves_apply_failure_output_and_cleanup_requirement(tmp_path):
    manifest = _manifest(tmp_path)

    def runner(argv):
        if argv[1] == "apply":
            return 1, "apply-out", "apply-err"
        raise AssertionError("wait must not run after apply failure")

    application = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest}, runner=runner, repository_root=tmp_path
    ).inject("cpu-stress")

    assert application.valid is False
    assert application.cleanup_required is True
    assert application.stdout == "apply-out"
    assert application.stderr == "apply-err"


def test_chaos_adapter_converts_runner_exception_to_cleanup_required_application(tmp_path):
    manifest = _manifest(tmp_path)

    def runner(argv):
        if argv[1] == "wait":
            raise OSError("kubeconfig unavailable")
        return 0, "ok", ""

    application = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest}, runner=runner, repository_root=tmp_path
    ).inject("cpu-stress")

    assert application.valid is False
    assert application.cleanup_required is True
    assert "kubeconfig unavailable" in application.stderr


def test_chaos_adapter_reports_delete_timeout_and_retains_cleanup_requirement(tmp_path):
    manifest = _manifest(tmp_path)

    def runner(argv):
        if argv[1] == "delete":
            raise subprocess.TimeoutExpired(argv, 15)
        return 0, "ok", ""

    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest}, runner=runner, repository_root=tmp_path
    )
    application = adapter.inject("cpu-stress")
    cleanup = adapter.cleanup(application)

    assert cleanup.valid is False
    assert cleanup.cleanup_required is True
    assert "timed out" in cleanup.stderr


def test_chaos_adapter_repeated_successful_delete_remains_ignore_not_found(tmp_path):
    manifest = _manifest(tmp_path)
    deletes = []

    def runner(argv):
        if argv[1] == "delete":
            deletes.append(argv)
            return 0, "deleted", ""
        return 0, "ok", ""

    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest}, runner=runner, repository_root=tmp_path
    )
    application = adapter.inject("cpu-stress")

    first = adapter.cleanup(application)
    second = adapter.cleanup(application)

    assert first.valid is True
    assert second.valid is True
    assert len(deletes) == 2
    assert all(delete[-1] == "--ignore-not-found" for delete in deletes)
