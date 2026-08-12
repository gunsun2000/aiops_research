import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vscode_forwards_the_remote_control_plane_port():
    settings = json.loads(
        (ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8")
    )

    assert settings["remote.autoForwardPorts"] is True
    assert settings["remote.restoreForwardedPorts"] is True
    assert settings["remote.portsAttributes"]["18180"]["protocol"] == "http"
    assert settings["remote.portsAttributes"]["18180"]["onAutoForward"] == "openBrowser"


def test_vscode_task_starts_the_repository_console():
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    task = next(item for item in tasks["tasks"] if item["label"] == "AIOps: start research console")

    assert task["command"] == "bash scripts/start_research_console.sh"
    assert task["isBackground"] is True


def test_readme_distinguishes_remote_and_local_ports():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Ubuntu 원격 포트" in readme
    assert "로컬 포트 번호는 VS Code가 선택하므로" in readme
    assert "18180 -> 127.0.0.1:18181" not in readme
