from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher is Windows-specific")
def test_powershell_startup_prefers_the_current_checkout_source(tmp_path: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell is not installed")
    capture = tmp_path / "startup.txt"
    fake_python = tmp_path / "python.cmd"
    fake_python.write_text(
        "@echo off\r\n"
        "> \"%ORCHESTRATOR_STARTUP_CAPTURE%\" echo %PYTHONPATH%\r\n"
        ">> \"%ORCHESTRATOR_STARTUP_CAPTURE%\" echo %*\r\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    environment["PYTHONPATH"] = "preexisting-pythonpath"
    environment["ORCHESTRATOR_STARTUP_CAPTURE"] = str(capture)

    subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "start_orchestrator_agent.ps1"),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
    )

    python_path, arguments = capture.read_text(encoding="utf-8").splitlines()
    assert python_path.split(os.pathsep) == [
        str((ROOT / "src").resolve()),
        "preexisting-pythonpath",
    ]
    assert arguments == "-m orchestrator_agent.web"


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="POSIX launcher requires bash",
)
def test_posix_startup_prefers_the_current_checkout_source(tmp_path: Path) -> None:
    capture = tmp_path / "startup.txt"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s\\n%s\\n' \"$PYTHONPATH\" \"$*\" > \"$ORCHESTRATOR_STARTUP_CAPTURE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    environment["PYTHONPATH"] = "preexisting-pythonpath"
    environment["ORCHESTRATOR_STARTUP_CAPTURE"] = str(capture)

    subprocess.run(
        ["bash", str(ROOT / "scripts" / "start_orchestrator_agent.sh")],
        cwd=tmp_path,
        env=environment,
        check=True,
    )

    python_path, arguments = capture.read_text(encoding="utf-8").splitlines()
    assert python_path.split(os.pathsep) == [
        str((ROOT / "src").resolve()),
        "preexisting-pythonpath",
    ]
    assert arguments == "-m orchestrator_agent.web"
