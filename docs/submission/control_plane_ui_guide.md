# AIOps 4-Agent 연구 운영 콘솔

이 문서는 웹 Control Plane에서 4-Agent 장애 복구 실험을 생성하고, 진행 과정과
연구 근거를 확인하는 방법을 설명합니다.

## 1. 플랫폼 목적

콘솔은 다음 흐름을 하나의 `experiment_id`로 연결합니다.

```text
실험 조건
-> 장애 주입
-> Evidence 수집
-> 4-Agent 판단 및 상호검토
-> 합의와 안전 검증
-> 제한된 Kubernetes Action
-> 복구 관찰과 cleanup
-> 결과 및 이벤트 저장
```

화면은 여러 기능 페이지로 분리하지 않고 다음 네 영역을 동시에 보여줍니다.

| 영역 | 내용 |
| --- | --- |
| 왼쪽 | 장애 시나리오, 실행 모드, 연구 프로파일, 반복 횟수 |
| 가운데 | 7단계 실행 상태, Evidence, 4-Agent 상호감시, 최종 Action, 이벤트 |
| 오른쪽 | 선택 Agent 판단, peer review, allowlist와 Validator 결과 |
| 하단 | 복구 성공, MTTR, Reward, Agent review, 산출물 |

## 2. 현재 구현 범위

구현된 기능:

- Pod Kill, CPU Stress, Memory Stress, Network Delay 시나리오 선택
- `mock`, `dry-run`, `real` 실행 요청
- SQLite 기반 영속 Job 및 이벤트 저장
- 백그라운드 반복 실행
- SSE 기반 실시간 단계와 로그 표시
- 실행 취소 요청
- 새로고침 후 최근 Job과 이벤트 복원
- 서버 재시작 시 미완료 Job을 `interrupted`로 안전 종료
- deterministic 4-Agent 상호감시와 Python Validator 결과 표시
- AutoGen GroupChat을 선택 가능한 Controller로 실행
- AutoGen model/controller provenance와 structured transcript 저장·표시

현재 웹 Job에 아직 연결하지 않은 기능:

- AIOpsLab benchmark 실행

AIOpsLab은 기존 CLI/스크립트 경로에는 존재하지만, 콘솔에서는 다음 통합 단계로
명확히 표시합니다. AutoGen은 의존성과 credential이 준비된 경우에만 선택할 수 있으며,
준비되지 않았으면 장애 주입 전 preflight에서 거부됩니다.

## 3. 설치와 실행

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[ui,dev,autogen]"

export AIOPS_REPO_ROOT="$(pwd)"
export AIOPS_BIND_ADDRESS="127.0.0.1"
export PORT=18080

aiops-control-plane
```

AutoGen Controller를 사용하려면 서버를 시작하기 전에 credential을 설정합니다.

```bash
export OPENAI_API_KEY="<your-api-key>"
aiops-control-plane
```

UI에서 `AutoGen GroupChat`을 선택하면 `four-agent-autogen-v1` 프로파일과 모델 입력이
연결됩니다. 모델 응답은 자유형 shell 명령으로 실행되지 않고 구조화된 Agent 판단으로
변환된 뒤 기존 Validator, allowlist, replica 제한과 cleanup 경계를 그대로 통과합니다.

브라우저:

```text
http://127.0.0.1:18080/
```

Windows PowerShell:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
python -m pip install -e ".[ui,dev,autogen]"
$env:AIOPS_REPO_ROOT=(Get-Location).Path
$env:AIOPS_BIND_ADDRESS="127.0.0.1"
$env:PORT="18080"
aiops-control-plane
```

Job DB의 기본 위치는 다음과 같습니다.

```text
runs/control-plane/experiment-jobs.sqlite3
```

다른 위치를 사용하려면 `AIOPS_JOB_DATABASE`를 설정합니다.

## 4. 실행 모드

| 모드 | Evidence | 외부 시스템 변경 |
| --- | --- | --- |
| `mock` | `FakeEvidenceProvider` 합성 Evidence | 없음 |
| `dry-run` | 등록된 실제 대상 기준 검증 | Kubernetes 상태 변경 없음 |
| `real` | Prometheus와 Kubernetes Evidence | Chaos Mesh 장애 및 허용된 Kubernetes Action |

`real` 실행은 Ubuntu 연구 서버에서만 사용합니다. 서버 시작 전에 다음 Gate를
명시적으로 열어야 합니다.

```bash
export CONFIRM_REAL_RUN=YES
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
export PROMETHEUS_URL="http://127.0.0.1:9091"
aiops-control-plane
```

이후 UI에서 `Real`을 선택하고 실행할 때 정확히 다음 문구를 입력해야 합니다.

```text
EXECUTE REAL EXPERIMENT
```

환경 Gate와 확인 문구는 실행 허가 조건일 뿐입니다. 등록 시나리오, target
allowlist, replica 최소·최대, target lock, Python Validator와 cleanup은 계속
적용됩니다.

## 5. 취소와 서버 재시작

- 취소는 즉시 프로세스를 강제 종료하지 않고 runtime의 안전한 단계 경계에서 처리합니다.
- 장애가 주입된 뒤 취소되더라도 cleanup은 항상 시도합니다.
- 서버가 재시작되면 기존 `queued`, `running`, `cancelling` Job은
  `interrupted`로 기록합니다.
- 중단된 Job을 자동 재실행하지 않습니다. 이는 동일 장애가 두 번 주입되는 것을
  막기 위한 보수적 정책입니다.

## 6. API

| Endpoint | 역할 |
| --- | --- |
| `GET /healthz` | 서버 상태 |
| `GET /api/platform` | runtime과 Job 기능 범위 |
| `GET /api/connections` | Kubernetes, Prometheus, Chaos Mesh 연결 준비 상태 |
| `GET /api/scenarios` | 등록 장애 시나리오 조회 |
| `POST /api/experiments/validate` | 읽기 전용 요청 preflight |
| `POST /api/experiments` | 백그라운드 실험 Job 생성 |
| `GET /api/experiments` | 최근 Job 목록 |
| `GET /api/experiments/{experiment_id}` | Job, 결과, 저장 이벤트 조회 |
| `GET /api/experiments/{experiment_id}/events` | SSE 이벤트 replay와 live stream |
| `POST /api/experiments/{experiment_id}/cancel` | 실행 취소 요청 |

FastAPI 문서:

```text
http://127.0.0.1:18080/api/docs
```

## 7. 연구 결과 해석

- `mock` 성공은 Agent·합의·Validator·UI 연결 검증입니다.
- `dry-run` 성공은 명령과 API 허용성 검증이며 실제 복구 성공이 아닙니다.
- `real` 결과는 Ubuntu 서버에서 Prometheus, Chaos Mesh, Kubernetes 연결과
  cleanup 산출물까지 확인한 경우에만 실제 실험 근거로 사용합니다.
- AutoGen fake-provider 자동 시험은 웹·Job·transcript 연결 검증이며 실제 모델 호출 결과가 아닙니다.
- AutoGen real 결과는 Ubuntu 서버에서 credential, 선택 모델, Controller provenance,
  transcript와 Kubernetes 산출물까지 확인한 경우에만 실제 비교 실험 근거로 사용합니다.
- AIOpsLab 결과는 웹 Job 통합 전까지 기존 benchmark 산출물과 별도로 구분합니다.
