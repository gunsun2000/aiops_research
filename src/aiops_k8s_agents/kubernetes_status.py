from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

JsonRunner = Callable[[list[str]], tuple[int, str, str]]


def subprocess_json_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"command timed out after 15.0s: {exc}"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def collect_kubernetes_snapshot(
    namespace: str,
    deployment: str,
    runner: JsonRunner = subprocess_json_runner,
) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "deployment": deployment,
        "deployment_status": _deployment_status(namespace, deployment, runner),
        "pods": _pod_status(namespace, deployment, runner),
    }


def _deployment_status(
    namespace: str,
    deployment: str,
    runner: JsonRunner,
) -> dict[str, Any]:
    payload = _kubectl_json(
        [
            "kubectl",
            "get",
            "deployment",
            deployment,
            "-n",
            namespace,
            "-o",
            "json",
        ],
        runner,
    )
    if not payload["ok"]:
        return payload

    data = payload["data"]
    status = data.get("status", {})
    spec = data.get("spec", {})
    return {
        "ok": True,
        "name": data.get("metadata", {}).get("name", deployment),
        "desired_replicas": spec.get("replicas", 0),
        "ready_replicas": status.get("readyReplicas", 0),
        "available_replicas": status.get("availableReplicas", 0),
        "updated_replicas": status.get("updatedReplicas", 0),
    }


def _pod_status(
    namespace: str,
    deployment: str,
    runner: JsonRunner,
) -> dict[str, Any]:
    payload = _kubectl_json(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"app={deployment}",
            "-o",
            "json",
        ],
        runner,
    )
    if not payload["ok"]:
        return payload

    pods = [_summarize_pod(item) for item in payload["data"].get("items", [])]
    return {
        "ok": True,
        "count": len(pods),
        "running": sum(1 for pod in pods if pod["phase"] == "Running"),
        "items": pods,
    }


def _summarize_pod(item: dict[str, Any]) -> dict[str, Any]:
    statuses = item.get("status", {}).get("containerStatuses", [])
    ready = sum(1 for status in statuses if status.get("ready"))
    restarts = sum(int(status.get("restartCount", 0)) for status in statuses)
    return {
        "name": item.get("metadata", {}).get("name", ""),
        "uid": item.get("metadata", {}).get("uid", ""),
        "phase": item.get("status", {}).get("phase", ""),
        "ready": f"{ready}/{len(statuses)}",
        "restarts": restarts,
    }


def _kubectl_json(argv: list[str], runner: JsonRunner) -> dict[str, Any]:
    return_code, stdout, stderr = runner(argv)
    if return_code != 0:
        return {
            "ok": False,
            "command": " ".join(argv),
            "stderr": stderr,
        }
    try:
        return {"ok": True, "data": json.loads(stdout)}
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "command": " ".join(argv),
            "stderr": f"kubectl returned invalid JSON: {exc}",
        }
