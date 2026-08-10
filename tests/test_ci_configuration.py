from pathlib import Path
import tomllib


def test_ci_installs_ui_dependencies_before_running_web_tests():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'python -m pip install -e ".[dev,autogen,ui]"' in workflow


def test_autogen_dependencies_are_pinned_to_the_tested_compatible_stack():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["optional-dependencies"]["autogen"]

    assert "autogen-core==0.7.5" in dependencies
    assert "autogen-agentchat==0.7.5" in dependencies
    assert "autogen-ext[openai]==0.7.5" in dependencies
