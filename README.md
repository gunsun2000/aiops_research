# AIOps 4-Agent Kubernetes 자동화 연구

이 프로젝트는 Kubernetes 기반 서비스 장애 상황에서 4개의 AI Agent가 서로 다른 운영 관점을 나누어 판단하고, 검증된 action만 안전하게 실행하는 AIOps 연구 프로토타입입니다.

현재 중심은 **AIOpsLab 자체 개발**이 아니라, AIOpsLab/Chaos Mesh/Prometheus/Kubernetes 환경 위에서 동작하는 **4-Agent 서비스 제어 및 관리 자동화 구조**입니다.

## 현재까지 완료된 핵심

| 구분 | 상태 |
| --- | --- |
| 4-Agent 역할, action, reward 정책 | 완료 |
| AutoGen GroupChat 기반 Agent 대화 경로 | 완료 |
| Prometheus metric 입력 | 완료 |
| Chaos Mesh 장애 4종 실험 | 완료 |
| AIOpsLab Hotel Reservation 탐지 benchmark | 완료 |
| Kubernetes dry-run/real 실행 | 완료 |
| Go 언어 기반 최종 action guard | 완료 |
| 2종 코딩/LLM 관점 교차 검증 문서 | 완료 |
| Agent 등록 관리 프로토타입 | 완료 |
| CPU/GPU VM 기반 추론 배치 최적화 프로토타입 | 완료 |
| Reward 정책 변화와 장애별 action ranking 실험 | 완료 |

## 전체 구조

```text
AIOpsLab / Chaos Mesh 장애
-> Prometheus / Kubernetes 상태 관측
-> AI-MCMP Coordinator
-> 4-Agent 판단
   - HA 지원 Agent
   - 응용관리 Agent
   - AI반도체 인프라 운용 Agent
   - 비용 최적화 Agent
-> Action / Reward 교차 검증
-> Python Validator + Go Guard
-> kubectl dry-run 또는 real 실행
-> before / after 상태와 metric 저장
```

## 4-Agent 역할

| Agent | 담당 내용 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 자율 복구 필요성 평가 |
| `AIApplicationManagementAgent` | 응용 배포, 복구 action 선택, Kubernetes 제어 절차 관리 |
| `AISemiconductorInfraOpsAgent` | CPU/GPU/NPU 자원 수용성, replica 증가, VM 배치 가능성 검증 |
| `CostOptimizationAgent` | 자원 증가 비용, 과잉 action, 비용 우선 정책 검증 |

Agent 정의 파일:

```text
config/agent_registry.json
```

## 실행 환경 구분

| 환경 | 용도 |
| --- | --- |
| `base` | Anaconda 기본 환경 |
| `aiops_research` | 우리 프로젝트 실행, pytest, 4-Agent CLI, Go guard |
| `aiopslab` | 외부 AIOpsLab 공식 코드 실행 |

보통 우리 프로젝트 작업은 다음 환경에서 한다.

```bash
conda activate aiops_research
cd ~/geonhae/aiops_research
```

## 설치 및 테스트

### 서버

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"
python -m pytest
```

Go guard 테스트:

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
go run ./cmd/aiops-guard --input ../../examples/go_guard_scale_action.json
```

### Windows 로컬

```powershell
cd C:\Users\geonhae\Documents\aiops_research
.\.venv\Scripts\python.exe -m pytest
```

## 기본 명령

### 1. Agent 등록 관리

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json
```

```bash
aiops-k8s-agents validate-agent-action \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent \
  --action app_scale_deployment
```

### 2. CPU/GPU VM 추론 배치 추천

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

기대 결과:

```text
selected_resource = gpu-vm-l4
action = deploy_on_gpu_vm
```

가벼운 텍스트 모델:

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload text-classifier
```

기대 결과:

```text
selected_resource = cpu-vm-standard
action = deploy_on_cpu_vm
```

### 3. Kubernetes recovery action 실행

```bash
aiops-k8s-agents execute-recovery-action \
  --mode real \
  --guard-backend go \
  --action rollout_restart \
  --namespace online-boutique \
  --deployment paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

## 서버 real 실험

전제:

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
kubectl get nodes
```

Prometheus port-forward는 별도 터미널에서 계속 켜둔다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

실험 터미널:

```bash
export PROM=http://127.0.0.1:9091
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
curl -sS "$PROM/-/ready"
```

36회 recovery action 실험:

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

결과 확인:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
wc -l "$LATEST/outcomes.jsonl"
cat "$LATEST/analysis/reward_policy_comparison.md"
```

성공 기준:

```text
36 outcomes.jsonl
```

## 실제 장애 시나리오

| 장애 | 도구 | 대상 |
| --- | --- | --- |
| `pod-kill` | Chaos Mesh | `paymentservice` |
| `cpu-stress` | Chaos Mesh | `paymentservice` |
| `memory-stress` | Chaos Mesh | `checkoutservice` |
| `network-delay` | Chaos Mesh + blackbox exporter | `paymentservice` |

CPU 95% 입력은 초기 smoke test용 mock 시나리오다. 현재 연구 결과의 중심은 위의 실제 Chaos Mesh/AIOpsLab 기반 실험이다.

## 주요 문서

| 문서 | 내용 |
| --- | --- |
| `docs/requirements_definition.md` | 요구사항 정의서 |
| `docs/agent_registry_guide.md` | AI Agent 등록 관리 가이드 |
| `docs/inference_optimization_guide.md` | CPU/GPU VM 추론 최적화 가이드 |
| `docs/functional_api_guide.md` | 기능/API 사용 가이드 |
| `docs/test_guide.md` | 시험 검증 가이드 |
| `docs/go_and_llm_cross_validation.md` | Go 언어 및 LLM 교차 검증 정리 |
| `docs/recovery_action_experiment_guide.md` | 장애별 action/reward 실험 가이드 |
| `docs/first_stage_research_completion.md` | 1차 연구 완료 범위 정리 |

## 현재 연구 단계

현재 단계는 **1차 통합 프로토타입 구현 및 실험 검증 완료**로 볼 수 있다.

완료된 내용:

- 4-Agent 구조 구현
- 실제 장애 주입과 metric 관측
- Kubernetes real action 실행
- Go guard 기반 최종 action 검증
- Agent 등록 관리
- CPU/GPU VM 기반 추론 최적화 정책
- Reward 정책 변화에 따른 장애별 action ranking 비교

다음 연구 확장:

- single-agent baseline 비교
- Agent 제거 ablation 실험
- AutoGen multi-round real action 선택
- 실제 GPU/NPU 스케줄링과 모델 추론 서비스 연동
- 통계 검정과 그래프 기반 정량 평가

## 추가 완료 항목: LLM 선정 및 AI 응용 배포/제어 전략

다음 두 항목도 코드, CLI, 테스트, 문서 산출물로 정리했다.

| 개발 항목 | 완료 산출물 |
| --- | --- |
| Ops 분석 시험 및 최적 LLM 선정 | `config/ops_llm_benchmark.json`, `docs/ops_llm_selection_guide.md`, `aiops-k8s-agents select-ops-llm` |
| CPU/GPU VM 기반 AI 응용 배포/제어 추론 최적화 전략 | `config/inference_optimization.json`, `docs/ai_application_deployment_strategy.md`, `aiops-k8s-agents plan-inference-deployment` |

실행 명령:

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy quality_first
```

```bash
aiops-k8s-agents plan-inference-deployment \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```
