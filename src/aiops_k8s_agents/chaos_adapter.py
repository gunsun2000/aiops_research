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
    scenario_id: str | None = None
    manifest: str | None = None
    resource_kind: str | None = None
    missing_prerequisites: tuple[str, ...] = ()


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
        repository_root: str | Path | None = None,
        wait_timeout_seconds: int = 60,
        command_timeout_seconds: int = 15,
    ) -> None:
        if isinstance(wait_timeout_seconds, bool) or wait_timeout_seconds < 1:
            raise ValueError("wait_timeout_seconds must be positive")
        if isinstance(command_timeout_seconds, bool) or command_timeout_seconds < 1:
            raise ValueError("command_timeout_seconds must be positive")
        self._runner = runner or self._subprocess_runner
        self._uses_subprocess_runner = runner is None
        self._sleeper = sleeper
        self._repository_root = Path(repository_root or Path(__file__).resolve().parents[2]).resolve()
        self._manifest_root = (self._repository_root / "k8s").resolve()
        self._wait_timeout_seconds = wait_timeout_seconds
        self._command_timeout_seconds = command_timeout_seconds
        self._scenarios = {
            self._scenario_id(key): self._registered_scenario(key, value)
            for key, value in scenarios.items()
            if getattr(value, "incident_source", "chaos_mesh") == "chaos_mesh"
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
            resources = {
                token.lower()
                for line in stdout.splitlines()
                for token in line.split()
            }
            missing = sorted(kind for kind in required_kinds if kind not in resources)
            if missing:
                return ChaosPreflight(
                    False,
                    stdout,
                    "missing Chaos Mesh resources: " + ", ".join(missing),
                    missing_prerequisites=tuple(
                        f"chaos_mesh.resource_kind:{kind}" for kind in missing
                    ),
                )
            return ChaosPreflight(True, stdout, stderr)
        except (OSError, ValueError) as exc:
            return ChaosPreflight(False, stderr=str(exc))

    def preflight_scenario(self, scenario_id: str) -> ChaosPreflight:
        """Check one registered manifest and its exact Chaos Mesh kind only."""
        scenario = self._scenarios.get(str(scenario_id).strip())
        if scenario is None:
            return ChaosPreflight(
                False,
                scenario_id=str(scenario_id),
                missing_prerequisites=(f"scenario:{scenario_id}",),
            )
        try:
            self._assert_manifest_is_safe(scenario.manifest)
            if not scenario.manifest.is_file():
                return ChaosPreflight(
                    False,
                    scenario_id=scenario.scenario_id,
                    manifest=str(scenario.manifest),
                    missing_prerequisites=(f"scenario_manifest:{scenario.scenario_id}",),
                )
            resource_kind = self._read_kind(scenario.manifest)
            code, stdout, stderr = self._run(["kubectl", "api-resources"])
            if code != 0:
                return ChaosPreflight(
                    False,
                    stdout,
                    "Chaos Mesh resource discovery unavailable",
                    scenario_id=scenario.scenario_id,
                    manifest=str(scenario.manifest),
                    resource_kind=resource_kind,
                    missing_prerequisites=("chaos_mesh.api_resources",),
                )
            resources = {
                token.lower()
                for line in stdout.splitlines()
                for token in line.split()
            }
            if resource_kind.lower() not in resources:
                return ChaosPreflight(
                    False,
                    stdout,
                    "Chaos Mesh resource kind is unavailable",
                    scenario_id=scenario.scenario_id,
                    manifest=str(scenario.manifest),
                    resource_kind=resource_kind,
                    missing_prerequisites=(
                        f"chaos_mesh.resource_kind:{resource_kind}",
                    ),
                )
            return ChaosPreflight(
                True,
                stdout,
                stderr,
                scenario_id=scenario.scenario_id,
                manifest=str(scenario.manifest),
                resource_kind=resource_kind,
            )
        except (OSError, ValueError):
            return ChaosPreflight(
                False,
                scenario_id=scenario.scenario_id,
                manifest=str(scenario.manifest),
                missing_prerequisites=(f"scenario_manifest:{scenario.scenario_id}",),
            )

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

        try:
            self._sleeper(0)
        except Exception as exc:
            return ChaosApplication(
                scenario, applied_at, False, apply_out, apply_err + str(exc), True
            )
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
        timeout = self._command_timeout_seconds
        if len(argv) > 1 and argv[1] == "wait":
            timeout += self._wait_timeout_seconds
        try:
            if self._uses_subprocess_runner:
                result = self._subprocess_runner(list(argv), timeout=timeout)
            else:
                result = self._runner(list(argv))
            if len(result) != 3:
                raise ValueError("command runner must return (returncode, stdout, stderr)")
            return int(result[0]), str(result[1]), str(result[2])
        except subprocess.TimeoutExpired as exc:
            stdout = _command_output(exc.stdout)
            stderr = _command_output(exc.stderr)
            return 124, stdout, stderr + f"command timed out after {timeout}s"
        except OSError as exc:
            return 126, "", str(exc)
        except Exception as exc:
            return 125, "", str(exc)

    @staticmethod
    def _subprocess_runner(argv: list[str], *, timeout: int) -> tuple[int, str, str]:
        completed = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=timeout
        )
        return completed.returncode, completed.stdout, completed.stderr


def _command_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
