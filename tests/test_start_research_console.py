from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_start_script_does_not_use_pipefail_sensitive_quiet_grep_for_chaos_resources():
    script = (ROOT / "scripts" / "start_research_console.sh").read_text(
        encoding="utf-8"
    )

    assert 'CHAOS_RESOURCES="$(kubectl api-resources --api-group=chaos-mesh.org --no-headers)"' in script
    assert 'grep -q .' not in script
    assert 'networkchaos' in script
    assert 'podchaos' in script
    assert 'stresschaos' in script
