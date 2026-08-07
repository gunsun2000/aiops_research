from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "docs" / "deliverables"
APP_JS = ROOT / "ui" / "control_plane_static" / "app.js"

EXPECTED_DOCUMENTS = {
    "AIOps_4Agent_Research_Report.docx": "AIOps 4-Agent Kubernetes 장애 복구 연구 보고서",
    "AIOps_Experiment_Operations_Guide.docx": "AIOps 실험 실행 및 검증 가이드",
    "AIOps_Agent_Policy_Specification.docx": "4-Agent Action 및 Reward 정책 명세서",
}


def test_research_docx_deliverables_are_valid_word_documents():
    for filename, title in EXPECTED_DOCUMENTS.items():
        path = DELIVERABLES / filename
        assert path.is_file(), f"missing research deliverable: {path}"

        with ZipFile(path) as archive:
            names = set(archive.namelist())
            assert "[Content_Types].xml" in names
            assert "word/document.xml" in names
            document_xml = archive.read("word/document.xml").decode("utf-8")
            assert title in document_xml


def test_control_plane_prioritizes_docx_research_documents():
    source = APP_JS.read_text(encoding="utf-8")

    for filename in EXPECTED_DOCUMENTS:
        assert f"docs/deliverables/{filename}" in source

    assert "RESEARCH_DOCUMENTS" in source
    assert "renderResearchDocuments" in source
    assert "/api/artifacts/" in source
