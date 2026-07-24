# 공식 연구 문서

이 폴더의 DOCX는 교수님, 연구실 구성원, 외부 검토자가 읽는 공식 연구 산출물입니다.

| 파일 | 용도 |
| --- | --- |
| `AIOps_4Agent_Research_Report.docx` | 연구 배경, 아키텍처, 실험 설계, 결과, 한계 |
| `AIOps_Experiment_Operations_Guide.docx` | 설치, 실행, 시험, real 실험 재현 |
| `AIOps_Agent_Policy_Specification.docx` | Agent 역할, action/reward, 합의, 안전 검증 |

생성 명령:

```bash
python -m pip install -e ".[docs]"
python scripts/build_research_documents.py
```

DOCX는 `scripts/build_research_documents.py`에서 생성합니다. 세부 기술 내용은 `docs/submission/`, `docs/design/`, `docs/experiments/`의 Markdown 원본을 함께 참고합니다.
