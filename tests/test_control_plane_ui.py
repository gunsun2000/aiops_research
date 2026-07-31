from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "ui" / "control_plane_static" / "app.js"
INDEX_HTML = ROOT / "ui" / "control_plane_static" / "index.html"
STYLES_CSS = ROOT / "ui" / "control_plane_static" / "styles.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_control_plane_renders_one_integrated_experiment_console():
    source = _source(APP_JS)

    for class_name in (
        "experiment-console",
        "console-header",
        "metric-strip",
        "scenario-rail",
        "live-canvas",
        "agent-flow-grid",
        "decision-inspector",
    ):
        assert class_name in source

    assert "4-Agent AIOps 실험 콘솔" in source
    assert "운영 판단과 복구 흐름" in source
    assert "장애 시나리오" in source


def test_control_plane_uses_one_experiment_session_for_all_scenarios():
    source = _source(APP_JS)

    assert 'fetch("/api/scenarios"' in source
    assert 'fetch("/api/experiments/mock"' in source
    assert "currentSession" in source
    assert "experimentHistory" in source
    assert "mockResult" not in source
    assert "mutualResult" not in source


def test_scenario_change_clears_a_mismatched_current_session():
    source = _source(APP_JS)

    assert "state.currentSession.condition.scenario !== scenarioId" in source
    assert "state.currentSession = null;" in source


def test_control_plane_exposes_all_four_fault_scenarios():
    source = _source(APP_JS)

    for scenario_id in (
        "pod-kill",
        "cpu-stress",
        "memory-stress",
        "network-delay",
    ):
        assert scenario_id in source


def test_control_plane_exposes_all_four_agent_roles_in_one_flow():
    source = _source(APP_JS)

    for agent_name in (
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    ):
        assert agent_name in source

    assert "selectedAgent" in source
    assert "selectAgent" in source
    assert "상호검토" in source
    assert "최종 Action" in source


def test_guard_backend_and_safety_boundary_remain_visible():
    source = _source(APP_JS)

    assert 'selected: state.backend === "python"' in source
    assert 'selected: state.backend === "go"' in source
    assert "session ? session.guard_backend : state.backend" in source
    assert "Python Validator" in source
    assert "Go Guard" in source
    assert "allowlist" in source
    assert "replica 1–5" in source


def test_control_plane_uses_clean_korean_utf8_and_cache_busting():
    app_source = _source(APP_JS)
    html_source = _source(INDEX_HTML)

    assert "연구 운영" in app_source
    assert "실험 실행" in app_source
    assert "JavaScript가 비활성화되어" in html_source
    assert "styles.css?v=7" in html_source
    assert "app.js?v=7" in html_source


def test_control_plane_styles_match_compact_research_console():
    source = _source(STYLES_CSS)

    for selector in (
        ".experiment-console",
        ".console-header",
        ".metric-strip",
        ".scenario-rail",
        ".live-canvas",
        ".agent-flow-grid",
        ".decision-inspector",
    ):
        assert selector in source

    assert "max-width: 1180px" in source
    assert "grid-template-columns: 230px minmax(0, 1fr)" in source


def test_control_plane_prevents_long_research_terms_from_overflowing_mobile():
    source = _source(STYLES_CSS)

    assert "overflow-x: hidden" in source
    assert "overflow-wrap: anywhere" in source
    assert "@media (max-width: 720px)" in source
