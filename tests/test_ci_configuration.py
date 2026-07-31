from pathlib import Path


def test_ci_installs_ui_dependencies_before_running_web_tests():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'python -m pip install -e ".[dev,autogen,ui]"' in workflow
