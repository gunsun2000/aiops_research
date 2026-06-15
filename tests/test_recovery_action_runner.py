import json
from pathlib import Path

import pytest

from aiops_k8s_agents.recovery_runner import (
    MetricDirection,
    RecoveryExperimentRuntime,
    build_treatment_matrix,
    load_recovery_experiment_config,
    metric_improvement,
    resolve_metric_query,
    run_recovery_matrix,
    run_recovery_treatment,
)


CONFIG_PATH = Path("config/recovery_action_experiments.json")


def test_real_pilot_matrix_has_four_faults_three_actions_and_no_cpu_95_alert():
    config = load_recovery_experiment_config(CONFIG_PATH)
    matrix = build_treatment_matrix(config, repetitions=1)
    serialized = json.dumps(
        json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
        ensure_ascii=False,
    ).lower()

    assert len(config.scenarios) == 4
    assert set(config.actions) == {
        "observe_only",
        "rollout_restart",
        "scale_out",
    }
    assert len(matrix) == 12
    assert config.recovery_timeout_seconds == 150
    assert "cpu 95" not in serialized
    assert '"value": 95' not in serialized

    pod_kill = next(item for item in config.scenarios if item.id == "pod-kill")
    assert pod_kill.evidence_source == "pod_replacement"

    cpu = next(item for item in config.scenarios if item.id == "cpu-stress")
    assert "[1m]" in (cpu.query or "")

    memory = next(item for item in config.scenarios if item.id == "memory-stress")
    assert memory.fault_threshold == 50_000_000
    assert memory.recovery_threshold == 50_000_000
    assert 'size: "80MB"' in Path(memory.chaos_manifest).read_text(
        encoding="utf-8"
    )


def test_network_delay_requires_real_latency_evidence(monkeypatch):
    config = load_recovery_experiment_config(CONFIG_PATH)
    scenario = next(item for item in config.scenarios if item.id == "network-delay")
    monkeypatch.delenv("NETWORK_LATENCY_QUERY", raising=False)

    with pytest.raises(ValueError, match="NETWORK_LATENCY_QUERY"):
        resolve_metric_query(scenario)


def test_pod_kill_detects_replacement_uid_without_prometheus_query():
    config = load_recovery_experiment_config(CONFIG_PATH)
    treatment = next(
        item
        for item in build_treatment_matrix(config, repetitions=1)
        if item.scenario.id == "pod-kill"
        and item.action.value == "observe_only"
    )
    snapshots = iter(
        [
            (1, 1, ["old-uid"]),
            (1, 1, ["old-uid"]),
            (1, 1, ["new-uid"]),
            (1, 1, ["new-uid"]),
            (1, 1, ["new-uid"]),
        ]
    )

    def snapshot(_namespace: str, _deployment: str):
        desired, available, uids = next(snapshots)
        return {
            "deployment_status": {
                "ok": True,
                "desired_replicas": desired,
                "available_replicas": available,
            },
            "pods": {
                "ok": True,
                "count": len(uids),
                "running": available,
                "items": [
                    {
                        "name": f"paymentservice-{index}",
                        "uid": uid,
                        "phase": "Running",
                        "ready": "1/1",
                        "restarts": 0,
                    }
                    for index, uid in enumerate(uids)
                ],
            },
        }

    runtime = RecoveryExperimentRuntime(
        kubectl=lambda _argv: (0, "ok", ""),
        query_metric=lambda _url, _query: pytest.fail(
            "pod-kill evidence must come from Kubernetes availability"
        ),
        snapshot=snapshot,
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 1.0, 2.0, 3.0, 4.0]).__next__,
    )

    record = run_recovery_treatment(
        treatment=treatment,
        config=config,
        mode="real",
        prometheus_url="http://127.0.0.1:9091",
        runtime=runtime,
    )

    assert record["measurement_valid"] is True
    assert record["metric_at_fault"] == 0.0
    assert record["metric_after_action"] == 1.0
    assert record["fault"]["pods"]["items"][0]["uid"] == "new-uid"


def test_pod_kill_scale_out_waits_until_all_desired_replicas_are_available():
    config = load_recovery_experiment_config(CONFIG_PATH)
    treatment = next(
        item
        for item in build_treatment_matrix(config, repetitions=1)
        if item.scenario.id == "pod-kill"
        and item.action.value == "scale_out"
    )
    snapshots = iter(
        [
            (1, 1, ["old-uid"]),
            (1, 1, ["new-uid"]),
            (3, 1, ["new-uid", "scale-a", "scale-b"]),
            (3, 3, ["new-uid", "scale-a", "scale-b"]),
            (3, 3, ["new-uid", "scale-a", "scale-b"]),
        ]
    )

    def snapshot(_namespace: str, _deployment: str):
        desired, available, uids = next(snapshots)
        return {
            "deployment_status": {
                "ok": True,
                "desired_replicas": desired,
                "available_replicas": available,
            },
            "pods": {
                "ok": True,
                "count": len(uids),
                "running": available,
                "items": [
                    {
                        "name": f"paymentservice-{index}",
                        "uid": uid,
                        "phase": "Running",
                        "ready": "1/1" if index < available else "0/1",
                        "restarts": 0,
                    }
                    for index, uid in enumerate(uids)
                ],
            },
        }

    runtime = RecoveryExperimentRuntime(
        kubectl=lambda _argv: (0, "ok", ""),
        query_metric=lambda _url, _query: pytest.fail(
            "pod-kill evidence must come from Kubernetes state"
        ),
        snapshot=snapshot,
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0]).__next__,
    )

    record = run_recovery_treatment(
        treatment=treatment,
        config=config,
        mode="real",
        prometheus_url="http://127.0.0.1:9091",
        runtime=runtime,
    )

    assert record["measurement_valid"] is True
    assert record["metric_after_action"] == 1.0
    assert record["availability_recovery"] == 1.0
    assert record["replica_delta"] == 2


def test_network_delay_rejects_prometheus_up_as_latency_evidence(tmp_path):
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    network = next(item for item in data["scenarios"] if item["id"] == "network-delay")
    network.pop("query_env", None)
    network["query"] = "max(up)"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="latency evidence"):
        load_recovery_experiment_config(invalid_path)


def test_metric_improvement_respects_high_and_low_bad_directions():
    assert metric_improvement(100.0, 20.0, MetricDirection.HIGH) == 0.8
    assert metric_improvement(0.0, 1.0, MetricDirection.LOW) == 1.0
    assert metric_improvement(20.0, 100.0, MetricDirection.HIGH) == 0.0


def test_main_matrix_expands_to_thirty_six_independent_treatments():
    config = load_recovery_experiment_config(CONFIG_PATH)
    matrix = build_treatment_matrix(config, repetitions=3)

    assert len(matrix) == 36
    assert len({item.treatment_id for item in matrix}) == 36


def test_real_treatment_applies_fault_executes_bounded_action_and_always_cleans_up():
    config = load_recovery_experiment_config(CONFIG_PATH)
    treatment = next(
        item
        for item in build_treatment_matrix(config, repetitions=1)
        if item.scenario.id == "cpu-stress" and item.action.value == "scale_out"
    )
    commands: list[list[str]] = []
    metric_values = iter([0.1, 1.0, 0.1])

    def kubectl(argv: list[str]):
        commands.append(argv)
        return 0, "ok", ""

    def snapshot(_namespace: str, _deployment: str):
        desired = 3 if any("--replicas=3" in part for cmd in commands for part in cmd) else 1
        return {
            "deployment_status": {
                "ok": True,
                "desired_replicas": desired,
                "available_replicas": desired,
            },
            "pods": {"ok": True, "count": desired, "running": desired, "items": []},
        }

    runtime = RecoveryExperimentRuntime(
        kubectl=kubectl,
        query_metric=lambda _url, _query: next(metric_values),
        snapshot=snapshot,
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 1.0, 2.0, 3.0, 4.0]).__next__,
    )

    record = run_recovery_treatment(
        treatment=treatment,
        config=config,
        mode="real",
        prometheus_url="http://127.0.0.1:9090",
        runtime=runtime,
        environ={"NETWORK_LATENCY_QUERY": "histogram_quantile(0.95, rate(x[1m]))"},
    )

    assert record["measurement_valid"] is True
    assert record["safety_valid"] is True
    assert record["recovery_success"] is True
    assert record["started_at"]
    assert record["finished_at"]
    assert record["action"]["kind"] == "scale_out"
    assert record["metric_improvement"] == 0.9
    assert ["kubectl", "apply", "-f", treatment.scenario.chaos_manifest] in commands
    assert any(command[:4] == ["kubectl", "scale", "deployment", "paymentservice"] for command in commands)
    assert [
        "kubectl",
        "delete",
        "-f",
        treatment.scenario.chaos_manifest,
        "--ignore-not-found",
    ] in commands
    assert commands[-2][:4] == ["kubectl", "scale", "deployment", "paymentservice"]


def test_measurement_failure_is_recorded_and_fault_is_still_cleaned_up():
    config = load_recovery_experiment_config(CONFIG_PATH)
    treatment = next(
        item
        for item in build_treatment_matrix(config, repetitions=1)
        if item.scenario.id == "memory-stress"
        and item.action.value == "observe_only"
    )
    commands: list[list[str]] = []

    def kubectl(argv: list[str]):
        commands.append(argv)
        return 0, "ok", ""

    runtime = RecoveryExperimentRuntime(
        kubectl=kubectl,
        query_metric=lambda _url, _query: (_ for _ in ()).throw(
            ValueError("no Prometheus sample")
        ),
        snapshot=lambda _namespace, _deployment: {
            "deployment_status": {
                "ok": True,
                "desired_replicas": 1,
                "available_replicas": 1,
            },
            "pods": {"ok": True, "count": 1, "running": 1, "items": []},
        },
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 100.0, 101.0]).__next__,
    )

    record = run_recovery_treatment(
        treatment=treatment,
        config=config,
        mode="real",
        prometheus_url="http://127.0.0.1:9090",
        runtime=runtime,
    )

    assert record["measurement_valid"] is False
    assert record["recovery_success"] is False
    assert "no Prometheus sample" in record["error"]
    assert [
        "kubectl",
        "delete",
        "-f",
        treatment.scenario.chaos_manifest,
        "--ignore-not-found",
    ] in commands


def test_matrix_writes_one_jsonl_record_per_treatment(tmp_path):
    config = load_recovery_experiment_config(CONFIG_PATH)
    output_path = tmp_path / "outcomes.jsonl"

    def fake_treatment_runner(**kwargs):
        treatment = kwargs["treatment"]
        return {
            "treatment_id": treatment.treatment_id,
            "scenario": treatment.scenario.id,
            "repetition": treatment.repetition,
            "action": {
                "namespace": treatment.scenario.namespace,
                "deployment": treatment.scenario.deployment,
                "kind": treatment.action.value,
                "replicas": 3 if treatment.action.value == "scale_out" else None,
                "reason": "test",
            },
            "recovery_success": True,
            "availability_recovery": 1.0,
            "metric_improvement": 0.5,
            "recovery_seconds": 10.0,
            "replica_delta": 0,
            "command_count": 0,
            "safety_valid": True,
            "measurement_valid": True,
        }

    summary = run_recovery_matrix(
        config=config,
        repetitions=1,
        mode="real",
        prometheus_url="http://127.0.0.1:9090",
        output_path=output_path,
        treatment_runner=fake_treatment_runner,
        environ={"NETWORK_LATENCY_QUERY": "histogram_quantile(0.95, rate(x[1m]))"},
    )
    records = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]

    assert summary["total_treatments"] == 12
    assert summary["valid_measurements"] == 12
    assert len(records) == 12
    assert len({record["treatment_id"] for record in records}) == 12


def test_matrix_preflight_rejects_missing_network_latency_query(tmp_path):
    config = load_recovery_experiment_config(CONFIG_PATH)

    with pytest.raises(ValueError, match="NETWORK_LATENCY_QUERY"):
        run_recovery_matrix(
            config=config,
            repetitions=1,
            mode="real",
            prometheus_url="http://127.0.0.1:9090",
            output_path=tmp_path / "outcomes.jsonl",
            treatment_runner=lambda **_kwargs: pytest.fail(
                "treatments must not start before preflight passes"
            ),
            environ={},
        )
