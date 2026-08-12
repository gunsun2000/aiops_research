from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from aiops_k8s_agents.control_plane_process import (
    ControlPlaneProcessManager,
    ProcessConfiguration,
    _print_result,
    is_control_plane_command,
)


class _FakeProcess:
    def __init__(self, pid: int = 4321, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode

    def poll(self) -> int | None:
        return self._returncode


def _configuration(tmp_path: Path) -> ProcessConfiguration:
    return ProcessConfiguration(
        root=tmp_path,
        python_executable=Path("/opt/conda/envs/aiops_research/bin/python"),
        host="127.0.0.1",
        port=19180,
        startup_timeout=0.2,
    )


def test_process_identity_accepts_only_aiops_control_plane_commands():
    assert is_control_plane_command(
        "/opt/python -m aiops_k8s_agents.control_plane_launcher"
    )
    assert is_control_plane_command("/opt/bin/aiops-control-plane")
    assert not is_control_plane_command("python -m http.server 18180")


def test_start_rejects_an_unrelated_port_listener(tmp_path):
    manager = ControlPlaneProcessManager(
        _configuration(tmp_path),
        health_probe=lambda: False,
        listener_pid=lambda _port: 777,
        command_reader=lambda _pid: "python -m http.server 19180",
    )

    result = manager.start()

    assert result["ok"] is False
    assert result["status"] == "port_in_use"
    assert "777" in result["message"]


def test_restart_stops_managed_listener_and_waits_for_health(tmp_path):
    probes = iter([False, True])
    stopped: list[int] = []
    spawned: list[list[str]] = []

    def spawn(command, **_kwargs):
        spawned.append(list(command))
        return _FakeProcess()

    manager = ControlPlaneProcessManager(
        _configuration(tmp_path),
        health_probe=lambda: next(probes, True),
        listener_pid=lambda _port: 321,
        command_reader=lambda _pid: (
            "/opt/python -m aiops_k8s_agents.control_plane_launcher"
        ),
        process_stopper=lambda pid: stopped.append(pid),
        process_spawner=spawn,
        sleeper=lambda _seconds: None,
    )

    result = manager.restart()

    assert result["ok"] is True
    assert result["status"] == "ready"
    assert stopped == [321]
    assert spawned[0][-2:] == ["-m", "aiops_k8s_agents.control_plane_launcher"]
    assert manager.configuration.pid_file.read_text(encoding="utf-8") == "4321\n"


def test_status_reports_connection_summary_when_server_is_ready(tmp_path):
    payload = {
        "connections": {
            "kubernetes": {"ready": True},
            "prometheus": {
                "ready": True,
                "port_forward": {"managed": True},
            },
            "chaos_mesh": {"ready": True},
            "aiopslab": {"ready": True},
            "autogen": {"ready": False, "status": "missing_credentials"},
        }
    }
    manager = ControlPlaneProcessManager(
        _configuration(tmp_path),
        health_probe=lambda: True,
        listener_pid=lambda _port: 4321,
        command_reader=lambda _pid: "aiops-control-plane",
        connections_probe=lambda: payload,
    )

    result = manager.status()

    assert result["ok"] is True
    assert result["connections"]["prometheus"]["ready"] is True
    assert result["connections"]["autogen"]["status"] == "missing_credentials"
    json.dumps(result)


def test_default_health_probe_requires_control_plane_service_identity(
    tmp_path, monkeypatch
):
    class Response(BytesIO):
        status = 200

    payloads = iter(
        [
            b'{"status":"ok","service":"another-service"}',
            b'{"status":"ok","service":"aiops-control-plane"}',
        ]
    )
    monkeypatch.setattr(
        "aiops_k8s_agents.control_plane_process.urlopen",
        lambda *_args, **_kwargs: Response(next(payloads)),
    )
    manager = ControlPlaneProcessManager(_configuration(tmp_path))

    assert manager._default_health_probe() is False
    assert manager._default_health_probe() is True


def test_stop_uses_verified_pid_file_when_listener_lookup_is_unavailable(tmp_path):
    configuration = _configuration(tmp_path)
    configuration.runtime_directory.mkdir(parents=True)
    configuration.pid_file.write_text("6543\n", encoding="utf-8")
    stopped: list[int] = []
    manager = ControlPlaneProcessManager(
        configuration,
        health_probe=lambda: False,
        listener_pid=lambda _port: None,
        command_reader=lambda pid: (
            "/opt/python -m aiops_k8s_agents.control_plane_launcher"
            if pid == 6543
            else ""
        ),
        process_stopper=lambda pid: stopped.append(pid),
    )

    result = manager.stop()

    assert result["ok"] is True
    assert stopped == [6543]
    assert not configuration.pid_file.exists()


def test_stale_pid_file_never_stops_an_unrelated_process(tmp_path):
    configuration = _configuration(tmp_path)
    configuration.runtime_directory.mkdir(parents=True)
    configuration.pid_file.write_text("7654\n", encoding="utf-8")
    stopped: list[int] = []
    manager = ControlPlaneProcessManager(
        configuration,
        health_probe=lambda: False,
        listener_pid=lambda _port: None,
        command_reader=lambda _pid: "python -m http.server 19180",
        process_stopper=lambda pid: stopped.append(pid),
    )

    result = manager.stop()

    assert result["ok"] is True
    assert result["status"] == "stopped"
    assert stopped == []
    assert not configuration.pid_file.exists()


def test_ready_output_shows_url_log_and_korean_connection_states(capsys):
    _print_result(
        {
            "ok": True,
            "status": "ready",
            "message": "Control Plane이 준비되었습니다.",
            "url": "http://127.0.0.1:18180",
            "log_file": "/repo/runs/control-plane/server-18180.log",
            "connections": {
                "kubernetes": {"ready": True},
                "prometheus": {
                    "ready": True,
                    "port_forward": {"managed": True},
                },
                "chaos_mesh": {"ready": True},
                "aiopslab": {"ready": True},
                "autogen": {"ready": False, "status": "missing_credentials"},
            },
        }
    )

    output = capsys.readouterr().out
    assert "접속 주소: http://127.0.0.1:18180" in output
    assert "로그: /repo/runs/control-plane/server-18180.log" in output
    assert "Kubernetes: 연결됨" in output
    assert "Prometheus: 자동 연결됨" in output
    assert "AutoGen: 설정 필요" in output


def test_real_background_process_start_status_and_stop(tmp_path, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    project_root = Path(__file__).resolve().parents[1]
    pythonpath = str(project_root / "src")
    if os.environ.get("PYTHONPATH"):
        pythonpath += os.pathsep + os.environ["PYTHONPATH"]
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.setenv("AIOPS_AUTO_PORT_FORWARD", "off")
    monkeypatch.setenv("AIOPS_JOB_DATABASE", str(tmp_path / "jobs.sqlite3"))

    processes: dict[int, subprocess.Popen[str]] = {}

    def spawn(command, **kwargs):
        process = subprocess.Popen(command, **kwargs)
        processes[process.pid] = process
        return process

    def read_command(pid):
        process = processes.get(pid)
        if process is not None and process.poll() is None:
            return f"{sys.executable} -m aiops_k8s_agents.control_plane_launcher"
        return ""

    def stop_process(pid):
        process = processes[pid]
        process.terminate()
        process.wait(timeout=10)

    manager = ControlPlaneProcessManager(
        ProcessConfiguration(
            root=tmp_path,
            python_executable=Path(sys.executable),
            port=port,
            startup_timeout=20,
        ),
        listener_pid=lambda _port: None,
        command_reader=read_command,
        process_stopper=stop_process,
        process_spawner=spawn,
    )

    try:
        started = manager.restart()
        assert started["ok"] is True
        assert started["status"] == "ready"
        assert manager.status()["status"] == "ready"
    finally:
        stopped = manager.stop()
        assert stopped["ok"] is True
        assert stopped["status"] == "stopped"
