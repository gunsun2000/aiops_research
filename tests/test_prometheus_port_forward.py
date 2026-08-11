from __future__ import annotations

from dataclasses import dataclass

from aiops_k8s_agents.prometheus_port_forward import PrometheusPortForwardManager


@dataclass
class FakeProcess:
    pid: int = 4321
    returncode: int | None = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_manager_reuses_an_already_ready_prometheus_endpoint(monkeypatch):
    monkeypatch.setenv("AIOPS_AUTO_PORT_FORWARD", "true")
    calls: list[list[str]] = []
    manager = PrometheusPortForwardManager(
        "http://127.0.0.1:9091",
        probe=lambda: True,
        popen=lambda command: calls.append(command),
    )

    manager.start()

    assert calls == []
    assert manager.status()["ready"] is True
    assert manager.status()["managed"] is False


def test_manager_starts_port_forward_and_reports_managed_endpoint(monkeypatch):
    monkeypatch.setenv("AIOPS_AUTO_PORT_FORWARD", "true")
    process = FakeProcess()
    calls: list[list[str]] = []
    manager = PrometheusPortForwardManager(
        "http://127.0.0.1:9091",
        namespace="monitoring-full",
        service="service/kube-prometheus-stack-prometheus",
        probe=lambda: True,
        popen=lambda command: (calls.append(command) or process),
        existing_ready=False,
    )

    manager.start()

    assert calls == [[
        "kubectl",
        "port-forward",
        "--namespace",
        "monitoring-full",
        "service/kube-prometheus-stack-prometheus",
        "9091:9090",
    ]]
    assert manager.status()["ready"] is True
    assert manager.status()["managed"] is True
    manager.stop()
    assert process.returncode == 0


def test_manager_does_not_manage_non_local_prometheus_endpoint(monkeypatch):
    monkeypatch.setenv("AIOPS_AUTO_PORT_FORWARD", "true")
    calls: list[list[str]] = []
    manager = PrometheusPortForwardManager(
        "http://prometheus.monitoring.svc:9090",
        probe=lambda: False,
        popen=lambda command: calls.append(command),
    )

    manager.start()

    assert calls == []
    assert manager.status()["state"] == "external"
