from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Mapping

from aiops_k8s_agents.aiopslab_evaluator import attach_aiopslab_evaluation
from aiops_k8s_agents.aiopslab_jobs import AIOpsLabBenchmarkRequest


def resolve_aiopslab_python(
    *,
    env: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    current_python: str | Path | None = None,
) -> Path:
    """Resolve the interpreter used by the external AIOpsLab runtime.

    The web server commonly runs in ``aiops_research`` while AIOpsLab's
    dependencies live in its own conda environment.  Prefer an explicit
    server-owned path, then discover the conventional conda locations before
    falling back to the interpreter running this process.
    """

    environment = os.environ if env is None else env
    explicit = str(environment.get("AIOPSLAB_PYTHON", "")).strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    home_path = Path.home() if home is None else Path(home).expanduser()
    candidates = (
        home_path / "anaconda3" / "envs" / "aiopslab" / "bin" / "python",
        home_path / "miniconda3" / "envs" / "aiopslab" / "bin" / "python",
        home_path / "anaconda3" / "envs" / "aiopslab" / "python.exe",
        home_path / "miniconda3" / "envs" / "aiopslab" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    return Path(current_python or sys.executable).expanduser().resolve()


@dataclass(frozen=True)
class AIOpsLabBenchmarkSpec:
    benchmark_id: str
    title: str
    problem_id: str
    namespace: str
    service: str
    metrics_duration_minutes: int
    max_steps: int
    timeout_seconds: int
    max_repetitions: int
    subtitle: str = ""
    tag: str = "AIOpsLab"
    description: str = ""
    dataset_label: str = "AIOpsLab Dataset"
    icon: str = "▦"

    def validate_request(
        self,
        request: AIOpsLabBenchmarkRequest,
        *,
        repetitions_override: int | None = None,
    ) -> None:
        if request.benchmark_id != self.benchmark_id:
            raise ValueError("benchmark request does not match registered specification")
        repetitions = (
            request.repetitions
            if repetitions_override is None
            else repetitions_override
        )
        if repetitions > self.max_repetitions:
            raise ValueError(
                f"maximum repetitions for {self.benchmark_id} is "
                f"{self.max_repetitions}"
            )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.benchmark_id,
            "title": self.title,
            "problem_id": self.problem_id,
            "namespace": self.namespace,
            "service": self.service,
            "max_repetitions": self.max_repetitions,
            "subtitle": self.subtitle,
            "tag": self.tag,
            "description": self.description,
            "dataset_label": self.dataset_label,
            "icon": self.icon,
        }


class AIOpsLabBenchmarkCatalog:
    def __init__(self, specs: tuple[AIOpsLabBenchmarkSpec, ...]) -> None:
        if not specs:
            raise ValueError("at least one AIOpsLab benchmark must be registered")
        by_id = {spec.benchmark_id: spec for spec in specs}
        if len(by_id) != len(specs):
            raise ValueError("duplicate AIOpsLab benchmark id")
        self._specs = by_id

    @classmethod
    def from_path(cls, path: str | Path) -> "AIOpsLabBenchmarkCatalog":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw_specs = data.get("benchmarks", [])
        if not isinstance(raw_specs, list):
            raise ValueError("benchmarks must be a list")
        return cls(tuple(_spec_from_dict(item) for item in raw_specs))

    def resolve(self, benchmark_id: str) -> AIOpsLabBenchmarkSpec:
        try:
            return self._specs[benchmark_id]
        except KeyError as exc:
            raise KeyError(f"AIOpsLab benchmark is not registered: {benchmark_id}") from exc

    def to_public_list(self) -> list[dict[str, Any]]:
        return [
            self._specs[key].to_public_dict()
            for key in sorted(self._specs)
        ]


@dataclass(frozen=True)
class AIOpsLabExecutionResult:
    report_path: Path
    returncode: int
    stdout: str
    stderr: str


class AIOpsLabExecutionCancelled(RuntimeError):
    pass


class AIOpsLabBenchmarkExecutor:
    """Runs a server-registered AIOpsLab benchmark without invoking a shell."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        aiopslab_root: str | Path,
        python_executable: str | Path,
        kubeconfig: str | Path,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.aiopslab_root = Path(aiopslab_root).expanduser().resolve()
        self.python_executable = Path(python_executable).expanduser().resolve()
        self.kubeconfig = Path(kubeconfig).expanduser().resolve()
        self.runner_script = (
            self.repo_root / "scripts" / "server_aiopslab_auto_detection.py"
        )

    def readiness(self) -> dict[str, Any]:
        checks = (
            (self.repo_root.is_dir(), "project root not found"),
            (self.runner_script.is_file(), "AIOpsLab runner script not found"),
            (self.aiopslab_root.is_dir(), "AIOpsLab root not found"),
            (self.python_executable.is_file(), "AIOpsLab Python executable not found"),
            (self.kubeconfig.is_file(), "kubeconfig not found"),
        )
        reasons = [reason for valid, reason in checks if not valid]
        return {"ready": not reasons, "reasons": reasons}

    def build_command(
        self,
        spec: AIOpsLabBenchmarkSpec,
        *,
        output_dir: str | Path,
    ) -> list[str]:
        output_dir = Path(output_dir).expanduser().resolve()
        return [
            str(self.python_executable),
            str(self.runner_script),
            "--aiopslab-root",
            str(self.aiopslab_root),
            "--problem-id",
            spec.problem_id,
            "--namespace",
            spec.namespace,
            "--service",
            spec.service,
            "--metrics-duration-minutes",
            str(spec.metrics_duration_minutes),
            "--max-steps",
            str(spec.max_steps),
            "--kubeconfig",
            str(self.kubeconfig),
            "--save-result-dir",
            str(output_dir),
            "--quiet-decisions",
        ]

    def execute(
        self,
        spec: AIOpsLabBenchmarkSpec,
        *,
        job_id: str,
        repetition: int,
        output_dir: str | Path,
        cancellation: Event,
    ) -> AIOpsLabExecutionResult:
        readiness = self.readiness()
        if not readiness["ready"]:
            raise RuntimeError("; ".join(readiness["reasons"]))
        output_dir = Path(output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        previous_reports = set(output_dir.glob("*_aiopslab_auto_detection.json"))
        command = self.build_command(spec, output_dir=output_dir)
        env = os.environ.copy()
        env["KUBECONFIG"] = str(self.kubeconfig)
        process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        deadline = time.monotonic() + spec.timeout_seconds
        try:
            while process.poll() is None:
                if cancellation.wait(timeout=0.25):
                    _terminate(process)
                    raise AIOpsLabExecutionCancelled(
                        f"AIOpsLab benchmark cancelled: {job_id}/{repetition}"
                    )
                if time.monotonic() >= deadline:
                    _terminate(process)
                    raise TimeoutError(
                        f"AIOpsLab benchmark timed out after {spec.timeout_seconds}s"
                    )
            stdout, stderr = process.communicate(timeout=5)
        except BaseException:
            if process.poll() is None:
                _terminate(process)
            raise

        stdout = sanitize_benchmark_output(stdout)
        stderr = sanitize_benchmark_output(stderr)
        if process.returncode != 0:
            detail = stderr or stdout or "AIOpsLab benchmark failed"
            raise RuntimeError(detail[-4000:])
        new_reports = sorted(
            set(output_dir.glob("*_aiopslab_auto_detection.json")) - previous_reports,
            key=lambda path: path.stat().st_mtime_ns,
        )
        if not new_reports:
            raise RuntimeError("AIOpsLab benchmark did not produce a report")
        report_path = new_reports[-1]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        attach_aiopslab_evaluation(
            report,
            max_steps=spec.max_steps,
            metrics_duration_minutes=spec.metrics_duration_minutes,
        )
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return AIOpsLabExecutionResult(
            report_path=report_path,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )


def sanitize_benchmark_output(value: str) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)\b(OPENAI_(?:API|ADMIN)_KEY)\s*=\s*[^\s]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\bsk-[A-Za-z0-9_-]{8,}",
        "[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)[A-Z]:\\Users\\[^\\\s]+",
        r"C:\\Users\\[REDACTED]",
        text,
    )
    home = str(Path.home())
    if home:
        text = text.replace(home, "[HOME]")
    return text


def _spec_from_dict(data: Mapping[str, Any]) -> AIOpsLabBenchmarkSpec:
    if not isinstance(data, Mapping):
        raise ValueError("benchmark specification must be an object")
    return AIOpsLabBenchmarkSpec(
        benchmark_id=str(data["id"]).strip(),
        title=str(data["title"]).strip(),
        problem_id=str(data["problem_id"]).strip(),
        namespace=str(data["namespace"]).strip(),
        service=str(data["service"]).strip(),
        metrics_duration_minutes=int(data["metrics_duration_minutes"]),
        max_steps=int(data["max_steps"]),
        timeout_seconds=int(data["timeout_seconds"]),
        max_repetitions=int(data["max_repetitions"]),
        subtitle=str(data.get("subtitle", "")).strip(),
        tag=str(data.get("tag", "AIOpsLab")).strip(),
        description=str(data.get("description", "")).strip(),
        dataset_label=str(data.get("dataset_label", "AIOpsLab Dataset")).strip(),
        icon=str(data.get("icon", "▦")).strip(),
    )


def _terminate(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
