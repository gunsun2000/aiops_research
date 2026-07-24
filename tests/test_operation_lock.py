from pathlib import Path
import json
import socket

import pytest

from aiops_k8s_agents.operation_lock import (
    OperationLockError,
    TargetOperationLock,
)


def test_target_operation_lock_rejects_second_real_controller(tmp_path: Path):
    first = TargetOperationLock(
        namespace="online-boutique",
        deployment="paymentservice",
        lock_dir=tmp_path,
    )
    second = TargetOperationLock(
        namespace="online-boutique",
        deployment="paymentservice",
        lock_dir=tmp_path,
    )

    with first:
        with pytest.raises(OperationLockError, match="already active"):
            with second:
                pass

    with second:
        assert second.path.exists()

    assert not second.path.exists()


def test_target_operation_lock_recovers_dead_process_lock(tmp_path: Path):
    lock = TargetOperationLock(
        namespace="online-boutique",
        deployment="paymentservice",
        lock_dir=tmp_path,
    )
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(
        json.dumps(
            {
                "token": "dead-owner",
                "pid": 2_147_483_647,
                "host": socket.gethostname(),
                "acquired_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with lock:
        owner = json.loads(lock.path.read_text(encoding="utf-8"))
        assert owner["token"] == lock.token

    assert not lock.path.exists()
