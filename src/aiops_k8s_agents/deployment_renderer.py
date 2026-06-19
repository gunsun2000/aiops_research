from __future__ import annotations

from typing import Any

from aiops_k8s_agents.inference_optimizer import InferenceDeploymentPlan

DEPLOYMENT_DRY_RUN_COMMAND = "kubectl apply -f - --dry-run=server"


def render_deployment_manifest(plan: InferenceDeploymentPlan) -> dict[str, Any]:
    """Render an inference deployment plan as a Kubernetes Deployment manifest."""

    if not plan.valid:
        raise ValueError("cannot render deployment manifest from an invalid plan")

    kubernetes = dict(plan.deployment_plan.get("kubernetes", {}))
    deployment = str(kubernetes.get("deployment", "")).strip()
    namespace = str(kubernetes.get("namespace", "")).strip()
    image = str(plan.deployment_plan.get("container_image", "")).strip()
    if not deployment or not namespace or not image:
        raise ValueError("deployment plan must include deployment, namespace, and image")

    labels = {"app": deployment}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "replicas": int(kubernetes.get("replicas", 1)),
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeSelector": dict(kubernetes.get("node_selector", {})),
                    "containers": [
                        {
                            "name": deployment,
                            "image": image,
                            "resources": dict(kubernetes.get("resources", {})),
                        }
                    ],
                },
            },
        },
    }
