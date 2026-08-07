from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "ui" / "control_plane_static" / "index.html"
APP = ROOT / "ui" / "control_plane_static" / "app.js"
REFERENCE = ROOT / "ui" / "control_plane_static" / "reference-ui.js"


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
    assert "/events" in script
    assert "artifact_urls" in script


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
