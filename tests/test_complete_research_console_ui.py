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
    assert "/api/benchmarks/aiopslab/jobs/${encodeURIComponent(" in script
    assert ".events" in script
    assert "artifact_urls" in script


def test_reference_ui_is_event_driven_and_has_no_mutation_observers():
    script = source(REFERENCE)
    assert "MutationObserver" not in script
    assert "bindAIOpsLabTabs" in script
    assert "addEventListener" in script


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


def test_bulk_experiment_result_deletion_is_visible_safe_and_refreshes_results():
    script = source(REFERENCE)
    assert "delete-all-experiments" in script
    assert "전체 삭제" in script
    assert "deleteAllExperimentResults" in script
    assert "/api/experiments?limit=100" in script
    assert "completed" in script and "failed" in script and "blocked" in script
    assert "cancelled" in script and "interrupted" in script
    assert "queued" in script and "running" in script and "cancelling" in script
    assert "실행 중인 실험은 삭제하지 않습니다" in script
    assert "window.confirm" in script
    assert 'method: "DELETE"' in script or "method:'DELETE'" in script or 'method:"DELETE"' in script
    assert "aiops:history-updated" in script
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
