"""Start and supervise the research Control Plane as a background process."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


def is_control_plane_command(command: str) -> bool:
    normalized = command.replace("\\", "/").lower()
    return (
        "aiops-control-plane" in normalized
        or "aiops_k8s_agents.control_plane_launcher" in normalized
    )


@dataclass(frozen=True)
class ProcessConfiguration:
    root: Path
    python_executable: Path
    host: str = "127.0.0.1"
    port: int = 18180
    startup_timeout: float = 30.0

    @property
    def runtime_directory(self) -> Path:
        return self.root / "runs" / "control-plane"

    @property
    def pid_file(self) -> Path:
        return self.runtime_directory / f"server-{self.port}.pid"

    @property
    def log_file(self) -> Path:
        return self.runtime_directory / f"server-{self.port}.log"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class ControlPlaneProcessManager:
    def __init__(
        self,
        configuration: ProcessConfiguration,
        *,
        health_probe: Callable[[], bool] | None = None,
        connections_probe: Callable[[], Mapping[str, Any]] | None = None,
        listener_pid: Callable[[int], int | None] | None = None,
        command_reader: Callable[[int], str] | None = None,
        process_stopper: Callable[[int], None] | None = None,
        process_spawner: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.configuration = configuration
        self._health_probe = health_probe or self._default_health_probe
        self._connections_probe = connections_probe or self._default_connections_probe
        self._listener_pid = listener_pid or _linux_listener_pid
        self._command_reader = command_reader or _linux_command_reader
        self._process_stopper = process_stopper or _stop_process
        self._process_spawner = process_spawner or subprocess.Popen
        self._sleep = sleeper

    def start(self) -> dict[str, Any]:
        if self._safe_health_probe():
            return self._ready_result("Control Plane이 이미 실행 중입니다.")

        listener = self._listener_pid(self.configuration.port)
        if listener is not None:
            command = self._command_reader(listener)
            if not is_control_plane_command(command):
                return {
                    "ok": False,
                    "status": "port_in_use",
                    "message": (
                        f"Port {self.configuration.port} is used by unrelated "
                        f"process PID {listener}: {command or 'unknown command'}"
                    ),
                    "url": self.configuration.base_url,
                }
            self._process_stopper(listener)

        return self._launch_and_wait()

    def restart(self) -> dict[str, Any]:
        stopped = self._stop_managed_listener()
        if stopped.get("status") == "port_in_use":
            return stopped
        return self._launch_and_wait()

    def stop(self) -> dict[str, Any]:
        result = self._stop_managed_listener()
        if result.get("ok"):
            self.configuration.pid_file.unlink(missing_ok=True)
        return result

    def status(self) -> dict[str, Any]:
        if not self._safe_health_probe():
            listener = self._listener_pid(self.configuration.port)
            return {
                "ok": False,
                "status": "stopped" if listener is None else "unhealthy",
                "message": "Control Plane is not reachable.",
                "url": self.configuration.base_url,
                "pid": listener,
            }
        return self._ready_result("Control Plane is ready.")

    def _launch_and_wait(self) -> dict[str, Any]:
        config = self.configuration
        config.runtime_directory.mkdir(parents=True, exist_ok=True)
        command = [
            str(config.python_executable),
            "-m",
            "aiops_k8s_agents.control_plane_launcher",
        ]
        environment = os.environ.copy()
        environment["AIOPS_BIND_ADDRESS"] = config.host
        environment["PORT"] = str(config.port)

        with config.log_file.open("a", encoding="utf-8") as log_stream:
            try:
                process = self._process_spawner(
                    command,
                    cwd=config.root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    text=True,
                )
            except OSError as exc:
                return {
                    "ok": False,
                    "status": "start_failed",
                    "message": f"Could not start Control Plane: {exc}",
                    "url": config.base_url,
                    "log_file": str(config.log_file),
                }

        config.pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
        deadline = time.monotonic() + config.startup_timeout
        while time.monotonic() < deadline:
            if self._safe_health_probe():
                return self._ready_result("Control Plane이 준비되었습니다.")
            if process.poll() is not None:
                break
            self._sleep(0.25)

        return {
            "ok": False,
            "status": "start_failed",
            "message": "Control Plane did not become healthy before the timeout.",
            "url": config.base_url,
            "pid": process.pid,
            "log_file": str(config.log_file),
            "log_tail": _tail(config.log_file),
        }

    def _stop_managed_listener(self) -> dict[str, Any]:
        listener = self._listener_pid(self.configuration.port)
        if listener is None:
            listener = self._managed_pid_from_file()
        if listener is None:
            self.configuration.pid_file.unlink(missing_ok=True)
            return {
                "ok": True,
                "status": "stopped",
                "message": "Control Plane이 이미 종료되어 있습니다.",
                "url": self.configuration.base_url,
            }
        command = self._command_reader(listener)
        if not is_control_plane_command(command):
            return {
                "ok": False,
                "status": "port_in_use",
                "message": (
                    f"Port {self.configuration.port} is used by unrelated "
                    f"process PID {listener}: {command or 'unknown command'}"
                ),
                "url": self.configuration.base_url,
            }
        self._process_stopper(listener)
        return {
            "ok": True,
            "status": "stopped",
            "message": f"Control Plane PID {listener}을 종료했습니다.",
            "url": self.configuration.base_url,
        }

    def _managed_pid_from_file(self) -> int | None:
        try:
            pid = int(self.configuration.pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        command = self._command_reader(pid)
        if is_control_plane_command(command):
            return pid
        self.configuration.pid_file.unlink(missing_ok=True)
        return None

    def _ready_result(self, message: str) -> dict[str, Any]:
        try:
            payload = dict(self._connections_probe())
        except Exception as exc:
            payload = {"connections": {}, "probe_error": str(exc)}
        return {
            "ok": True,
            "status": "ready",
            "message": message,
            "url": self.configuration.base_url,
            "pid": self._listener_pid(self.configuration.port),
            "log_file": str(self.configuration.log_file),
            "connections": payload.get("connections", {}),
        }

    def _safe_health_probe(self) -> bool:
        try:
            return bool(self._health_probe())
        except Exception:
            return False

    def _default_health_probe(self) -> bool:
        with urlopen(self.configuration.base_url + "/healthz", timeout=2) as response:
            if not 200 <= response.status < 300:
                return False
            payload = json.load(response)
            return (
                payload.get("status") == "ok"
                and payload.get("service") == "aiops-control-plane"
            )

    def _default_connections_probe(self) -> Mapping[str, Any]:
        with urlopen(
            self.configuration.base_url + "/api/connections", timeout=20
        ) as response:
            return json.load(response)


def _linux_listener_pid(port: int) -> int | None:
    try:
        completed = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"pid=(\d+)", completed.stdout)
    return int(match.group(1)) if match else None


def _linux_command_reader(pid: int) -> str:
    cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        if hasattr(os, "getuid") and cmdline.stat().st_uid != os.getuid():
            return ""
        return cmdline.read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        ).strip()
    except OSError:
        return ""


def _stop_process(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError(f"Control Plane PID {pid} did not stop within 8 seconds")


def _tail(path: Path, lines: int = 20) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:])
    except OSError:
        return ""


def _print_result(result: Mapping[str, Any]) -> None:
    print(result.get("message", ""))
    print(f"접속 주소: {result.get('url', '')}")
    if result.get("log_file"):
        print(f"로그: {result['log_file']}")
    if result.get("log_tail"):
        print("\nRecent log:")
        print(result["log_tail"])
    connections = result.get("connections", {})
    if isinstance(connections, Mapping) and connections:
        print("\n연결 상태:")
        labels = {
            "kubernetes": "Kubernetes",
            "prometheus": "Prometheus",
            "chaos_mesh": "Chaos Mesh",
            "aiopslab": "AIOpsLab",
            "autogen": "AutoGen",
        }
        for key, label in labels.items():
            value = connections.get(key, {})
            ready = isinstance(value, Mapping) and bool(value.get("ready"))
            if ready and key == "prometheus":
                port_forward = value.get("port_forward", {})
                managed = isinstance(port_forward, Mapping) and bool(
                    port_forward.get("managed")
                )
                state = "자동 연결됨" if managed else "연결됨"
            elif ready:
                state = "연결됨"
            elif key == "autogen" and isinstance(value, Mapping):
                state = "설정 필요"
            else:
                reason = value.get("reason", "미연결") if isinstance(value, Mapping) else "미연결"
                state = str(reason)
            print(f"- {label}: {state}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("start", "restart", "status", "stop"), nargs="?", default="restart"
    )
    args = parser.parse_args(argv)
    root = Path(os.environ.get("AIOPS_REPO_ROOT", Path.cwd())).resolve()
    manager = ControlPlaneProcessManager(
        ProcessConfiguration(
            root=root,
            python_executable=Path(sys.executable).resolve(),
            host=os.environ.get("AIOPS_BIND_ADDRESS", "127.0.0.1"),
            port=int(os.environ.get("PORT", "18180")),
            startup_timeout=float(os.environ.get("AIOPS_CONTROL_PLANE_TIMEOUT", "45")),
        )
    )
    result = getattr(manager, args.action)()
    _print_result(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
