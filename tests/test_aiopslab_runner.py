import importlib.util
from pathlib import Path


def _load_runner_module():
    module_path = Path("scripts/server_aiopslab_auto_detection.py")
    spec = importlib.util.spec_from_file_location(
        "server_aiopslab_auto_detection", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_observe_wait_ignores_prometheus_node_exporter_port_conflict():
    runner = _load_runner_module()

    assert runner._is_required_observe_prometheus_pod(
        "prometheus-server-58bc5d6547-5n4s2"
    )
    assert runner._is_required_observe_prometheus_pod(
        "prometheus-kube-state-metrics-6c78fbbd9d-9kkng"
    )
    assert not runner._is_required_observe_prometheus_pod(
        "prometheus-prometheus-node-exporter-2pmcm"
    )
