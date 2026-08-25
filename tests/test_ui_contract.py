from html import unescape
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_ui_exposes_the_orchestration_workflow_without_recovery_controls() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    combined = unescape(f"{html}\n{script}").lower()

    for label in (
        "input & context",
        "partition decision",
        "scheduling handoff",
        "federated coordination",
        "generate plan",
    ):
        assert label in combined

    for forbidden in ("ha agent", "cost agent", "chaos mesh", "aiopslab", "autogen"):
        assert forbidden not in combined
