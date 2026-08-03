from __future__ import annotations

from pathlib import Path

import pytest

from aiops_k8s_agents.chaos_adapter import ChaosMeshAdapter


def test_chaos_adapter_applies_waits_and_deletes_registered_manifest(tmp_path):
    manifest = tmp_path / "cpu.yaml"
    manifest.write_text("kind: StressChaos\n", encoding="utf-8")
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
        manifest_root=tmp_path,
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
        manifest_root=tmp_path / "k8s",
    )

    result = adapter.preflight()

    assert result.valid is False
    assert "under" in result.stderr


def test_chaos_adapter_reports_missing_manifest_during_preflight(tmp_path):
    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": tmp_path / "missing.yaml"},
        runner=lambda _argv: (0, "stresschaos", ""),
        manifest_root=tmp_path,
    )

    result = adapter.preflight()

    assert result.valid is False
    assert "does not exist" in result.stderr


def test_chaos_adapter_cleanup_is_idempotent_and_keeps_delete_failure_visible(tmp_path):
    manifest = tmp_path / "cpu.yaml"
    manifest.write_text("kind: StressChaos\n", encoding="utf-8")
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
        manifest_root=tmp_path,
    )
    application = adapter.inject("cpu-stress")

    first = adapter.cleanup(application)
    second = adapter.cleanup(application)

    assert first.valid is False
    assert second.valid is False
    assert first.cleanup_required is True
    assert len(delete_calls) == 2
    assert all(call[-1] == "--ignore-not-found" for call in delete_calls)
