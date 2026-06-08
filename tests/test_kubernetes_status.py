import json

from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot


def test_collect_kubernetes_snapshot_summarizes_deployment_and_pods():
    def fake_runner(argv):
        if argv[:3] == ["kubectl", "get", "deployment"]:
            return (
                0,
                json.dumps(
                    {
                        "metadata": {"name": "paymentservice"},
                        "spec": {"replicas": 3},
                        "status": {
                            "readyReplicas": 3,
                            "availableReplicas": 3,
                            "updatedReplicas": 3,
                        },
                    }
                ),
                "",
            )
        return (
            0,
            json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "paymentservice-a"},
                            "status": {
                                "phase": "Running",
                                "containerStatuses": [
                                    {"ready": True, "restartCount": 0}
                                ],
                            },
                        },
                        {
                            "metadata": {"name": "paymentservice-b"},
                            "status": {
                                "phase": "Running",
                                "containerStatuses": [
                                    {"ready": True, "restartCount": 1}
                                ],
                            },
                        },
                    ]
                }
            ),
            "",
        )

    snapshot = collect_kubernetes_snapshot(
        "online-boutique",
        "paymentservice",
        runner=fake_runner,
    )

    assert snapshot["deployment_status"]["ready_replicas"] == 3
    assert snapshot["pods"]["count"] == 2
    assert snapshot["pods"]["running"] == 2
    assert snapshot["pods"]["items"][1]["restarts"] == 1


def test_collect_kubernetes_snapshot_keeps_kubectl_errors_in_report():
    def fake_runner(_argv):
        return 1, "", "forbidden"

    snapshot = collect_kubernetes_snapshot(
        "online-boutique",
        "paymentservice",
        runner=fake_runner,
    )

    assert snapshot["deployment_status"]["ok"] is False
    assert snapshot["deployment_status"]["stderr"] == "forbidden"
    assert snapshot["pods"]["ok"] is False
