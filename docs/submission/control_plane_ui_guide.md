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

콘솔은 하나의 연구 흐름을 목적별 화면으로 나눠 보여줍니다. 각 화면은 동일한
`experiment_id`와 저장된 Job 결과를 사용하므로 기능이 서로 분리되어 동작하지 않습니다.

| 화면 | 연구자가 확인하는 내용 |
| --- | --- |
| 시스템 개요 | 연결 상태, 8단계 자율 복구 흐름, 실행 중인 실험, 최근 결과 |
| 복구 실험 | 장애 시나리오, Controller, 실행 모드, 안전 설정을 선택하고 실험 실행 |
| AIOpsLab Benchmark | 탐지 benchmark 실행, 진행 상태, 정확도·TTD·step·reward 확인 |
| 실험 결과 | 저장된 실험 검색·필터, 복구 전략 비교, 성능 대시보드 |
| 실험 상세 | 요약, 타임라인, Agent 판단, Evidence, 로그, 산출물 확인 |

복구 실험 화면은 `조건 -> Evidence -> 4-Agent 상호검토 -> 안전 검증 -> 실행 -> 복구
관찰`을 한 Job으로 연결합니다. AIOpsLab은 같은 플랫폼에서 실행·조회되지만 탐지 성능을
평가하는 별도 실험 유형이므로 복구 성능 통계와 혼합하지 않습니다.

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
- 저장된 복구 Job을 장애·Action·Controller/모드별로 집계하는 성능 대시보드
- 복구 성공률, 평균 MTTR, 평균 Team Reward와 실행 횟수 표시
- 실험 상세의 복구 전·후 Evidence, Agent 승인·거부, 실행 로그와 artifact 조회

AIOpsLab detection benchmark는 동일 Control Plane 안에서 복구 실험과 구분된 전용 Job으로 연결되어 있습니다.
등록된 benchmark ID와 1~12회 반복만 브라우저에서 선택할 수 있고, 외부 저장소,
Python 실행 파일, kubeconfig 경로는 서버 운영자가 환경변수로 제공합니다. 진행 이벤트는
SSE로 표시되며 완료 후 정확도, 평균 TTD, 평균 step, 평균 reward와 Markdown/CSV 보고서를
확인할 수 있습니다. AutoGen은 의존성과 credential이 준비된 경우에만 선택할 수 있으며,
준비되지 않았으면 장애 주입 전 preflight에서 거부됩니다.

참조 화면에 보이는 F1, Precision, Recall, AUC를 임의로 만들지 않습니다. 현재 AIOpsLab
결과 스키마가 제공하는 정확도, 평균 TTD, 평균 action step, 평균 reward만 표시하며,
없는 값은 `—`로 남깁니다. 복구 성능 대시보드도 저장된 Job의 측정값만 집계하고 누락된
MTTR·Team Reward를 `0`으로 계산하지 않습니다. Recovery 결과의 Team Reward는 `evaluation.team_reward`만 사용하며, legacy report는 `—`로 표시합니다.

## 3. 설치와 실행

Control Plane의 프로젝트 기본 포트는 다른 로컬 서비스와 겹치지 않도록 `18180`입니다.
`PORT` 환경변수를 직접 지정하면 다른 포트로 덮어쓸 수 있습니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[ui,dev,autogen]"

export AIOPS_REPO_ROOT="$(pwd)"
export AIOPS_BIND_ADDRESS="127.0.0.1"
export PORT=18180

# AIOpsLab Benchmark를 웹에서 실제 실행할 때만 설정
export AIOPSLAB_ROOT="$HOME/geonhae/external/AIOpsLab"
export AIOPSLAB_PYTHON="$HOME/anaconda3/envs/aiopslab/bin/python"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

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

Ubuntu 서버에서 직접 브라우저를 실행할 때:

```text
http://127.0.0.1:18180/
```

Windows의 VS Code Remote SSH에서 확인할 때는 VS Code Ports 탭에서 원격 포트
`18180`을 로컬 포트로 전달합니다. 로컬 포트 번호는 VS Code가 선택하므로
`18181`로 고정하지 않습니다. 해당 포트의 `Open in Browser`를 사용합니다.

```text
VS Code Ports 탭의 `Forwarded Address`에 표시된 로컬 주소
```

정상적인 구성은 원격 포트가 `18180`으로 표시되고, 접속용 로컬 포트는 VS Code가
선택한 값으로 표시되는 것입니다. Ubuntu에서 실행하는 Control Plane의
`PORT=18180`은 그대로 유지합니다.

Windows PowerShell:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
python -m pip install -e ".[ui,dev,autogen]"
$env:AIOPS_REPO_ROOT=(Get-Location).Path
$env:AIOPS_BIND_ADDRESS="127.0.0.1"
$env:PORT="18180"
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
| `GET /api/benchmarks/aiopslab` | 등록 Benchmark와 runtime readiness 조회 |
| `POST /api/benchmarks/aiopslab/jobs` | AIOpsLab detection Job 생성 |
| `GET /api/benchmarks/aiopslab/jobs/{job_id}` | Benchmark 결과와 이벤트 조회 |
| `GET /api/benchmarks/aiopslab/jobs/{job_id}/events` | Benchmark SSE replay와 live stream |
| `POST /api/benchmarks/aiopslab/jobs/{job_id}/cancel` | Benchmark 취소 요청 |
| `GET /api/comparisons/recovery` | Recovery 비교 matrix와 Mock/Real 준비 상태 조회 |
| `POST /api/comparisons/recovery/jobs` | 4개 장애 × 3개 Action 비교 Job 생성 |
| `GET /api/comparisons/recovery/jobs/{job_id}` | 비교 결과, 정량 통계와 artifact URL 조회 |
| `GET /api/comparisons/recovery/jobs/{job_id}/events` | 비교 실험 SSE 진행·replay |
| `POST /api/comparisons/recovery/jobs/{job_id}/cancel` | 현재 treatment cleanup 후 취소 요청 |

FastAPI 문서:

```text
http://127.0.0.1:18180/api/docs
```

## 7. 연구 결과 해석

- `mock` 성공은 Agent·합의·Validator·UI 연결 검증입니다.
- `dry-run` 성공은 명령과 API 허용성 검증이며 실제 복구 성공이 아닙니다.
- `real` 결과는 Ubuntu 서버에서 Prometheus, Chaos Mesh, Kubernetes 연결과
  cleanup 산출물까지 확인한 경우에만 실제 실험 근거로 사용합니다.
- AutoGen fake-provider 자동 시험은 웹·Job·transcript 연결 검증이며 실제 모델 호출 결과가 아닙니다.
- AutoGen real 결과는 Ubuntu 서버에서 credential, 선택 모델, Controller provenance,
  transcript와 Kubernetes 산출물까지 확인한 경우에만 실제 비교 실험 근거로 사용합니다.
- AIOpsLab fake-executor 웹 시험은 Job/SSE/UI 연결 검증이며 실제 benchmark 결과가 아닙니다.
- AIOpsLab real 결과는 Ubuntu 서버에서 외부 AIOpsLab 저장소, 전용 Python 환경,
  kubeconfig와 생성 report를 확인한 경우에만 detection benchmark 근거로 사용합니다.
- AIOpsLab 탐지 지표와 Chaos Mesh 복구 지표는 같은 Control Plane에서 조회하더라도
  서로 다른 실험 유형으로 저장하고 해석합니다.
- Recovery Action Comparison의 `Mock`은 화면·통계·그래프 파이프라인 검증용
  합성 데이터이며 실제 성공률이나 MTTR 근거가 아닙니다.
- Recovery Action Comparison의 `Real`은 Ubuntu에서 Chaos Mesh 장애를 실제로
  주입하고 Prometheus와 Kubernetes 결과를 측정합니다. `CONFIRM_REAL_RUN=YES`,
  kubeconfig, Prometheus, latency query와 `EXECUTE REAL COMPARISON` 확인이 필요합니다.

## 8. 성능 화면 해석

| 지표 | 의미 | 주의점 |
| --- | --- | --- |
| 성공률 | 복구 성공 여부가 기록된 Job 중 성공 비율 | 결과가 없는 Job은 분모에서 제외 |
| 평균 MTTR | 복구 시간이 기록된 Job의 평균 초 | 누락값을 0초로 처리하지 않음 |
| 평균 Team Reward | `evaluation.team_reward`가 있는 Recovery Job의 평균 | legacy report와 평가 미완료 Job은 평균에서 제외 |
| Action별 성능 | `observe_only`, `rollout_restart`, `scale_out`별 집계 | 장애와 실행 모드를 함께 확인 |
| Controller별 성능 | deterministic/AutoGen과 mock/dry-run/real 조합별 집계 | Mock과 Real을 같은 실험 근거로 해석하지 않음 |

성능 대시보드는 새로운 값을 생성하지 않고 `GET /api/experiments`에서 조회한 저장 Job의
report를 집계합니다. 따라서 논문이나 발표에는 반드시 실행 모드, Controller, 장애
시나리오, 반복 횟수와 함께 제시합니다.
