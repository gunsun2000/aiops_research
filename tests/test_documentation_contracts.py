from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ranker_docs_keep_scheduler_and_learning_scope_explicit():
    guide = (
        ROOT / "docs" / "experiments" / "partition_ranker_experiment_guide.md"
    ).read_text(encoding="utf-8")

    assert "Scheduling Agent는 외부 구성요소" in guide
    assert "observed" in guide
    assert "predicted·mock·dry-run 결과는 Real Runtime 성능 근거로 사용하지 않는다" in guide
    assert "--selection-mode shadow" in guide
    assert "--selection-mode learned_guarded" in guide


def test_ranker_docs_preserve_authoritative_safety_boundaries():
    design = (
        ROOT / "docs" / "design" / "model_partition_orchestrator_agent_design.md"
    ).read_text(encoding="utf-8")

    assert "Deterministic Candidate Generator" in design
    assert "AI Ranker는 Hard Constraint를 통과한 후보만 순위화" in design
    assert "PartitionPlanValidator" in design
    assert "Baseline 선택" in design
    assert "AI 추천" in design
    assert "최종 선택" in design


def test_ranker_execution_guide_uses_current_cli_contract():
    guide = (ROOT / "docs" / "submission" / "execution_code_guide.md").read_text(
        encoding="utf-8"
    )

    for command in (
        "build-partition-ranking-dataset",
        "train-partition-ranker",
        "evaluate-partition-ranker",
    ):
        assert command in guide
    assert "--artifact-signing-key-file" in guide
    assert 'python -m pip install -e ".[ml]"' in guide


def test_readme_links_to_partition_ranker_research_guides():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "partition_ranker_experiment_guide.md" in readme
    assert "model_partition_orchestrator_agent_design.md" in readme
    assert "learned_guarded" in readme
