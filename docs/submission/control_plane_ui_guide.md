# AIOps 4-Agent Control Plane UI

이 문서는 교수님 시연과 연구실 점검을 위한 웹 기반 Control Plane 실행 방법을 정리합니다.

## 목적

Control Plane UI는 기존 연구 코어를 바꾸지 않고 목적별 독립 화면을 제공합니다.

- 대시보드: 연구 상태와 전체 운영 흐름
- 장애 실험: Chaos Mesh 장애 4종과 action 비교 매트릭스
- 4-Agent 판단: mock 기반 역할별 decision, action, reward
- 안전 검증: Python Validator와 선택적 Go Guard 경계
- 실험 결과: 최근 recovery 결과, reward ranking, 정량 artifact
- 연구 문서: 공식 DOCX 보고서·실행 가이드·정책 명세와 MD 원본

UI는 연구 설명과 안전한 mock 판단 확인을 위한 시연 화면입니다. 실제 Kubernetes `real` 제어는 기존 CLI와 명시적 확인 절차로 수행합니다.

## 설치

서버 환경:

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[ui,dev,autogen]"
```

Windows 로컬 환경:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
python -m pip install -e ".[ui,dev,autogen]"
```

프론트엔드는 외부 React CDN이나 별도 build tool 없이 정적 HTML/CSS/JavaScript로 동작합니다. 그래서 인터넷이 막힌 시연 환경에서도 FastAPI 서버만 실행되면 화면을 열 수 있습니다.

## 실행

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research

export AIOPS_REPO_ROOT="$(pwd)"
export AIOPS_BIND_ADDRESS="127.0.0.1"
export PORT=18080

aiops-control-plane
```

브라우저:

```text
http://127.0.0.1:18080/
```

Windows PowerShell:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
$env:AIOPS_REPO_ROOT=(Get-Location).Path
$env:AIOPS_BIND_ADDRESS="127.0.0.1"
$env:PORT="18080"
aiops-control-plane
```

## 화면 구성

| 화면 | Hash route | 내용 |
| --- | --- | --- |
| 대시보드 | `#/dashboard` | 연구 상태, 4-Agent, 6단계 운영 흐름, 최근 실험 |
| 장애 실험 | `#/experiments` | 장애 4종, action 3종, 36회 실험 매트릭스 |
| 4-Agent 판단 | `#/decision` | mock 장애 입력, Agent별 판단, 합의와 검증 명령 |
| 안전 검증 | `#/safety` | Registry, consensus, Validator, Guard, dry-run 경계 |
| 실험 결과 | `#/evidence` | JSONL, reward ranking, CSV·PNG·SVG artifact |
| 연구 문서 | `#/documents` | 공식 DOCX 3종, 기술 원본 MD, 전체 구성도 |

사이드바는 같은 문서 안의 위치로 스크롤하지 않습니다. 메뉴를 선택하면 중앙
workspace 전체가 해당 기능 화면으로 교체됩니다.

## 안전 정책

첫 버전 UI는 연구 시연 안정성을 위해 `mock` 판단을 중심으로 동작합니다.

- UI에는 real-mode 실행 버튼을 제공하지 않습니다.
- 실제 Kubernetes 제어는 `docs/submission/execution_code_guide.md`의 CLI 절차로 실행합니다.
- UI는 `runs/` 결과와 `docs/` 문서를 읽어 보여주는 관측 화면 역할을 우선합니다.
- `POST /api/mock-alert`는 기존 Coordinator, Agent, Validator 경로를 사용하지만 실행 모드는 `mock`으로 고정됩니다.

## 공식 연구 문서

`연구 문서` 화면은 다음 DOCX 산출물을 우선 표시합니다.

| 문서 | 용도 |
| --- | --- |
| `AIOps_4Agent_Research_Report.docx` | 연구 전체 설명과 결과 보고 |
| `AIOps_Experiment_Operations_Guide.docx` | 설치·실험·검증 재현 |
| `AIOps_Agent_Policy_Specification.docx` | Agent action/reward와 안전 경계 |

각 문서 옆의 `MD 원본`은 구현과 함께 갱신되는 기술 원문입니다. DOCX는 다음 명령으로 재생성합니다.

```bash
python -m pip install -e ".[docs]"
python scripts/build_research_documents.py
```

## API

| Endpoint | 역할 |
| --- | --- |
| `GET /healthz` | UI backend 상태 확인 |
| `GET /api/overview` | 프로젝트 상태, 최신 run, 안전 계층 요약 |
| `GET /api/agents` | Agent Registry 조회 |
| `GET /api/runs/latest` | 최신 recovery-action-pilot run 조회 |
| `POST /api/mock-alert` | mock 4-Agent 판단 실행 |
| `GET /api/artifacts/{path}` | 허용된 `runs/`, `docs/` 파일 조회 |

FastAPI 문서:

```text
http://127.0.0.1:18080/api/docs
```
