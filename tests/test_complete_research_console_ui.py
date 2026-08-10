from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "ui" / "control_plane_static" / "index.html"
APP = ROOT / "ui" / "control_plane_static" / "app.js"
REFERENCE = ROOT / "ui" / "control_plane_static" / "reference-ui.js"
BULK = ROOT / "ui" / "control_plane_static" / "bulk-delete-ui.js"
POLISH = ROOT / "ui" / "control_plane_static" / "research-console-polish.js"
FLOW = ROOT / "ui" / "control_plane_static" / "stage-flow-ui.js"
STYLES = ROOT / "ui" / "control_plane_static" / "styles.css"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_aiopslab_three_tabs_are_functional_and_use_persisted_jobs():
    script = source(REFERENCE)
    for label in ("벤치마크 평가", "모델 성능 비교", "실행 이력"):
        assert label in script
    for tab in ("evaluation", "comparison", "history"):
        assert f'"{tab}"' in script or f"'{tab}'" in script
    assert "/api/benchmarks/aiopslab/jobs?limit=100" in script
    assert "renderAIOpsLabComparison" in script
    assert "renderAIOpsLabHistory" in script
    assert "비교 가능한 Detector가 1개입니다." in script
    assert "AI-MCMP Four-Agent" in script
    assert "fake" not in script.lower()


def test_aiopslab_history_has_filters_pagination_detail_events_and_artifacts():
    script = source(REFERENCE)
    for token in (
        "aiopslab-history-status",
        "aiopslab-history-query",
        "aiopslab-history-page-size",
        "aiopslab-history-prev",
        "aiopslab-history-next",
        "aiopslab-history-body",
        "aiopslab-job-detail",
    ):
        assert token in script
    assert "/api/benchmarks/aiopslab/jobs/${encodeURIComponent(" in script
    assert ".events" in script
    assert "artifact_urls" in script


def test_reference_ui_is_event_driven_and_has_no_mutation_observers():
    script = source(REFERENCE)
    assert "MutationObserver" not in script
    assert "bindAIOpsLabTabs" in script
    assert "addEventListener" in script


def test_data_first_visual_polish_is_loaded_without_fabricated_values():
    bulk = source(BULK)
    polish = source(POLISH)
    styles = source(STYLES)
    assert "/static/research-console-polish.js?v=2" in bulk
    assert "/api/benchmarks/aiopslab/jobs?limit=6" in polish
    assert "renderRecentBenchmarkResults" in polish
    assert "experiment-id-search" in polish
    assert "data-first" in polish
    assert "No broad MutationObserver" in polish
    assert "experiment-history-body" in polish
    assert 'document.readyState === "loading"' in polish
    assert ".aiopslab-tool-panel table" in styles
    assert ".detail-header" in styles
    lowered = polish.lower()
    for forbidden in ("0.842", "0.831", "0.863", "0.901", "14.32", "4.12"):
        assert forbidden not in lowered


def test_data_first_polish_keeps_aiopslab_metrics_to_supported_schema():
    polish = source(POLISH)
    for metric in ("Accuracy", "Average TTD", "Average Steps", "Average Reward"):
        assert metric in polish
    for unsupported in ("F1-Score", "Precision", "Recall", "AUC"):
        assert unsupported not in polish


def test_benchmark_and_result_styles_are_owned_by_the_shared_stylesheet():
    styles = source(STYLES)
    polish = source(POLISH)
    assert "injectPolishStyles();" not in polish
    for selector in (
        ".aiopslab-functional-tabs",
        ".aiopslab-tool-panel table",
        ".recent-benchmark-table",
        ".result-search-shell",
        ".detail-log-controls",
        ".performance-dashboard-grid",
    ):
        assert selector in styles
    assert "@media(max-width:1350px)" in styles


def test_performance_dashboard_uses_persisted_recovery_jobs():
    html = source(INDEX)
    app = source(APP)
    for marker in (
        "performance-dashboard-grid",
        "dashboard-scenario-body",
        "dashboard-action-body",
        "dashboard-controller-body",
    ):
        assert marker in html
    assert "function renderPerformanceDashboard" in app
    assert "state.jobs" in app
    assert 'value!=null&&value!==""' in app
    assert "recovery.recovery_success==null?undefined" in app
    for metric in ("성공률", "평균 MTTR", "평균 Team Reward"):
        assert metric in html


def test_recovery_selection_summary_tracks_async_scenario_updates():
    app = source(APP)
    reference = source(REFERENCE)
    assert 'new CustomEvent("aiops:selection-updated")' in app
    assert 'addEventListener("aiops:selection-updated", syncRecoveryReference)' in reference


def test_experiment_detail_tracks_the_rendered_job_report():
    app = source(APP)
    reference = source(REFERENCE)
    assert 'new CustomEvent("aiops:job-rendered")' in app
    assert 'addEventListener("aiops:job-rendered", syncDetailReference)' in reference


def test_recovery_flow_exposes_all_four_agents_in_eight_steps():
    bulk = source(BULK)
    flow = source(FLOW)
    assert "/static/stage-flow-ui.js?v=1" in bulk
    expected = (
        "장애 조건 확인",
        "Evidence 수집",
        "HA Agent 진단",
        "APP Agent 복구 Action 제안",
        "Infra Agent 검토",
        "Cost Agent 검토",
        "안전 명령 검증",
        "복구 실행 · 결과 확인",
        "Recovery Evaluator Agent",
    )
    for label in expected:
        assert label in flow
    assert "Infra · Cost 검토" not in flow
    assert "MutationObserver" not in flow
    assert "overview-stage-timeline" in flow
    assert "stage-timeline" in flow
    assert "mini-stage-list" in flow
    assert "Recovery Evaluator" in flow


def test_recovery_flow_agent_steps_match_agent_card_colors():
    flow = source(FLOW)
    for role_class in ("stage-ha", "stage-app", "stage-infra", "stage-cost"):
        assert role_class in flow
        assert f".reference-flow li.{role_class}" in flow
    for color_var in ("var(--blue)", "var(--green)", "var(--purple)", "var(--orange)"):
        assert color_var in flow
    assert 'style.id = "agent-stage-role-colors"' in flow


def test_overview_runtime_rendering_is_split_by_research_responsibility():
    script = source(APP)
    for function_name in (
        "renderOverviewContext",
        "renderOverviewStages",
        "renderOverviewAgents",
        "renderOverviewResult",
    ):
        assert f"function {function_name}" in script
    for status in ("queued", "running", "completed", "blocked", "failed", "cancelled"):
        assert status in script
    for fabricated in ("14.32", "4.12", "0.842", "0.901"):
        assert fabricated not in script
    assert "/api/connections" in script
    assert "post_execution_reviews" in script


def test_experiment_results_sync_filters_to_url_and_paginate():
    script = source(REFERENCE)
    for name in ("period", "scenario", "controller", "mode", "status", "q", "page", "page_size"):
        assert name in script
    assert "syncResultFiltersFromUrl" in script
    assert "syncResultFiltersToUrl" in script
    assert "applyExperimentPagination" in script
    assert "result-filter-reset" in script
    assert "result-pagination-prev" in script
    assert "result-pagination-next" in script
    assert "300" in script


def test_experiment_result_deletion_requires_confirmation_and_refreshes_history():
    app = source(APP)
    reference = source(REFERENCE)
    assert 'status.id="result-delete-status"' in app
    assert 'button.id="detail-delete-button"' in app
    assert "deleteExperimentResult" in app
    assert "window.confirm" in app
    assert "Job, 이벤트, 생성된 결과 파일이 영구적으로 삭제됩니다." in app
    assert 'method:"DELETE"' in app or 'method: "DELETE"' in app
    assert "/api/experiments/${encodeURIComponent(experimentId)}" in app
    assert "loadExperimentHistory" in app
    assert "aiops:history-updated" in app
    assert "실행 중인 실험은 삭제할 수 없습니다." in app
    assert "MutationObserver" not in reference


def test_bulk_experiment_result_deletion_reloads_after_success_headers_without_waiting_for_json():
    html = source(INDEX)
    script = source(BULK)
    assert "/static/bulk-delete-ui.js?v=2" in html
    assert "delete-all-experiments" in script
    assert "전체 삭제" in script
    assert "deleteAllExperimentResults" in script
    assert "실행 중인 실험은 삭제하지 않습니다" in script
    assert "window.confirm" in script
    delete_body = script.split("async function deleteAllExperimentResults", 1)[1].split("function ensureBulkDeleteControl", 1)[0]
    assert 'fetch("/api/experiments"' in delete_body
    assert 'method: "DELETE"' in delete_body
    assert "/api/experiments/${encodeURIComponent(" not in script
    assert "while (true)" not in script
    assert "for (const job" not in script
    assert "response.json()" not in delete_body.split("if (!response.ok)", 1)[0]
    assert "location.reload()" in script
    assert "MutationObserver" not in script


def test_experiment_detail_has_copy_download_rerun_url_tabs_logs_and_events():
    html = source(INDEX)
    script = source(REFERENCE)
    for tab in ("summary", "timeline", "agents", "evidence", "logs", "events"):
        assert f'data-detail-tab="{tab}"' in html
    for token in (
        "copyExperimentId",
        "prefillRerun",
        "syncDetailTabFromUrl",
        "syncDetailTabToUrl",
        "detail-log-search",
        "detail-log-level",
        "detail-log-autoscroll",
        "detail-event-payloads",
    ):
        assert token in script
    assert "navigator.clipboard" in script
    assert "detail_tab" in script
    assert "Real" in script
    assert "click()" in script


def test_existing_runtime_contracts_still_present():
    script = source(APP)
    assert 'api("/api/experiments",' in script
    assert "new EventSource(`/api/experiments/${state.experimentId}/events`)" in script
    assert "EXECUTE REAL EXPERIMENT" in script
    assert 'api("/api/benchmarks/aiopslab/jobs",' in script
    assert "EXECUTE REAL COMPARISON" in script


def test_recovery_reward_ui_uses_evaluator_team_reward_only():
    html = source(INDEX)
    app = source(APP)

    assert "evaluation.team_reward" in app
    assert "evaluatorAgentReward" in app
    report_metrics = app.split("function reportMetrics", 1)[1].split("function renderDetail", 1)[0]
    assert "agent_contributions" not in report_metrics
    assert "reduce((sum,item)=>sum+Number(item.reward||0),0)" not in app
    assert 'reward:evaluation&&evaluation.team_reward!=null?Number(evaluation.team_reward):null' in app
    assert "Team Reward" in html
    for marker in (
        "detail-team-reward",
        "detail-ha-reward",
        "detail-app-reward",
        "detail-infra-reward",
        "detail-cost-reward",
        "detail-outcome",
        "detail-efficiency",
        "detail-safety",
        "detail-evidence-quality",
        "detail-evaluator",
        "detail-rubric",
    ):
        assert marker in html


def test_legacy_reports_have_no_authoritative_reward():
    app = source(APP)
    assert "evaluationFor(report)" in app
    assert 'reward:evaluation&&evaluation.team_reward!=null?Number(evaluation.team_reward):null' in app
    assert "report.agent_contributions" not in app
