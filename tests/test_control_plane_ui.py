from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui" / "control_plane_static" / "index.html"
APP_JS = ROOT / "ui" / "control_plane_static" / "app.js"
REFERENCE_JS = ROOT / "ui" / "control_plane_static" / "reference-ui.js"
STYLES_CSS = ROOT / "ui" / "control_plane_static" / "styles.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _compact(source: str) -> str:
    return "".join(source.split())


def test_console_has_four_primary_research_views():
    html = _source(INDEX_HTML)
    assert '<html lang="ko">' in html
    for view in ("overview", "experiment", "aiopslab", "analysis"):
        assert f'data-view="{view}"' in html
        assert f'data-view-panel="{view}"' in html
    assert "시스템 개요" in html
    assert "복구 실험" in html
    assert "AIOpsLab Benchmark" in html
    assert "실험 결과" in html
    assert "styles.css?v=24" in html
    assert "app.js?v=24" in html
    assert "reference-ui.js?v=3" in html


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
        "aiopslab-cancel", "aiopslab-accuracy", "aiopslab-ttd",
        "aiopslab-steps", "aiopslab-reward", "aiopslab-scenario-list",
    ):
        assert f'id="{element_id}"' in html
    assert 'api("/api/benchmarks/aiopslab")' in script
    assert 'api("/api/benchmarks/aiopslab/jobs",' in script
    assert "new EventSource(`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/events`)" in script
    assert "`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/cancel`" in script


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
