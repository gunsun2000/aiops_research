from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui" / "control_plane_static" / "index.html"
APP_JS = ROOT / "ui" / "control_plane_static" / "app.js"
REFERENCE_JS = ROOT / "ui" / "control_plane_static" / "reference-ui.js"
POLISH_JS = ROOT / "ui" / "control_plane_static" / "research-console-polish.js"
STYLES_CSS = ROOT / "ui" / "control_plane_static" / "styles.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _compact(source: str) -> str:
    return "".join(source.split())


def test_console_has_five_primary_research_views():
    html = _source(INDEX_HTML)
    assert '<html lang="ko">' in html
    for view in ("overview", "experiment", "orchestration", "aiopslab", "analysis"):
        assert f'data-view="{view}"' in html
        assert f'data-view-panel="{view}"' in html
    assert "시스템 개요" in html
    assert "복구 실험" in html
    assert "AI Workload Orchestration" in html
    assert "AIOpsLab Benchmark" in html
    assert "실험 결과" in html
    assert "styles.css?v=37" in html
    assert "app.js?v=37" in html


def test_model_partition_workspace_preserves_upstream_approval_boundary():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    for element_id in (
        "partition-load-inference",
        "partition-load-training",
        "partition-plan-run",
        "partition-intake-details",
        "partition-strategy-details",
        "partition-candidates",
        "partition-selected-plan",
        "partition-execution-graph",
        "partition-validation",
        "partition-evaluation",
        "partition-handoff",
        "partition-feedback-form",
        "partition-history",
    ):
        assert f'id="{element_id}"' in html
    assert "현재 구현 범위" in html
    assert 'id="partition-mode-select"' not in html
    assert "/api/model-partition/plans" in script
    assert "/api/model-partition/strategies" in script
    assert "/feedback" in script
    assert "Estimated reward" in script


def test_orchestration_workspace_has_four_research_stages():
    index_html = _source(INDEX_HTML)

    for label in (
        "계획 입력 확인",
        "분할 기준 결정",
        "최종 분할안 확인",
        "스케줄러 전달",
    ):
        assert label in index_html


def test_orchestration_workspace_explains_its_input_decision_output_and_next_stage():
    index_html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert 'id="partition-purpose-flow"' in index_html
    for label in (
        "승인된 Coordination Plan",
        "Model Partition Orchestrator",
        "Partition Execution Plan",
        "Scheduling Agent",
        "실제 GPU 배치와 실행은 Scheduling Agent 이후 단계",
    ):
        assert label in index_html
    assert "지연시간·메모리 압력·통신량을 함께 비교한 결과" in script


def test_orchestration_workspace_keeps_primary_results_visible_and_research_metadata_collapsed():
    index_html = _source(INDEX_HTML)
    script = _source(APP_JS)

    for element_id in (
        "partition-intake-research-details",
        "partition-strategy-research-details",
        "partition-alternative-candidates",
        "partition-feedback-details",
        "partition-history-details",
    ):
        assert f'id="{element_id}"' in index_html
    assert index_html.count("실제 Runtime 결과가 아닙니다") == 1
    assert "alternativeCandidates=(plan.alternative_candidates||[])" in script
    assert "candidates=[selected" not in script


def test_orchestration_workspace_marks_predicted_results():
    index_html = _source(INDEX_HTML)

    assert "실행 전 예측" in index_html
    assert "실제 Runtime 결과가 아닙니다" in index_html


def test_orchestration_samples_are_loaded_from_the_examples_api():
    script = _source(APP_JS)

    assert "PARTITION_V2_SAMPLES" not in script
    assert 'api("/api/model-partition/examples")' in script
    assert "item.request.coordination_plan.plan_type===kind" in script


def test_orchestration_strategy_and_handoff_render_review_context_and_errors():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert "plan.assumptions" in script
    assert "plan.warnings" in script
    assert 'id="partition-handoff-error"' in html
    assert 'text("partition-handoff-error",error.message||String(error))' in script


def test_orchestration_strategy_renders_server_owned_contract_and_catalog_errors():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert 'id="partition-strategy-error"' in html
    for field in (
        "strategy.objective_weights",
        "strategy.allowed_split_boundary_rule",
        "strategy.forbidden_split_boundaries",
        "strategy.graph_requirements",
        "strategy.memory_rules",
    ):
        assert field in script
    assert "plan.objective_weights" not in script
    assert "partitionStrategyError" in script


def test_orchestration_keeps_sample_when_catalog_fails_and_clears_stale_handoff_errors():
    script = _source(APP_JS)

    assert 'text("partition-strategy-error",state.partitionStrategyError)' in script
    assert 'state.partitionStrategyError=error.message||String(error)' in script
    assert script.count('text("partition-handoff-error","")') >= 3


def test_orchestration_stage_tabs_support_roving_keyboard_navigation():
    script = _source(APP_JS)

    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in script
    assert 'button.tabIndex=active?0:-1' in script
    assert "activeButton.focus()" in script


def test_dynamic_console_scripts_use_fresh_cache_versions():
    html = _source(INDEX_HTML)
    bulk_script = _source(ROOT / "ui" / "control_plane_static" / "bulk-delete-ui.js")
    assert "reference-ui.js?v=4" in html
    assert "bulk-delete-ui.js?v=3" in html
    assert "research-console-polish.js?v=3" in bulk_script


def test_reference_images_define_the_page_structure():
    html = _source(INDEX_HTML)
    for marker in (
        "reference-overview",
        "recovery-stepper",
        "reference-recovery-setup",
        "aiopslab-reference-grid",
        "results-reference-grid",
        "detail-reference-layout",
    ):
        assert marker in html
    assert "최근 시나리오" in html
    assert "선택된 실험 요약" in html
    assert "벤치마크 평가" in html
    assert "결과 분포" in html
    assert "복구 전 / 후 Evidence" in html


def test_reference_console_has_semantic_page_actions_and_workspace_sections():
    html = _source(INDEX_HTML)
    assert '<header class="page-heading recovery-header">' in html
    assert 'class="recovery-main" aria-label="복구 실험 설정"' in html
    assert 'class="surface selected-summary" aria-label="선택된 실험 요약"' in html
    assert 'aria-label="실험 결과 필터"' in html
    assert 'aria-label="실험 상세 탭"' in html


def test_recovery_workspace_keeps_live_progress_and_links_to_detailed_results():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)
    assert 'id="run-experiment" class="primary-action"' in html
    assert 'id="recovery-header-run"' not in html
    for phase in ("design", "observe"):
        assert f'data-recovery-phase="{phase}"' in html
    assert "설계" in html
    assert "실행·관찰" in html
    assert 'data-recovery-phase="review"' not in html
    assert 'id="recovery-review-panel"' not in html
    assert "결과 검토" not in html
    for element_id in (
        "recovery-progress-summary",
        "recovery-progress-outcome",
        "recovery-progress-action",
        "recovery-progress-mttr",
        "recovery-progress-reward",
    ):
        assert f'id="{element_id}"' in html
    assert 'id="live-workflow"' in html
    assert 'class="recovery-phase-nav"' in html
    assert 'id="recovery-workspace"' in html
    assert 'data-recovery-phase="design"' in html
    assert "recovery-detail-disclosure" in script
    assert "dataset.recoveryPhase=phase" in script
    assert "function updateRecoveryPhase" in script
    assert "function focusRecoveryProgress" in script
    assert 'scrollIntoView({behavior:"smooth",block:"start"})' in script
    assert "function renderRecoveryCompletionSummary" in script
    assert "function renderRecoveryReview" not in script
    assert "function renderRecoveryReviewContext" not in script
    assert "실험 결과에서 상세 보기" in html
    assert "Role-based veto · 2 rounds" in script
    assert "function renderExperimentDirection" in script
    assert "function ensureExperimentDirection" in script
    assert "recovery-direction-bar" in script


def test_sidebar_exposes_runtime_connection_statuses():
    html = _source(INDEX_HTML)
    for connection in ("kubernetes", "prometheus", "chaos-mesh", "aiopslab", "autogen"):
        assert f'id="status-{connection}"' in html
        assert f'id="status-{connection}-label"' in html


def test_recovery_scenarios_are_separate_from_aiopslab():
    script = _compact(_source(APP_JS))
    assert "constRECOVERY_SCENARIOS" in script
    for scenario in ("cpu-stress", "memory-stress", "network-delay", "pod-kill"):
        assert f'"{scenario}"' in script
    assert 'id!=="aiopslab-hotel-reservation"' in script
    assert '(item.incident_source||"chaos_mesh")!=="aiopslab"' in script
    assert 'incident_source:"chaos_mesh"' in script
    assert 'benchmark_id:""' in script


def test_recovery_ui_has_eight_stage_workflow_and_safe_modes():
    html = _source(INDEX_HTML)
    assert html.count('id="stage-timeline"') == 1
    for stage_text in (
        "장애 조건 확인", "Evidence 수집", "HA Agent 진단", "복구 Action 제안",
        "Infra · Cost 검토", "안전 명령 검증", "복구 실행", "복구 결과 확인",
    ):
        assert stage_text in html
    for mode in ("mock", "dry-run", "real"):
        assert f'data-mode="{mode}"' in html
    assert "Mock" in html
    assert "DRY-RUN" in _source(APP_JS)
    assert "Dry-run 검증 완료" in _source(APP_JS)


def test_recovery_timeline_is_readable_and_status_coded():
    css = _source(STYLES_CSS)

    assert "counter-reset:stage" in css
    assert 'content:"✓"' in css
    assert ".recovery-stage-timeline li.active::before" in css
    assert ".recovery-stage-timeline li.failed::before" in css
    assert "position:absolute;left:50%;top:5px" in css
    assert "border-radius:50%" in css
    assert "position:absolute;left:calc(50% + 14px)" in css
    assert "@keyframes recovery-stage-spin" in css
    assert "animation:recovery-stage-spin" in css
    assert "@media (max-width: 1400px)" in css


def test_console_preserves_experiment_job_sse_cancel_and_real_gate():
    script = _source(APP_JS)
    assert 'api("/api/experiments",' in script
    assert "new EventSource(`/api/experiments/${state.experimentId}/events`)" in script
    assert "`/api/experiments/${state.experimentId}/cancel`" in script
    assert 'api("/api/experiments?limit=100")' in script
    assert "EXECUTE REAL EXPERIMENT" in script


def test_autogen_is_readiness_gated_and_model_only_used_for_autogen():
    html = _source(INDEX_HTML)
    script = _compact(_source(APP_JS))
    assert 'data-controller="autogen"' in html
    assert 'id="autogen-controller-state"' in html
    assert "autoButton.disabled=!autogen.ready" in script
    assert 'controller==="autogen"?$("model-input").value.trim():""' in script
    assert "controllerLabel(controller,model)" in script
    assert "DeterministicMutualSupervision" in script
    assert "AutoGenRound-Robin" in script
    assert "deterministic·" not in script


def test_console_has_four_agents_and_no_fake_precomputed_decisions():
    source = _source(INDEX_HTML) + _source(APP_JS)
    for agent in (
        "AIServiceHASupportAgent", "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent", "CostOptimizationAgent",
    ):
        assert agent in source
    assert "DEFAULT_DIAGNOSIS" not in source
    assert "DEFAULT_ACTIONS" not in source
    assert "실제 실행 결과의 Agent 판단 근거만 표시합니다." in source


def test_evidence_boundaries_do_not_mix_aiopslab_into_recovery():
    script = _compact(_source(APP_JS))
    assert '"ChaosMeshSimulation"' in script
    assert '"ChaosMesh"' in script
    assert 'return"SyntheticEvidenceProvider"' in script
    assert 'return"KubernetesSnapshot"' in script
    assert 'return"Kubernetes+Prometheus"' in script
    assert "AIOpsLab+Prometheus+Kubernetes" not in script


def test_aiopslab_has_its_own_benchmark_runtime_and_sse():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)
    assert 'data-view-panel="aiopslab"' in html
    for element_id in (
        "aiopslab-benchmark-select", "aiopslab-repetitions", "aiopslab-run",
        "aiopslab-cancel", "aiopslab-delete-current", "aiopslab-delete-all",
        "aiopslab-accuracy", "aiopslab-ttd",
        "aiopslab-steps", "aiopslab-reward", "aiopslab-scenario-list",
    ):
        assert f'id="{element_id}"' in html
    assert 'api("/api/benchmarks/aiopslab")' in script
    assert 'api("/api/benchmarks/aiopslab/jobs",' in script
    assert "deleteCurrentAIOpsLabJob" in script
    assert "deleteAllAIOpsLabJobs" in script
    assert 'api("/api/benchmarks/aiopslab/jobs",{method:"DELETE"})' in script
    assert "new EventSource(`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/events`)" in script
    assert "`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/cancel`" in script


def test_aiopslab_recent_results_have_individual_delete_actions():
    script = _source(POLISH_JS)
    assert "data-aiopslab-delete-job" in script
    assert "deleteAIOpsLabRow" in script
    assert 'method: "DELETE"' in script
    assert "aiops:aiopslab-jobs-updated" in script


def test_results_include_history_comparison_dashboard_and_mock_warning():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)
    for tab in ("history", "comparison", "dashboard"):
        assert f'data-result-tab="{tab}"' in html
        assert f'data-result-panel="{tab}"' in html
    assert 'id="synthetic-warning"' in html
    assert "합성 데이터 기반 결과입니다." in html
    assert 'id="experiment-history-body"' in html
    assert 'id="dashboard-donut"' in html
    assert 'api("/api/comparisons/recovery")' in script
    assert 'api("/api/comparisons/recovery/jobs",' in script
    assert "EXECUTE REAL COMPARISON" in script


def test_experiment_detail_has_six_research_tabs_and_artifacts():
    html = _source(INDEX_HTML)
    for tab in ("summary", "timeline", "agents", "evidence", "logs", "events"):
        assert f'data-detail-tab="{tab}"' in html
        assert f'data-detail-panel="{tab}"' in html
    assert 'id="experiment-artifacts"' in html
    assert 'id="allowlist-result"' in html
    assert 'id="validator-result"' in html
    assert 'id="cleanup-result"' in html
    assert 'id="detail-download-button"' in html
    assert 'id="detail-rerun-button"' in html


def test_styles_match_reference_shell_and_desktop_density():
    css = _compact(_source(STYLES_CSS))
    assert ".platform-shell" in css
    assert "grid-template-columns:232pxminmax(0,1fr)" in css
    assert ".platform-sidebar" in css
    assert ".reference-overview" in css
    assert ".recovery-step" in css
    assert ".scenario-grid" in css
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert ".aiopslab-reference-grid" in css
    assert ".results-reference-grid" in css
    assert ".dashboard-donut" in css
    assert ".detail-reference-layout" in css
    assert "@media(max-width:760px)" in css


def test_reference_shell_uses_stable_workspace_dimensions():
    css = _compact(_source(STYLES_CSS))
    assert "--sidebar-width:252px" in css
    assert "max-width:1560px" in css
    assert "grid-template-columns:var(--sidebar-width)minmax(0,1fr)" in css
    assert "@media(max-width:760px)" in css
    assert "position:sticky" in css
    assert "overflow-wrap:anywhere" in css


def test_reference_ui_script_builds_catalog_cards_donut_and_detail_actions():
    script = _source(REFERENCE_JS)
    assert "aiopslab-scenario-list" in script
    assert "dashboard-donut" in script
    assert "detail-download-button" in script
    assert "detail-rerun-button" in script
