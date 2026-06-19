from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
from aiops_k8s_agents.inference_optimizer import InferencePlacementDecision
from aiops_k8s_agents.models import AlertEvent
from aiops_k8s_agents.service_operations import AIServiceOperationsPipeline


def test_service_operations_prepare_service_connects_llm_placement_and_manifest():
    pipeline = AIServiceOperationsPipeline(mode=ExecutionMode.MOCK)

    report = pipeline.prepare_service(
        workload_id="llm-chat-inference",
        llm_policy="quality_first",
    )

    assert report["selected_llm"] == "gpt-5.5"
    assert report["selected_resource"] == "gpu-vm-l4"
    assert report["deployment_plan"]["kubernetes"]["deployment"] == (
        "llm-chat-inference"
    )
    assert report["deployment_manifest"]["kind"] == "Deployment"
    assert report["deployment_dry_run"]["valid"] is True
    assert report["deployment_dry_run"]["command"] == (
        "kubectl apply -f - --dry-run=server"
    )
    assert report["agent_reviews"]["application"]["approved"] is True
    assert report["agent_reviews"]["infrastructure"]["approved"] is True
    assert report["agent_reviews"]["cost"]["approved"] is True


def test_service_operations_can_create_autogen_client_from_selected_llm():
    pipeline = AIServiceOperationsPipeline()

    client = pipeline.create_selected_autogen_model_client(
        workload_id="llm-chat-inference",
        llm_policy="quality_first",
        model_client_factory=lambda model: {"model": model},
    )

    assert client == {"model": "gpt-5.5"}


def test_service_operations_run_combines_preparation_and_recovery_readiness():
    pipeline = AIServiceOperationsPipeline(
        mode=ExecutionMode.MOCK,
        guard_backend=ExecutionBackend.GO,
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=95,
        threshold=80,
        message="paymentservice CPU high",
    )

    report = pipeline.run(
        workload_id="llm-chat-inference",
        llm_policy="quality_first",
        alert=alert,
    )

    assert report["command"] == "run-service-operations"
    assert report["selected_llm"] == "gpt-5.5"
    assert report["selected_resource"] == "gpu-vm-l4"
    assert report["recovery_pipeline_ready"] is True
    assert report["guard_backend"] == "go"
    assert report["recovery"]["metadata"]["coordinator"] == "AI-MCMP"


def test_infra_agent_rejects_invalid_cpu_gpu_placement():
    decision = InferencePlacementDecision(
        valid=False,
        workload="impossible-llm",
        selected_resource="",
        action="",
        score=0.0,
        latency_ms=0.0,
        throughput_rps=0.0,
        cost_per_hour=0.0,
        slo_satisfied=False,
        reason="no eligible CPU/GPU VM resource satisfied the workload constraints",
        rejected_resources={"cpu-only": "accelerator required"},
        ranked_candidates=[],
    )

    review = AISemiconductorInfraOpsAgent().review_operation(
        placement_decision=decision
    )

    assert review.approved is False
    assert review.action == "infra_placement_rejected"
