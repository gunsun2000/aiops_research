from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "ui" / "control_plane_static" / "app.js"
STYLES_CSS = ROOT / "ui" / "control_plane_static" / "styles.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_control_plane_uses_independent_hash_routes():
    source = _source(APP_JS)

    for route in (
        "dashboard",
        "experiments",
        "decision",
        "supervision",
        "safety",
        "evidence",
        "documents",
    ):
        assert f'"#/{route}"' in source

    assert 'window.addEventListener("hashchange"' in source
    assert '"#overview"' not in source
    assert '"#architecture"' not in source


def test_control_plane_has_one_renderer_for_each_workspace():
    source = _source(APP_JS)

    for renderer in (
        "dashboardView",
        "experimentsView",
        "decisionView",
        "supervisionView",
        "safetyView",
        "evidenceView",
        "documentsView",
    ):
        assert f"function {renderer}(" in source

    assert "function workspaceView(" in source
    assert "function hero(" not in source
    assert "function evidenceAndDemo(" not in source


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


def test_guard_backend_selection_and_session_provenance_stay_visible():
    source = _source(APP_JS)

    assert 'selected: state.backend === "python"' in source
    assert 'selected: state.backend === "go"' in source
    assert "session ? session.guard_backend : state.backend" in source


def test_control_plane_exposes_all_four_fault_scenarios():
    source = _source(APP_JS)

    for scenario_id in (
        "pod-kill",
        "cpu-stress",
        "memory-stress",
        "network-delay",
    ):
        assert scenario_id in source


def test_control_plane_renders_the_seven_experiment_stages():
    source = _source(APP_JS)

    for stage in (
        "조건 설정",
        "Evidence",
        "Agent 진단",
        "상호검토·합의",
        "안전 검증",
        "실행·복구 관찰",
        "결과·산출물",
    ):
        assert stage in source


def test_control_plane_styles_separate_navigation_and_workspace():
    source = _source(STYLES_CSS)

    for selector in (
        ".workspace",
        ".workspace-header",
        ".route-view",
        ".nav-link.is-active",
        ".status-strip",
    ):
        assert selector in source

    assert "grid-template-columns: 292px minmax(0, 1fr)" not in source


def test_control_plane_prevents_long_research_terms_from_overflowing_mobile():
    source = _source(STYLES_CSS)

    assert "overflow-x: hidden" in source
    assert "overflow-wrap: anywhere" in source
