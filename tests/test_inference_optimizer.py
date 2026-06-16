from aiops_k8s_agents.inference_optimizer import (
    load_inference_optimization_config,
    recommend_inference_placement,
)


def test_gpu_required_llm_workload_selects_gpu_vm():
    config = load_inference_optimization_config(
        "config/inference_optimization.json"
    )

    decision = recommend_inference_placement(config, "llm-chat-inference")

    assert decision.valid is True
    assert decision.selected_resource == "gpu-vm-l4"
    assert decision.action == "deploy_on_gpu_vm"
    assert decision.slo_satisfied is True
    assert decision.rejected_resources["cpu-vm-standard"].startswith(
        "accelerator required"
    )


def test_lightweight_text_workload_prefers_cpu_vm_when_slo_is_met():
    config = load_inference_optimization_config(
        "config/inference_optimization.json"
    )

    decision = recommend_inference_placement(config, "text-classifier")

    assert decision.valid is True
    assert decision.selected_resource == "cpu-vm-standard"
    assert decision.action == "deploy_on_cpu_vm"
    assert decision.cost_per_hour == 0.45


def test_optimizer_reports_no_candidate_when_constraints_cannot_be_met(tmp_path):
    config_path = tmp_path / "inference.json"
    config_path.write_text(
        """
{
  "version": "1",
  "weights": {"latency": 0.35, "throughput": 0.30, "cost": 0.20, "capacity": 0.15},
  "resources": [
    {
      "id": "cpu-only",
      "accelerator": "cpu",
      "cpu_cores": 8,
      "memory_gb": 32,
      "gpu_memory_gb": 0,
      "expected_latency_ms": 500,
      "expected_throughput_rps": 5,
      "cost_per_hour": 0.2,
      "available_replicas": 1,
      "supported_model_types": ["text-classification"]
    }
  ],
  "workloads": [
    {
      "id": "impossible-llm",
      "model_type": "llm",
      "requires_accelerator": true,
      "estimated_vram_gb": 16,
      "latency_slo_ms": 100,
      "min_throughput_rps": 50,
      "batch_size": 8
    }
  ]
}
""",
        encoding="utf-8",
    )
    config = load_inference_optimization_config(config_path)

    decision = recommend_inference_placement(config, "impossible-llm")

    assert decision.valid is False
    assert decision.selected_resource == ""
    assert "cpu-only" in decision.rejected_resources
