from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui" / "control_plane_static" / "index.html"
APP_JS = ROOT / "ui" / "control_plane_static" / "app.js"
STYLES_CSS = ROOT / "ui" / "control_plane_static" / "styles.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_console_has_one_accessible_research_workspace():
    source = _source(INDEX_HTML)

    assert '<html lang="ko">' in source
    assert 'id="experiment-controls"' in source
    assert 'id="live-workflow"' in source
    assert 'id="decision-inspector"' in source
    assert 'id="research-results"' in source
    assert "4-Agent AIOps 연구 운영 콘솔" in source
    assert "새 복구 실험" not in source
    assert "styles.css?v=19" in source
    assert "app.js?v=19" in source


def test_console_has_three_primary_views_and_preserves_research_subviews():
    source = _source(INDEX_HTML)

    assert 'id="platform-nav"' in source
    for view_name in ("overview", "experiment", "analysis"):
        assert f'data-view="{view_name}"' in source
    assert 'data-view="aiopslab"' not in source

    for subview_name in ("agents", "observability", "history"):
        assert f'data-view="{subview_name}"' not in source
        assert f'data-view-link="{subview_name}"' in source

    for view_name in (
        "overview", "experiment", "agents", "observability",
        "analysis", "history",
    ):
        assert f'data-view-panel="{view_name}"' in source
    assert 'data-view-panel="aiopslab"' not in source

    for context_id in (
        "global-experiment-id",
        "global-scenario",
        "global-controller",
        "global-stage",
    ):
        assert f'id="{context_id}"' in source

    assert source.count('id="recovery-comparison-panel"') == 1
    assert 'styles.css?v=19' in source
    assert 'app.js?v=19' in source


def test_console_navigation_preserves_jobs_and_renders_shared_context():
    source = _source(APP_JS)

    assert "function selectPlatformView(viewName" in source
    assert 'document.querySelectorAll("[data-view]")' in source
    assert 'document.querySelectorAll("[data-view-panel]")' in source
    assert "PRIMARY_VIEW_BY_PANEL" in source
    assert "window.location.hash" in source
    assert 'window.addEventListener("hashchange"' in source
    assert "function renderGlobalContext(job)" in source
    for context_id in (
        "global-experiment-id",
        "global-scenario",
        "global-controller",
        "global-stage",
    ):
        assert f'"{context_id}"' in source


def test_console_offers_all_registered_fault_scenarios_and_safe_modes():
    source = _source(INDEX_HTML) + _source(APP_JS)

    for scenario_id in (
        "pod-kill",
        "cpu-stress",
        "memory-stress",
        "network-delay",
        "aiopslab-hotel-reservation",
    ):
        assert scenario_id in source
    for mode in ("mock", "dry-run", "real"):
        assert f'data-mode="{mode}"' in source


def test_console_connects_create_stream_cancel_and_restore_job_apis():
    source = _source(APP_JS)

    assert 'api("/api/experiments",' in source
    assert "new EventSource" in source
    assert "`/api/experiments/${state.experimentId}/events`" in source
    assert "`/api/experiments/${state.experimentId}/cancel`" in source
    assert 'api("/api/experiments?limit=20")' in source
    assert 'real_confirmation: "EXECUTE REAL EXPERIMENT"' in source


def test_console_exposes_four_agents_without_fake_precomputed_decisions():
    source = _source(INDEX_HTML) + _source(APP_JS)

    for agent_name in (
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    ):
        assert agent_name in source
    assert "DEFAULT_DIAGNOSIS" not in source
    assert "DEFAULT_ACTIONS" not in source
    assert "실험 Evidence 수집 후 표시" in source


def test_console_separates_mock_dry_run_and_real_evidence_boundaries():
    source = _source(APP_JS)

    assert "합성 Evidence" in source
    assert "명령 검증" in source
    assert "실제 Kubernetes" in source
    assert "CONFIRM_REAL_RUN" in source
    assert "AutoGen GroupChat은 다음 통합 단계" not in source
    assert "AIOpsLab + Prometheus + Kubernetes" in source


def test_console_exposes_ready_gated_autogen_controller_and_model_provenance():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert '<select id="controller-select" hidden aria-hidden="true">' in html
    assert '<option value="autogen">AutoGen GroupChat</option>' in html
    assert 'id="controller-options"' in html
    assert 'data-controller="deterministic"' in html
    assert 'data-controller="autogen"' in html
    assert 'id="autogen-controller-state"' in html
    assert "RoundRobin GroupChat" in html
    assert "구조화 응답" in html
    assert "안전 검증" in html
    assert 'id="model-input"' in html
    assert 'id="controller-provenance"' in html
    assert 'id="autogen-transcript"' in html
    assert 'controller: elements["controller-select"].value' in script
    assert 'model: elements["model-input"].value.trim()' in script
    assert 'protocol_profile: controllerProfile()' in script
    assert 'connections.autogen' in script
    assert 'button[data-controller]' in script
    assert 'elements["autogen-controller-state"]' in script
    assert 'elements["advanced-settings"].open = isAutogen' in script
    assert 'elements["advanced-settings"].open = job.request.controller === "autogen"' in script
    assert 'autogenOption.disabled' not in script
    assert 'report.autogen_transcript' in script


def test_console_styles_use_multi_view_desktop_shell_and_mobile_reflow():
    source = _source(STYLES_CSS)

    assert ".platform-shell" in source
    assert ".platform-sidebar" in source
    assert "grid-template-columns: 232px minmax(0, 1fr)" in source
    assert ".global-context" in source
    assert '.view-panel[hidden]' in source
    assert ".view-panel.is-active" in source
    assert ".experiment-workspace" in source
    assert ".experiment-controls" in source
    assert ".live-workflow" in source
    assert ".decision-inspector" in source
    assert ".section-tabs" in source
    assert ".controller-options" in source
    assert ".controller-option" in source
    assert ".header-run" not in source
    assert "@media (max-width: 760px)" in source
    assert "position: sticky" in source
    assert "overflow-wrap: anywhere" in source
    assert "letter-spacing: 0" in source


def test_console_integrates_aiopslab_into_the_primary_experiment_contract():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert 'data-scenario-link="aiopslab-hotel-reservation"' in html
    assert 'data-view-panel="aiopslab"' not in html
    assert 'incident_source: item.incident_source' in script
    assert 'benchmark_id: item.benchmark_id' in script
    assert 'state.selectedScenario = job.request.scenario_id' in script
    assert 'api("/api/experiments",' in script


def test_console_runs_recovery_action_comparison_and_renders_graphs():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert 'id="recovery-comparison-panel"' in html
    assert 'id="comparison-mode"' in html
    assert 'id="comparison-repetitions"' in html
    assert 'id="comparison-run"' in html
    assert 'id="comparison-cancel"' in html
    assert 'id="comparison-progress"' in html
    assert 'id="comparison-success-chart"' in html
    assert 'id="comparison-recovery-chart"' in html
    assert "합성 비교 데이터" in html

    assert 'api("/api/comparisons/recovery")' in script
    assert 'api("/api/comparisons/recovery/jobs?limit=20")' in script
    assert 'api("/api/comparisons/recovery/jobs",' in script
    assert "new EventSource(`/api/comparisons/recovery/jobs/${state.comparisonJobId}/events`)" in script
    assert "`/api/comparisons/recovery/jobs/${state.comparisonJobId}/cancel`" in script
    assert "EXECUTE REAL COMPARISON" in script


def test_recovery_experiment_uses_compact_controls_and_grouped_workflow():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)
    styles = _source(STYLES_CSS)

    assert 'class="scenario-list scenario-grid"' in html
    assert 'id="advanced-settings"' in html
    assert '<summary>고급 설정</summary>' in html
    assert html.count('class="workflow-phase') == 4
    assert 'data-stages="preflight injecting_fault collecting_evidence"' in html
    assert 'data-stages="executing observing_recovery cleanup completed"' in html
    assert 'id="selection-summary"' in html
    assert 'id="safety-status"' in html

    assert "const WORKFLOW_PHASES" in script
    assert 'elements["selection-summary"]' in script
    assert 'item.dataset.stages.split(" ")' in script

    assert ".scenario-grid" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles
    assert ".workflow-phase" in styles
    assert ".advanced-settings" in styles
