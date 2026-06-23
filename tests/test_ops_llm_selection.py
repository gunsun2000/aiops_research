import pytest

from aiops_k8s_agents.ops_llm_selection import (
    OpsLLMSelectionError,
    load_ops_llm_benchmark_config,
    select_ops_llm,
)


def test_quality_first_policy_selects_gpt_55():
    config = load_ops_llm_benchmark_config("config/ops_llm_benchmark.json")

    result = select_ops_llm(config, policy_name="quality_first")

    assert result.selected_model == "gpt-5.5"
    assert result.policy == "quality_first"
    assert result.ranking[0]["model"] == "gpt-5.5"
    assert result.ranking[0]["score"] > result.ranking[1]["score"]
    assert result.ranking[0]["metrics"]["accuracy"] == 1.0
    assert result.ranking[0]["metrics"]["action_validity"] == 1.0


def test_ops_llm_benchmark_exposes_data_source_metadata():
    config = load_ops_llm_benchmark_config("config/ops_llm_benchmark.json")

    assert config.metadata.data_source == "manual_summary"
    assert config.metadata.is_synthetic is False
    assert config.metadata.is_standardized_benchmark is False
    assert config.metadata.measurement_level == (
        "manual_summary_from_available_project_runs"
    )
    assert config.metadata.requires_regeneration_for_final_report is True
    assert config.metadata.benchmark_run_id
    assert "manually summarized" in " ".join(config.metadata.notes).lower()


def test_cost_first_policy_selects_lightweight_model():
    config = load_ops_llm_benchmark_config("config/ops_llm_benchmark.json")

    result = select_ops_llm(config, policy_name="cost_first")

    assert result.selected_model == "gpt-4o-mini"
    assert result.policy == "cost_first"
    assert result.ranking[0]["metrics"]["cost"] == 1.0


def test_unknown_policy_is_rejected():
    config = load_ops_llm_benchmark_config("config/ops_llm_benchmark.json")

    with pytest.raises(OpsLLMSelectionError, match="unknown LLM selection policy"):
        select_ops_llm(config, policy_name="missing")
