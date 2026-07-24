from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class OperationLockError(RuntimeError):
    """Raised when another real recovery owns the same Kubernetes target."""


@dataclass
class TargetOperationLock:
    namespace: str
    deployment: str
    lock_dir: str | Path | None = None
    stale_after_seconds: float = 3600.0
    token: str = field(default_factory=lambda: uuid4().hex)
    _acquired: bool = field(default=False, init=False, repr=False)

    @property
    def path(self) -> Path:
        root = (
            Path(self.lock_dir)
            if self.lock_dir is not None
            else Path(tempfile.gettempdir()) / "aiops-mutual-supervision-locks"
        )
        target = f"{self.namespace}/{self.deployment}".encode("utf-8")
        digest = hashlib.sha256(target).hexdigest()[:24]
        return root / f"{digest}.lock"

    def __enter__(self) -> TargetOperationLock:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "token": self.token,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "namespace": self.namespace,
                "deployment": self.deployment,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        descriptor: int | None = None
        for attempt in range(2):
            try:
                descriptor = os.open(
                    path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                break
            except FileExistsError as exc:
                if attempt == 0 and self._clear_stale_lock(path):
                    continue
                raise OperationLockError(
                    "a real recovery operation is already active for "
                    f"{self.namespace}/{self.deployment}"
                ) from exc
        if descriptor is None:
            raise OperationLockError(
                f"could not acquire operation lock for {self.namespace}/{self.deployment}"
            )

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(payload)
                output.write("\n")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        self._acquired = True
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if not self._acquired:
            return
        path = self.path
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            owner = {}
        if owner.get("token") == self.token:
            path.unlink(missing_ok=True)
        self._acquired = False

    def _clear_stale_lock(self, path: Path) -> bool:
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
            modified_at = path.stat().st_mtime
        except (json.JSONDecodeError, OSError):
            owner = {}
            try:
                modified_at = path.stat().st_mtime
            except OSError:
                return False

        owner_token = owner.get("token")
        owner_host = str(owner.get("host", ""))
        owner_pid = owner.get("pid")
        same_host = owner_host == socket.gethostname()
        dead_local_process = (
            same_host
            and isinstance(owner_pid, int)
            and not _pid_is_running(owner_pid)
        )
        age_seconds = max(datetime.now().timestamp() - modified_at, 0.0)
        expired_unknown_owner = (
            not same_host and age_seconds >= self.stale_after_seconds
        )
        if not (dead_local_process or expired_unknown_owner):
            return False

        try:
            current_owner = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current_owner = {}
        if current_owner.get("token") != owner_token:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        return True


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _windows_pid_is_running(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True
