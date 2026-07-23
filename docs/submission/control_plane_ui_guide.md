# AIOps 4-Agent Control Plane UI

이 문서는 교수님 시연과 연구실 점검을 위한 웹 기반 Control Plane 실행 방법을 정리합니다.

## 목적

Control Plane UI는 기존 연구 코어를 바꾸지 않고 다음 내용을 하나의 화면에서 보여줍니다.

- 4-Agent 역할 구조와 허용 action
- 장애 주입, 관측, Agent 판단, 안전 검증, 피드백으로 이어지는 전체 흐름
- mock 기반 4-Agent 판단 결과
- Python Validator와 선택적 Go Guard 경계
- 최근 recovery 실험 결과, reward ranking, 정량 그래프

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

| 화면 | 의미 |
| --- | --- |
| Header | 연구 목적, 현재 evidence 파일 상태, 기본 실행 모드 |
| Metric Strip | Agent 수, 장애 시나리오 수, bounded action 수, 최근 실험 record 수 |
| Framework Flow | 장애 주입부터 피드백 분석까지의 end-to-end 흐름 |
| 4-Agent 역할 구조 | HA, 응용관리, 인프라, 비용 Agent의 역할과 허용 action |
| 연구 산출물 상태 | Agent registry, recovery config, chaos manifest, runs 폴더 존재 여부 |
| Controlled Decision | 실제 클러스터를 건드리지 않는 mock 4-Agent 판단 실행 |
| Consensus Boundary | Agent별 decision, action, reward 표 |
| Latest Recovery Experiment | 최근 36회 recovery-action-pilot 결과와 reward policy ranking |
| Quantitative Artifacts | 성공률, 복구 시간, reward 그래프 |

## 안전 정책

첫 버전 UI는 연구 시연 안정성을 위해 `mock` 판단을 중심으로 동작합니다.

- UI에는 real-mode 실행 버튼을 제공하지 않습니다.
- 실제 Kubernetes 제어는 `docs/submission/execution_code_guide.md`의 CLI 절차로 실행합니다.
- UI는 `runs/` 결과와 `docs/` 문서를 읽어 보여주는 관측 화면 역할을 우선합니다.
- `POST /api/mock-alert`는 기존 Coordinator, Agent, Validator 경로를 사용하지만 실행 모드는 `mock`으로 고정됩니다.

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
