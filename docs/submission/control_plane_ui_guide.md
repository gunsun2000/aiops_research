# AIOps 4-Agent Control Plane UI

이 문서는 교수님 시연과 연구실 점검을 위한 웹 기반 Control Plane 실행 방법을 정리합니다.

## 목적

Control Plane UI는 기존 연구 코어를 바꾸지 않고 하나의 운영 실험을
`ExperimentSession`으로 연결해 보여줍니다.

- 대시보드: 연구 상태와 전체 운영 흐름
- 운영 실험: 장애 4종 중 하나를 선택해 Evidence부터 결과까지 7단계 실행
- 4-Agent 판단: 현재 세션의 역할별 decision, action, reward
- 상호감시: 현재 세션의 peer review, veto, 협상 라운드와 합의
- 안전 검증: Python Validator와 선택적 Go Guard 경계
- 실험 근거: 동일 브라우저 세션의 실행 이력과 원본 ExperimentSession JSON
- 연구 문서: 공식 DOCX 보고서·실행 가이드·정책 명세와 MD 원본

`조건 → Evidence → Agent 진단 → 상호검토·합의 → 안전 검증 → 실행·복구 관찰
→ 결과·산출물`은 모두 같은 `experiment_id`를 사용합니다. 따라서 각 메뉴는
서로 다른 프로그램이 아니라 동일한 실험 세션을 연구 목적별로 분석하는 화면입니다.

UI는 연구 설명과 안전한 mock 판단 확인을 위한 시연 화면입니다. 실제 Kubernetes
`real` 제어는 기존 CLI와 명시적 확인 절차로 수행합니다.

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
| 연구 개요 | `#/dashboard` | 연구 상태, 4-Agent, 폐쇄 루프와 mock/real 경계 |
| 운영 실험 | `#/experiments` | Pod Kill, CPU Stress, Memory Stress, Network Delay를 동일한 7단계 UI로 실행 |
| 4-Agent 판단 | `#/decision` | 현재 ExperimentSession의 Agent별 진단·제안·reward |
| 상호감시 | `#/supervision` | 현재 세션의 동료 검토, veto, 협상 라운드와 합의 |
| 안전 경계 | `#/safety` | 현재 Action에 적용된 Validator, 선택적 Go Guard와 bounded command |
| 실험 근거 | `#/evidence` | 브라우저 실행 이력과 현재 ExperimentSession 원본 JSON |
| 연구 문서 | `#/documents` | 공식 DOCX 3종, 기술 원본 MD, 전체 구성도 |

사이드바를 이동해도 `currentSession`은 유지됩니다. 메뉴를 선택하면 중앙 workspace는
바뀌지만, Agent 판단·합의·안전 검증·실험 근거는 모두 같은 `experiment_id`를
참조합니다.

## 안전 정책

첫 버전 UI는 연구 시연 안정성을 위해 `mock` 판단을 중심으로 동작합니다.

- UI에는 real-mode 실행 버튼을 제공하지 않습니다.
- 실제 Kubernetes 제어는 `docs/submission/execution_code_guide.md`의 CLI 절차로 실행합니다.
- UI의 4개 시나리오는 재현 가능한 `FakeEvidenceProvider` 기반 mock preset입니다.
- 화면에는 Evidence source와 `Mock research boundary`를 표시해 real 결과와 구분합니다.
- `POST /api/mock-alert`는 기존 Coordinator, Agent, Validator 경로를 사용하지만 실행 모드는 `mock`으로 고정됩니다.
- `POST /api/mutual-supervision/mock`은 deterministic 상호감시 엔진을 호출하며 실제 Kubernetes 상태를 변경하지 않습니다.
- `POST /api/experiments/mock`은 시나리오 preset을 실행하고 전체 결과를 하나의 `ExperimentSession`으로 정규화합니다.
- 상호감시 deterministic v1은 응용관리 Action을 HA·인프라·비용 Agent가 교차 검토하고, 실행 후에는 4-Agent 역할별 재평가를 수행합니다.
- 실제 제어는 UI에서 직접 제공하지 않습니다. CLI `real` 모드는 Kubernetes evidence, target lock, Validator를 모두 통과해야 합니다.

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
| `GET /api/scenarios` | UI에서 실행 가능한 mock 장애 시나리오 4종 조회 |
| `POST /api/experiments/mock` | 선택한 장애를 실행하고 통합 ExperimentSession 생성 |
| `GET /api/experiments/{experiment_id}` | 저장된 ExperimentSession 조회 |
| `GET /api/runs/latest` | 최신 recovery-action-pilot run 조회 |
| `POST /api/mock-alert` | mock 4-Agent 판단 실행 |
| `POST /api/mutual-supervision/mock` | mock 상호검토·재합의·사후평가 실행 |
| `GET /api/artifacts/{path}` | 허용된 `runs/`, `docs/` 파일 조회 |

FastAPI 문서:

```text
http://127.0.0.1:18080/api/docs
```
