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
        "safetyView",
        "evidenceView",
        "documentsView",
    ):
        assert f"function {renderer}(" in source

    assert "function workspaceView(" in source
    assert "function hero(" not in source
    assert "function evidenceAndDemo(" not in source


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
