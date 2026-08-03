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
    assert "styles.css?v=10" in source
    assert "app.js?v=10" in source


def test_console_offers_all_registered_fault_scenarios_and_safe_modes():
    source = _source(INDEX_HTML) + _source(APP_JS)

    for scenario_id in (
        "pod-kill",
        "cpu-stress",
        "memory-stress",
        "network-delay",
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
    assert "AIOpsLab Detection Benchmark" in source


def test_console_exposes_ready_gated_autogen_controller_and_model_provenance():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert '<option value="autogen">AutoGen GroupChat</option>' in html
    assert 'id="model-input"' in html
    assert 'id="controller-provenance"' in html
    assert 'id="autogen-transcript"' in html
    assert 'controller: elements["controller-select"].value' in script
    assert 'model: elements["model-input"].value.trim()' in script
    assert 'protocol_profile: controllerProfile()' in script
    assert 'connections.autogen' in script
    assert 'report.autogen_transcript' in script


def test_console_styles_use_three_area_desktop_layout_and_mobile_reflow():
    source = _source(STYLES_CSS)

    assert "grid-template-columns: 220px minmax(440px, 1fr) 300px" in source
    assert ".experiment-controls" in source
    assert ".live-workflow" in source
    assert ".decision-inspector" in source
    assert "@media (max-width: 760px)" in source
    assert "overflow-wrap: anywhere" in source
    assert "letter-spacing: 0" in source


def test_console_adds_compact_separate_aiopslab_benchmark_job_panel():
    html = _source(INDEX_HTML)
    script = _source(APP_JS)

    assert '<details class="benchmark-panel" id="aiopslab-benchmark-panel">' in html
    assert 'id="aiopslab-benchmark-select"' in html
    assert 'id="aiopslab-repetitions"' in html
    assert 'id="aiopslab-run"' in html
    assert 'id="aiopslab-cancel"' in html
    assert 'id="aiopslab-accuracy"' in html
    assert 'id="aiopslab-ttd"' in html
    assert 'id="aiopslab-reward"' in html
    assert 'id="aiopslab-event-log"' in html
    assert "별도 탐지 Benchmark" in html

    assert 'api("/api/benchmarks/aiopslab")' in script
    assert 'api("/api/benchmarks/aiopslab/jobs?limit=20")' in script
    assert 'api("/api/benchmarks/aiopslab/jobs",' in script
    assert "new EventSource(`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/events`)" in script
    assert "`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/cancel`" in script
    assert "artifact_urls" in script
