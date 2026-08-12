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


def test_start_script_selects_project_environment_and_delegates_lifecycle():
    script = (ROOT / "scripts" / "start_research_console.sh").read_text(
        encoding="utf-8"
    )

    assert "AIOPS_RESEARCH_PYTHON" in script
    assert 'anaconda3/envs/aiops_research/bin/python' in script
    assert 'miniconda3/envs/aiops_research/bin/python' in script
    assert "fastapi, uvicorn" in script
    assert 'PATH="$HOME/bin:$PATH"' in script
    assert 'python -m aiops_k8s_agents.control_plane_process' not in script
    assert '-m aiops_k8s_agents.control_plane_process "$ACTION"' in script


def test_start_script_keeps_optional_integrations_advisory():
    script = (ROOT / "scripts" / "start_research_console.sh").read_text(
        encoding="utf-8"
    )

    assert "warning: kubectl was not found" in script
    assert "warning: AIOpsLab runtime was not found" in script
    assert 'AIOPS_AUTO_PORT_FORWARD="${AIOPS_AUTO_PORT_FORWARD:-auto}"' in script
    assert 'exec aiops-control-plane' not in script
