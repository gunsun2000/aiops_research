"""Lifecycle management for the local Prometheus port-forward used by the UI."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import urlopen


Probe = Callable[[], bool]
PopenFactory = Callable[[Sequence[str]], object]


@dataclass(frozen=True)
class PortForwardConfiguration:
    url: str
    namespace: str = "monitoring-full"
    service: str = "service/kube-prometheus-stack-prometheus"
    remote_port: int = 9090


class PrometheusPortForwardManager:
    """Reuse or own a Prometheus port-forward for the control-plane lifetime.

    The manager never creates a second tunnel when the configured endpoint is
    already ready. Non-local Prometheus URLs are treated as externally managed.
    This keeps the existing ``PROMETHEUS_URL`` workflow compatible while making
    the Ubuntu server self-sufficient when a local Kubernetes context exists.
    """

    def __init__(
        self,
        url: str,
        *,
        namespace: str = "monitoring-full",
        service: str = "service/kube-prometheus-stack-prometheus",
        remote_port: int = 9090,
        probe: Probe | None = None,
        popen: PopenFactory | None = None,
        existing_ready: bool | None = None,
        startup_timeout: float = 15.0,
    ) -> None:
        self.configuration = PortForwardConfiguration(
            url=url.rstrip("/"),
            namespace=namespace,
            service=service,
            remote_port=remote_port,
        )
        parsed = urlparse(self.configuration.url)
        self._local_host = parsed.hostname or ""
        self._local_port = parsed.port or 9091
        self._probe = probe or self._http_probe
        self._popen = popen or self._default_popen
        self._custom_popen = popen is not None
        self._existing_ready = existing_ready
        self._startup_timeout = startup_timeout
        self._process: object | None = None
        self._state = "stopped"
        self._message = ""

    @classmethod
    def from_environment(cls, url: str) -> "PrometheusPortForwardManager":
        return cls(
            url,
            namespace=os.environ.get(
                "AIOPS_PROMETHEUS_NAMESPACE", "monitoring-full"
            ),
            service=os.environ.get(
                "AIOPS_PROMETHEUS_SERVICE",
                "service/kube-prometheus-stack-prometheus",
            ),
            remote_port=int(os.environ.get("AIOPS_PROMETHEUS_REMOTE_PORT", "9090")),
            startup_timeout=float(
                os.environ.get("AIOPS_PROMETHEUS_FORWARD_TIMEOUT", "15")
            ),
        )

    @property
    def enabled(self) -> bool:
        setting = os.environ.get("AIOPS_AUTO_PORT_FORWARD", "auto").lower()
        if self._local_host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        if setting in {"0", "false", "no", "off"}:
            return False
        if setting in {"1", "true", "yes", "on"}:
            return True
        if not self._custom_popen and shutil.which("kubectl") is None:
            return False
        kubeconfig = os.environ.get("KUBECONFIG")
        if kubeconfig:
            return os.path.exists(os.path.expanduser(kubeconfig))
        return os.path.exists(os.path.expanduser("~/.kube/config"))

    def start(self) -> None:
        if not self.enabled:
            self._state = "disabled" if self._local_host in {
                "127.0.0.1", "localhost", "::1"
            } else "external"
            self._message = "Automatic Prometheus port-forward is disabled."
            return

        if self._probe_existing():
            self._existing_ready = None
            self._state = "ready"
            self._message = "Using the existing Prometheus endpoint."
            return
        self._existing_ready = None

        if self._process_is_running():
            self._state = "starting"
            self._message = "Prometheus port-forward is starting."
            return

        if shutil.which("kubectl") is None:
            self._state = "unavailable"
            self._message = "kubectl was not found on PATH."
            return

        try:
            self._process = self._popen(self.command())
        except OSError as exc:
            self._state = "unavailable"
            self._message = f"Could not start kubectl port-forward: {exc}"
            return

        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            if self._probe_existing():
                self._state = "ready"
                self._message = "Prometheus port-forward is managed by the platform."
                return
            if not self._process_is_running():
                break
            time.sleep(0.25)

        self._state = "unavailable"
        self._message = "Prometheus did not become ready through kubectl port-forward."

    def ensure_running(self) -> None:
        if self._state in {"external", "disabled"}:
            return
        if self._probe_existing():
            self._state = "ready"
            return
        if not self._process_is_running():
            self.start()
        else:
            self._state = "starting"

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or not self._process_is_running(process):
            return
        terminate = getattr(process, "terminate", None)
        wait = getattr(process, "wait", None)
        kill = getattr(process, "kill", None)
        if callable(terminate):
            terminate()
        if callable(wait):
            try:
                wait(timeout=5)
            except (TimeoutError, subprocess.TimeoutExpired):
                if callable(kill):
                    kill()
        self._state = "stopped"

    def command(self) -> list[str]:
        return [
            "kubectl",
            "port-forward",
            "--namespace",
            self.configuration.namespace,
            self.configuration.service,
            f"{self._local_port}:{self.configuration.remote_port}",
        ]

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "managed": self._process is not None,
            "ready": self._probe_existing(),
            "state": self._state,
            "url": self.configuration.url,
            "message": self._message,
            "pid": getattr(self._process, "pid", None),
        }

    def _probe_existing(self) -> bool:
        if self._existing_ready is not None:
            return self._existing_ready
        try:
            return bool(self._probe())
        except Exception:
            return False

    def _http_probe(self) -> bool:
        with urlopen(self.configuration.url + "/-/ready", timeout=2) as response:
            return 200 <= response.status < 300

    def _process_is_running(self, process: object | None = None) -> bool:
        candidate = process if process is not None else self._process
        if candidate is None:
            return False
        poll = getattr(candidate, "poll", None)
        return callable(poll) and poll() is None

    @staticmethod
    def _default_popen(command: Sequence[str]) -> subprocess.Popen[str]:
        return subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            text=True,
        )
