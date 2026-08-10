import json

from aiops_k8s_agents.action_policy import (
    ACTION_KINDS,
    ContextualBanditPolicy,
    PolicyContext,
    PolicySample,
    load_policy_samples,
)


def _record(
    scenario: str,
    action: str,
    reward: float,
    *,
    safety_valid: bool = True,
    measurement_valid: bool = True,
) -> dict:
    return {
        "scenario": scenario,
        "metric": "cpu" if scenario == "cpu-stress" else "memory",
        "cause": "cpu_saturation" if scenario == "cpu-stress" else "memory_saturation",
        "action": {
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "kind": action,
            "replicas": 3 if action == "scale_out" else None,
        },
        "observed_reward": reward,
        "recovery_success": reward > 0.5,
        "safety_valid": safety_valid,
        "measurement_valid": measurement_valid,
    }


def test_policy_sample_normalizes_existing_recovery_outcome_record():
    sample = PolicySample.from_record(_record("cpu-stress", "scale_out", 0.8))

    assert sample.context.scenario == "cpu-stress"
    assert sample.context.cause == "cpu_saturation"
    assert sample.action == "scale_out"
    assert sample.observed_reward == 0.8
    assert sample.eligible is True


def test_baseline_policy_preserves_registered_cause_preference():
    policy = ContextualBanditPolicy(mode="baseline")

    recommendation = policy.recommend(
        PolicyContext(
            scenario="cpu-stress",
            metric="cpu",
            cause="cpu_saturation",
            severity="critical",
        )
    )

    assert recommendation.selected_action == "scale_out"
    assert recommendation.policy_mode == "baseline"
    assert {row["action"] for row in recommendation.ranking} == set(ACTION_KINDS)


def test_learned_policy_ranks_action_by_contextual_observed_reward():
    policy = ContextualBanditPolicy(mode="learned")
    policy.fit(
        [
            PolicySample.from_record(_record("cpu-stress", "scale_out", 0.90)),
            PolicySample.from_record(_record("cpu-stress", "scale_out", 0.80)),
            PolicySample.from_record(_record("cpu-stress", "observe_only", 0.20)),
            PolicySample.from_record(_record("cpu-stress", "rollout_restart", 0.40)),
        ]
    )

    recommendation = policy.recommend(
        PolicyContext("cpu-stress", "cpu", "cpu_saturation", "critical")
    )

    assert recommendation.selected_action == "scale_out"
    assert recommendation.training_samples == 4
    assert recommendation.fallback_reason == ""
    assert recommendation.ranking[0]["mean_reward"] == 0.85


def test_learned_policy_ignores_unsafe_samples_and_falls_back_without_data():
    policy = ContextualBanditPolicy(mode="learned")
    policy.fit(
        [
            PolicySample.from_record(
                _record(
                    "cpu-stress",
                    "scale_out",
                    1.0,
                    safety_valid=False,
                )
            )
        ]
    )

    recommendation = policy.recommend(
        PolicyContext("cpu-stress", "cpu", "cpu_saturation", "critical")
    )

    assert recommendation.selected_action == "scale_out"
    assert recommendation.training_samples == 0
    assert recommendation.fallback_reason == "no eligible training samples"


def test_load_policy_samples_reads_jsonl(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                _record("cpu-stress", "scale_out", 0.8),
                _record("cpu-stress", "observe_only", 0.2),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    samples = load_policy_samples(path)

    assert len(samples) == 2
    assert samples[0].action == "scale_out"
