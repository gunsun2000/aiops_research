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


def test_plan_artifact_workspace_exposes_catalog_details_and_lineage() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "artifactList",
        "artifactEmpty",
        "artifactDetail",
        "artifactHistory",
        "artifactDownloadButton",
        "artifactDeleteButton",
        "artifactActionMessage",
    ):
        assert f'id="{element_id}"' in html

    for behavior in (
        'fetch("/api/plans")',
        "async function loadArtifacts",
        "async function loadArtifact",
        'fetch(`/api/plans/${encodeURIComponent(planId)}/history`)',
        "await loadArtifacts(report.plan.plan_id)",
        '`/api/plans/${encodeURIComponent(plan.plan_id)}/download`',
        "plan.display_id || plan.plan_id",
        'method: "DELETE"',
        "window.confirm",
        "cannot be recovered",
        "was permanently deleted",
    ):
        assert behavior in script
