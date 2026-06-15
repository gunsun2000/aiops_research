# AIOps 4-Agent Kubernetes 자동화 연구

Kubernetes 마이크로서비스 환경에서 실제 장애를 관측하고, 역할이 다른 4개 Agent가 복구 Action을 평가한 뒤 안전하게 실행하는 AIOps 연구 프로젝트입니다.

현재 프로젝트는 아이디어나 Mock 단계가 아닙니다. 연구실 서버의 개인용 kind 클러스터에서 AIOpsLab, Online Boutique, Chaos Mesh, full Prometheus를 연결하고 실제 Kubernetes 제어 실험까지 수행했습니다.

## 한눈에 보는 현재 결과

| 실험 | 실행 환경 | 결과 |
| --- | --- | ---: |
| Python 자동 테스트 | 로컬·서버 | `92 passed` |
| AIOpsLab Hotel Reservation 탐지 | 서버 kind | Correct detection `12/12` |
| 실제 장애별 Action 파일럿 | Chaos Mesh + Kubernetes real | 유효 측정·복구 `12/12` |
| 실제 장애별 Action 본 실험 | 4장애 × 3Action × 3회 | 유효 측정·복구 `36/36` |

본 실험 결과는 다음 파일에 저장됐습니다.

```text
runs/recovery-action-pilot/20260615_123017/outcomes.jsonl
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.md
```

`runs/`는 서버에서 생성되는 실험 결과 디렉터리이므로 Git 저장소에는 없을 수 있습니다.

## 연구 시스템

```text
AIOpsLab / Chaos Mesh 실제 장애
-> Prometheus 및 Kubernetes 상태 관측
-> HA·응용관리·인프라·비용 Agent 평가
-> Reward 정책에 따른 후보 Action 순위 계산
-> Validator 안전 검증
-> kubectl real Action 실행
-> 복구 상태와 Metric 재측정
-> JSONL·CSV·Markdown 결과 저장
```

### 4개 Agent의 역할

| Agent | 주요 판단 |
| --- | --- |
| HA 지원 Agent | 장애 복구 성공과 서비스 가용성 |
| 응용관리 Agent | 복구 속도와 애플리케이션 상태 개선 |
| 인프라 운용 Agent | Replica·노드·가속기 자원 부담 |
| 비용 최적화 Agent | 추가 자원과 불필요한 Action 비용 |

Agent 판단을 모으는 AI-MCMP Coordinator와, 허용된 Action만 실행하는 Validator가 함께 동작합니다.

## 실제 장애 및 Action

### 장애 4종

| 장애 | 대상 | 관측값 |
| --- | --- | --- |
| `pod-kill` | `paymentservice` | Pod UID 교체 및 가용 Replica |
| `cpu-stress` | `paymentservice` | Container CPU 사용량 |
| `memory-stress` | `checkoutservice` | Memory working set |
| `network-delay` | `paymentservice` | Blackbox TCP probe 지연시간 |

### 후보 Action 3종

| Action | 실행 내용 |
| --- | --- |
| `observe_only` | Kubernetes 자체 복구를 관찰하고 변경하지 않음 |
| `rollout_restart` | 대상 Deployment를 안전하게 재시작 |
| `scale_out` | Replica를 1개에서 3개로 확장 |

## 36회 본 실험 결과

다음 표는 동일한 실제 측정 결과에 Reward 가중치를 다르게 적용했을 때 선택된 Action입니다.

| Reward 정책 | CPU stress | Memory stress | Network delay | Pod kill |
| --- | --- | --- | --- | --- |
| Balanced | 관찰 | 재시작 | 재시작 | 관찰 |
| HA 우선 | 관찰 | 재시작 | 재시작 | 관찰 |
| 비용 우선 | 관찰 | 관찰 | 관찰 | 관찰 |
| 인프라 우선 | 관찰 | 재시작 | 재시작 | 관찰 |

이 결과로 확인한 내용은 다음과 같습니다.

1. 장애 유형에 따라 높은 Reward를 받는 Action이 달라집니다.
2. 동일한 장애라도 Reward 정책에 따라 선택 Action이 달라질 수 있습니다.
3. 짧은 CPU stress와 Pod kill에서는 Kubernetes 자체 복구를 기다리는 것이 과잉 제어보다 유리했습니다.
4. Memory stress와 Network delay에서는 Balanced·HA·Infra 정책이 `rollout_restart`를 선택했습니다.

Reward는 강화학습의 학습 보상이 아닙니다. 실제 복구 결과를 HA, 응용관리, 인프라, 비용 관점에서 재평가하는 정책 점수입니다.

## 중요한 실험 구분

| 경로 | 상태 | 의미 |
| --- | --- | --- |
| Deterministic 4-Agent | 구현·real 실험 완료 | 구조화된 정책으로 실제 장애와 Action을 비교 |
| AutoGen GroupChat | 구현·Mock/Dry-run 검증 완료 | OpenAI LLM 기반 4-Agent 대화 및 구조화 응답 |
| AutoGen GroupChat real Action 선택 | 미완료 | 실제 Chaos Mesh 장애를 보고 LLM 대화가 Action을 직접 선택하는 비교 실험 |

따라서 `36/36` 결과는 실제 Chaos Mesh·Prometheus·Kubernetes 실험이지만, AutoGen 자유 대화가 Action을 직접 선택한 결과는 아닙니다.

CPU 95% 입력 시나리오는 명령 생성과 Validator를 빠르게 확인하는 선택적 Smoke Test이며, 현재 연구의 실제 장애 결과에는 포함하지 않습니다.

## 서버에서 가장 많이 사용하는 명령

### 1. 환경 준비와 코드 검증

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

python -m pytest
kubectl get nodes
```

### 2. Prometheus 연결 확인

별도 터미널에서 다음 명령을 계속 실행합니다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

실험 터미널에서는 다음을 설정합니다.

```bash
export PROM=http://127.0.0.1:9091
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
curl -sS "$PROM/-/ready"
```

### 3. 12회 파일럿 또는 36회 본 실험

```bash
MODE=real \
REPETITIONS=1 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

`REPETITIONS=3`으로 바꾸면 36회 본 실험을 수행합니다.

## 현재 연구 단계

| 구분 | 상태 |
| --- | --- |
| 4-Agent 시스템 설계와 통합 가능성 검증 | 완료 |
| AIOpsLab 자동 탐지 반복 실험 | 완료 |
| 실제 장애별 Action 비교 | 완료 |
| Reward 정책 변화 비교 | 완료 |
| 36회 반복 real 실험 | 완료 |
| 평균·표준편차·그래프와 통계 검정 | 다음 작업 |
| Single-Agent baseline 비교 | 미완료 |
| Agent 제거 Ablation | 미완료 |
| AutoGen multi-round real 제어 | 미완료 |
| GPU/NPU 실제 스케줄링 최적화 | 향후 확장 |

현재 상태는 **1차 시스템 연구 완료 + 2차 정량 비교 실험의 핵심 항목 완료**로 정리할 수 있습니다.

## 문서 안내

| 문서 | 내용 |
| --- | --- |
| [설치 및 실행 가이드](docs/install_and_run_guide.md) | `base`, `aiops_research`, `aiopslab` 환경과 설치 방법 |
| [현재 연구 완료 범위](docs/first_stage_research_completion.md) | 완료·미완료 항목과 실험 근거 |
| [실제 장애별 Action 실험](docs/recovery_action_experiment_guide.md) | 실험 설계, 실행 방법, 36회 결과 해석 |
| [전체 실험 명령어](docs/experiment_commands.md) | 서버·로컬 명령어 모음 |
| [AutoGen GroupChat](docs/autogen_groupchat.md) | LLM 기반 Agent 대화 구조 |
| [Agent Action/Reward 정책](docs/agent_action_reward_policy.md) | Agent별 Action과 Reward 정의 |
| [Full-stack 실험 가이드](docs/full_stack_experiment_guide.md) | Online Boutique·Prometheus·Chaos Mesh 환경 |
| [서버 이관 Runbook](docs/server_migration_runbook.md) | 서버 환경 구성과 이관 절차 |
