#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from aiops_k8s_agents.aiopslab_detection import (  # noqa: E402
    AIOpsLabDetectionPolicy,
    format_aiopslab_action,
)


class FourAgentAIOpsLabDetectionAgent:
    def __init__(
        self,
        namespace: str,
        service: str,
        metrics_duration_minutes: int,
        show_decisions: bool,
    ) -> None:
        self.policy = AIOpsLabDetectionPolicy(
            namespace=namespace,
            service=service,
            metrics_duration_minutes=metrics_duration_minutes,
        )
        self.show_decisions = show_decisions
        self.decision_history: list[dict[str, Any]] = []

    async def get_action(self, env_input: str) -> str:
        decision = self.policy.next_action(env_input)
        record = {
            "step": len(self.decision_history) + 1,
            "api_call": decision.api_call,
            "valid": decision.valid,
            "has_anomaly": decision.has_anomaly,
            "metadata": decision.metadata,
            "observation_excerpt": env_input[:1000],
        }
        self.decision_history.append(record)
        if self.show_decisions:
            print("== AI-MCMP Four-Agent AIOpsLab Decision ==")
            print(json.dumps(record, ensure_ascii=False, indent=2))
        return format_aiopslab_action(decision.api_call)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an AIOpsLab detection problem with the AI-MCMP 4-agent policy."
    )
    parser.add_argument(
        "--aiopslab-root",
        default="~/geonhae/external/AIOpsLab",
        help="Path to the cloned Microsoft AIOpsLab repository.",
    )
    parser.add_argument(
        "--problem-id",
        default="misconfig_app_hotel_res-detection-1",
        help="AIOpsLab problem id to run.",
    )
    parser.add_argument("--namespace", default="test-hotel-reservation")
    parser.add_argument("--service", default="geo")
    parser.add_argument("--metrics-duration-minutes", type=int, default=10)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument(
        "--kubeconfig",
        default="~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml",
    )
    parser.add_argument(
        "--results-dir",
        default="",
        help="Optional AIOpsLab session results directory.",
    )
    parser.add_argument(
        "--save-result-dir",
        default="runs",
        help="Directory where the automation report JSON is saved.",
    )
    parser.add_argument(
        "--no-openebs-kind-patch",
        action="store_true",
        help="Disable the kind/OpenEBS NDM readiness compatibility patch.",
    )
    parser.add_argument(
        "--quiet-decisions",
        action="store_true",
        help="Do not print each 4-agent decision during the run.",
    )
    return parser


async def run(args: argparse.Namespace) -> dict[str, Any]:
    aiopslab_root = Path(args.aiopslab_root).expanduser().resolve()
    kubeconfig = Path(args.kubeconfig).expanduser().resolve()
    if not aiopslab_root.exists():
        raise FileNotFoundError(f"AIOpsLab root not found: {aiopslab_root}")
    if not kubeconfig.exists():
        raise FileNotFoundError(f"kubeconfig not found: {kubeconfig}")

    os.environ["KUBECONFIG"] = str(kubeconfig)
    os.environ["PATH"] = f"{Path.home() / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
    sys.path.insert(0, str(aiopslab_root))
    os.chdir(aiopslab_root)

    if not args.no_openebs_kind_patch:
        _patch_openebs_wait_for_ready()

    from aiopslab.orchestrator import Orchestrator

    agent = FourAgentAIOpsLabDetectionAgent(
        namespace=args.namespace,
        service=args.service,
        metrics_duration_minutes=args.metrics_duration_minutes,
        show_decisions=not args.quiet_decisions,
    )
    orchestrator = Orchestrator(results_dir=args.results_dir or None)
    orchestrator.register_agent(agent, name="ai-mcmp-four-agent")

    started_at = datetime.now().isoformat(timespec="seconds")
    orchestrator.init_problem(args.problem_id)
    results = await orchestrator.start_problem(max_steps=args.max_steps)
    finished_at = datetime.now().isoformat(timespec="seconds")

    return {
        "command": "server-aiopslab-auto-detection",
        "problem_id": args.problem_id,
        "namespace": args.namespace,
        "service": args.service,
        "started_at": started_at,
        "finished_at": finished_at,
        "agent": "AI-MCMP four-agent detection policy",
        "decisions": agent.decision_history,
        "aiopslab_results": results,
    }


def _patch_openebs_wait_for_ready() -> None:
    from aiopslab.service.kubectl import KubeCtl
    from rich.console import Console

    original_wait_for_ready = KubeCtl.wait_for_ready

    def patched_wait_for_ready(
        self: Any,
        namespace: str,
        sleep: int = 2,
        max_wait: int = 300,
    ) -> None:
        if namespace != "openebs":
            return original_wait_for_ready(
                self,
                namespace=namespace,
                sleep=sleep,
                max_wait=max_wait,
            )

        console = Console()
        console.log(
            "[bold green]Waiting for required OpenEBS pods to be ready "
            "(kind NDM daemon pod ignored)..."
        )
        wait = 0
        while wait < max_wait:
            try:
                pod_list = self.list_pods(namespace)
                required_pods = [
                    pod
                    for pod in pod_list.items
                    if _is_required_openebs_pod(pod.metadata.name)
                ]
                if required_pods and all(
                    self._pod_is_ready_or_succeeded(pod) for pod in required_pods
                ):
                    console.log("[bold green]Required OpenEBS pods are ready.")
                    return
            except Exception as exc:
                console.log(f"[red]Error checking OpenEBS pod statuses: {exc}")
            time.sleep(sleep)
            wait += sleep
        raise Exception(
            "[red]Timeout: required OpenEBS pods did not reach Ready state "
            f"within {max_wait} seconds."
        )

    KubeCtl.wait_for_ready = patched_wait_for_ready


def _is_required_openebs_pod(name: str) -> bool:
    if not name.startswith("openebs-ndm-"):
        return True
    return any(
        component in name
        for component in ("cluster-exporter", "node-exporter", "operator")
    )


def save_report(args: argparse.Namespace, report: dict[str, Any]) -> Path:
    output_dir = Path(args.save_result_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"{timestamp}_aiopslab_auto_detection.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    args = build_parser().parse_args()
    report = asyncio.run(run(args))
    output_path = save_report(args, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"Saved report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
