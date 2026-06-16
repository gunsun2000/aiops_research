from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUTPUT = Path("docs/requirements_definition.docx")


def set_font(run, name: str = "Malgun Gothic", size: float | None = None, bold=None, color: str | None = None) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:ascii"), name)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), name)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, *, bold: bool = False, fill: str | None = None) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    set_font(run, size=9.5, bold=bold)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if fill:
        set_cell_shading(cell, fill)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[float]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        set_cell_text(cell, header, bold=True, fill="F2F4F7")
        cell.width = Inches(widths[index])
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            set_cell_text(cells[index], value)
            cells[index].width = Inches(widths[index])
    doc.add_paragraph()


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)

    normal = doc.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    normal.font.size = Pt(10.5)

    for style_name, size, color in [
        ("Heading 1", 16, "2E74B5"),
        ("Heading 2", 13, "2E74B5"),
        ("Heading 3", 12, "1F4D78"),
    ]:
        style = doc.styles[style_name]
        style.font.name = "Malgun Gothic"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = True


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    heading = doc.add_heading(text, level=level)
    for run in heading.runs:
        set_font(run, size=16 if level == 1 else 13, bold=True, color="2E74B5")


def build_docx() -> None:
    doc = Document()
    configure_document(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(
        title.add_run("AIOps 4-Agent 서비스 제어 자동화 요구사항 정의서"),
        size=18,
        bold=True,
        color="0B2545",
    )

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(
        subtitle.add_run("AI 기반 서비스 제어 및 관리 자동화 프레임워크"),
        size=11,
        color="555555",
    )

    doc.add_paragraph(
        "본 문서는 AIOps 4-Agent 연구 프로토타입의 구현 범위, 기능 요구사항, 시험 방법, 산출물 구성을 정리한 제출용 요구사항 정의서이다."
    )
    paragraph = doc.add_paragraph()
    set_font(paragraph.add_run("핵심 정의: "), bold=True)
    set_font(
        paragraph.add_run(
            "4개의 AI Agent가 장애 상태를 역할별로 판단하고, 구조화된 action과 reward 정책을 통해 Kubernetes 제어 명령을 안전하게 생성·검증·실행한다."
        )
    )

    add_heading(doc, "1. 연구 개발 범위")
    for item in [
        "AI LLM 운영 관리 구조 설계 및 프로토타입",
        "AI 에이전트 등록 관리 프로토타입",
        "AI 응용 자동화 에이전트 설계 및 프로토타입",
        "CPU/GPU VM 기반 AI 응용 배포/제어 추론 최적화 전략",
        "Go 언어 기반 최종 Kubernetes action guard",
        "최소 2종 이상의 LLM/코딩 에이전트 관점 교차 검증",
    ]:
        doc.add_paragraph(item, style="List Bullet")

    add_heading(doc, "2. 기능 요구사항")
    add_table(
        doc,
        ["ID", "요구사항", "상태"],
        [
            ["FR-01", "4-Agent 역할 분리 및 action/reward 정책 설계", "완료"],
            ["FR-02", "AutoGen GroupChat 기반 Agent 대화 경로", "완료"],
            ["FR-03", "Prometheus metric 입력 기반 실행 경로", "완료"],
            ["FR-04", "Chaos Mesh 장애 4종 실험", "완료"],
            ["FR-05", "AIOpsLab Hotel Reservation 탐지 benchmark 연동", "완료"],
            ["FR-06", "Kubernetes dry-run/real 제어 및 상태 확인", "완료"],
            ["FR-07", "Go 언어 기반 최종 action guard", "완료"],
            ["FR-08", "Agent 등록 관리 프로토타입", "완료"],
            ["FR-09", "CPU/GPU VM 기반 추론 배치 최적화 추천", "완료"],
            ["FR-10", "Reward 정책 변화와 장애별 action ranking 비교", "완료"],
            ["FR-11", "HTTP API 서버 형태의 Agent Registry 서비스", "향후 확장"],
        ],
        [0.8, 4.8, 0.9],
    )

    add_heading(doc, "3. Agent 역할 정의")
    add_table(
        doc,
        ["Agent", "역할", "대표 action"],
        [
            ["AIServiceHASupportAgent", "장애 진단, 가용성 판단, 자율 복구 필요성 평가", "ha_scale_out_required"],
            ["AIApplicationManagementAgent", "응용 배포, 복구 action 선택, Kubernetes 제어", "app_scale_deployment"],
            ["AISemiconductorInfraOpsAgent", "CPU/GPU/NPU 자원 수용성 및 VM 배치 가능성 검증", "infra_capacity_approved"],
            ["CostOptimizationAgent", "자원 사용량과 비용 정책 검증", "cost_budget_approved"],
        ],
        [2.0, 3.4, 1.1],
    )

    add_heading(doc, "4. CPU/GPU VM 추론 최적화 전략")
    doc.add_paragraph(
        "추론 최적화 모듈은 workload의 accelerator 필요 여부, VRAM 요구량, latency SLO, throughput 요구량, VM 비용, 가용 replica 수를 기준으로 CPU/GPU VM 후보를 평가한다."
    )
    add_table(
        doc,
        ["Workload", "선택 Resource", "Action", "판단 근거"],
        [
            ["llm-chat-inference", "gpu-vm-l4", "deploy_on_gpu_vm", "LLM은 GPU가 필요하며 L4가 SLO와 비용 균형을 만족"],
            ["text-classifier", "cpu-vm-standard", "deploy_on_cpu_vm", "CPU VM으로도 SLO를 만족하여 비용 효율적"],
        ],
        [1.7, 1.4, 1.5, 1.9],
    )

    add_heading(doc, "5. 시험 및 검증 방법")
    add_table(
        doc,
        ["시험", "명령", "성공 기준"],
        [
            ["Python 단위 테스트", "python -m pytest", "전체 테스트 passed"],
            ["Go guard 테스트", "go test ./...", "Go validator 테스트 통과"],
            ["Agent Registry", "aiops-k8s-agents list-agents", "4개 Agent 조회"],
            ["Inference Optimizer", "recommend-inference-placement", "워크로드별 적합 VM 추천"],
            ["Recovery 실험", "server_recovery_action_pilot.sh", "36개 결과 기록"],
        ],
        [1.4, 2.6, 2.5],
    )

    add_heading(doc, "6. 산출물")
    add_table(
        doc,
        ["산출물", "설명"],
        [
            ["config/agent_registry.json", "4-Agent 등록 관리 설정"],
            ["config/inference_optimization.json", "CPU/GPU VM 추론 배치 정책"],
            ["go/aiops-guard", "Go 언어 기반 최종 action guard"],
            ["docs/functional_api_guide.md", "기능/API 사용 가이드"],
            ["docs/test_guide.md", "시험 검증 가이드"],
            ["docs/requirements_definition.docx", "제출용 요구사항 정의서"],
        ],
        [2.6, 3.9],
    )

    add_heading(doc, "7. 향후 확장")
    for item in [
        "single-agent baseline 및 Agent 제거 ablation 실험",
        "AutoGen multi-round real action 선택 실험",
        "실제 GPU/NPU Kubernetes scheduling과 모델 추론 서비스 연동",
        "HTTP API 서버 기반 Agent Registry 관리 기능 구현",
    ]:
        doc.add_paragraph(item, style="List Bullet")

    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_font(footer.add_run("AIOps 4-Agent Research"), size=8, color="777777")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build_docx()
