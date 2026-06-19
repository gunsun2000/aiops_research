from aiops_k8s_agents.deployment_renderer import render_deployment_manifest
from aiops_k8s_agents.inference_optimizer import (
    build_inference_deployment_plan,
    load_inference_optimization_config,
)


def test_inference_deployment_plan_renders_kubernetes_deployment_manifest():
    config = load_inference_optimization_config("config/inference_optimization.json")
    plan = build_inference_deployment_plan(config, "llm-chat-inference")

    manifest = render_deployment_manifest(plan)

    assert manifest["apiVersion"] == "apps/v1"
    assert manifest["kind"] == "Deployment"
    assert manifest["metadata"] == {
        "name": "llm-chat-inference",
        "namespace": "ai-inference",
        "labels": {"app": "llm-chat-inference"},
    }
    assert manifest["spec"]["replicas"] == 1
    assert manifest["spec"]["template"]["spec"]["nodeSelector"] == {
        "aiops.resource/accelerator": "gpu",
        "aiops.resource/gpu-class": "l4",
    }
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["name"] == "llm-chat-inference"
    assert container["image"] == "ghcr.io/gunsun2000/aiops-llm-chat:latest"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
