from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable, Mapping


CommandRunner = Callable[[list[str]], tuple[int, str, str]]
_KIND_PATTERN = re.compile(r"^\s*kind\s*:\s*([A-Za-z0-9]+)\s*(?:#.*)?$")
_SUPPORTED_KINDS = {"stresschaos", "networkchaos", "podchaos", "iochaos", "timechaos"}


@dataclass(frozen=True)
class ChaosScenario:
    scenario_id: str
    manifest: Path
    kind: str


@dataclass(frozen=True)
class ChaosPreflight:
    valid: bool
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ChaosApplication:
    scenario: ChaosScenario
    applied_at: str
    valid: bool
    stdout: str = ""
    stderr: str = ""
    cleanup_required: bool = False


@dataclass(frozen=True)
class ChaosCleanup:
    valid: bool
    stdout: str = ""
    stderr: str = ""
    cleanup_required: bool = True


class ChaosMeshAdapter:
    """Bounded Chaos Mesh lifecycle adapter using only registered manifests."""

    def __init__(
        self,
        scenarios: Mapping[str, str | Path],
        *,
        runner: CommandRunner | None = None,
        sleeper: Callable[[float], None] = sleep,
        manifest_root: str | Path | None = None,
        wait_timeout_seconds: int = 60,
    ) -> None:
        if isinstance(wait_timeout_seconds, bool) or wait_timeout_seconds < 1:
            raise ValueError("wait_timeout_seconds must be positive")
        self._runner = runner or self._subprocess_runner
        self._sleeper = sleeper
        self._repository_root = Path(__file__).resolve().parents[2]
        self._manifest_root = Path(manifest_root or self._repository_root / "k8s").resolve()
        self._wait_timeout_seconds = wait_timeout_seconds
        self._scenarios = {
            self._scenario_id(key): self._registered_scenario(key, value)
            for key, value in scenarios.items()
        }

    def preflight(self) -> ChaosPreflight:
        try:
            scenarios = tuple(self._scenarios.values())
            for scenario in scenarios:
                self._assert_manifest_is_safe(scenario.manifest)
                if not scenario.manifest.is_file():
                    raise ValueError(f"manifest does not exist: {scenario.manifest}")
                self._read_kind(scenario.manifest)

            required_kinds = {self._read_kind(scenario.manifest).lower() for scenario in scenarios}
            if not required_kinds:
                return ChaosPreflight(valid=False, stderr="no chaos scenarios are registered")
            code, stdout, stderr = self._run(["kubectl", "api-resources"])
            if code != 0:
                return ChaosPreflight(False, stdout, stderr or "kubectl api-resources failed")
            resources = {line.split()[0].lower() for line in stdout.splitlines() if line.split()}
            missing = sorted(kind for kind in required_kinds if kind not in resources)
            if missing:
                return ChaosPreflight(False, stdout, "missing Chaos Mesh resources: " + ", ".join(missing))
            return ChaosPreflight(True, stdout, stderr)
        except (OSError, ValueError) as exc:
            return ChaosPreflight(False, stderr=str(exc))

    def inject(self, scenario_id: str) -> ChaosApplication:
        scenario = self._scenarios.get(str(scenario_id).strip())
        if scenario is None:
            raise ValueError(f"unknown chaos scenario: {scenario_id}")
        self._assert_manifest_is_safe(scenario.manifest)
        scenario = replace(scenario, kind=self._read_kind(scenario.manifest))
        applied_at = datetime.now(timezone.utc).isoformat()
        apply_code, apply_out, apply_err = self._run(
            ["kubectl", "apply", "-f", str(scenario.manifest)]
        )
        if apply_code != 0:
            return ChaosApplication(scenario, applied_at, False, apply_out, apply_err, True)

        self._sleeper(0)
        wait_code, wait_out, wait_err = self._run(
            [
                "kubectl", "wait", "--for=condition=AllInjected", "-f",
                str(scenario.manifest), f"--timeout={self._wait_timeout_seconds}s",
            ]
        )
        return ChaosApplication(
            scenario=scenario,
            applied_at=applied_at,
            valid=wait_code == 0,
            stdout=apply_out + wait_out,
            stderr=apply_err + wait_err,
            cleanup_required=True,
        )

    def cleanup(self, application: ChaosApplication) -> ChaosCleanup:
        if not isinstance(application, ChaosApplication):
            raise TypeError("application must be a ChaosApplication")
        self._assert_manifest_is_safe(application.scenario.manifest)
        code, stdout, stderr = self._run(
            ["kubectl", "delete", "-f", str(application.scenario.manifest), "--ignore-not-found"]
        )
        return ChaosCleanup(
            valid=code == 0,
            stdout=stdout,
            stderr=stderr,
            cleanup_required=code != 0,
        )

    def _registered_scenario(self, scenario_id: str, manifest: str | Path) -> ChaosScenario:
        path = self._resolve_manifest(Path(manifest))
        return ChaosScenario(scenario_id, path, "")

    def _resolve_manifest(self, path: Path) -> Path:
        if path.is_absolute():
            return path.resolve()
        if path.parts and path.parts[0].lower() == self._manifest_root.name.lower():
            return (self._repository_root / path).resolve()
        return (self._manifest_root / path).resolve()

    def _assert_manifest_is_safe(self, path: Path) -> None:
        try:
            path.relative_to(self._manifest_root)
        except ValueError as exc:
            raise ValueError(f"manifest must resolve under {self._manifest_root}: {path}") from exc

    @staticmethod
    def _read_kind(path: Path) -> str:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = _KIND_PATTERN.match(line)
                if match:
                    kind = match.group(1)
                    if kind.lower() not in _SUPPORTED_KINDS:
                        raise ValueError(f"unsupported Chaos Mesh resource kind: {kind}")
                    return kind
        except OSError as exc:
            raise ValueError(f"cannot read manifest: {path}") from exc
        raise ValueError(f"manifest kind is missing: {path}")

    @staticmethod
    def _scenario_id(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("scenario id must not be empty")
        return value.strip()

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        result = self._runner(list(argv))
        if len(result) != 3:
            raise ValueError("command runner must return (returncode, stdout, stderr)")
        return int(result[0]), str(result[1]), str(result[2])

    @staticmethod
    def _subprocess_runner(argv: list[str]) -> tuple[int, str, str]:
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        return completed.returncode, completed.stdout, completed.stderr
