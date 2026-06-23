# AIOps 4-Agent Kubernetes 자동화 연구

![AIOps 4-Agent 프로젝트 진행 구조 및 연결 흐름](docs/assets/project_architecture_overview.png)

이 저장소는 **4개의 AI Agent가 Kubernetes 기반 서비스 장애와 AI 응용 배포 조건을 판단하고, Python Validator와 Go Guard를 거쳐 안전한 Kubernetes Action만 실행하는 AIOps 자동화 연구 프로토타입**이다.

핵심은 API 서버 자체가 아니라 다음 흐름이다.

```text
AIOpsLab / Chaos Mesh 장애 주입
-> Prometheus / Kubernetes 상태 관측
-> AI-MCMP Coordinator
-> 4-Agent 판단
-> Action / Reward 교차 검증
-> Python Validator + Go Guard
-> kubectl dry-run 또는 real 실행
-> 실행 결과와 metric 저장 및 분석
```

## 먼저 볼 문서

처음 보는 사람은 아래 순서대로 보면 된다.

| 순서 | 문서 | 무엇을 나타내는가 |
| --- | --- | --- |
| 1 | [docs/core_submission_summary.md](docs/core_submission_summary.md) | 교수님/평가자에게 보여줄 핵심 요약 |
| 2 | [docs/README.md](docs/README.md) | `docs/` 폴더 전체 문서 지도 |
| 3 | [docs/design/research_task_integration_design.md](docs/design/research_task_integration_design.md) | 교수님 요청 연구와 ETRI/대학원 과제 요구사항의 관계 |
| 4 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) | 목적별 실행 코드 전체 모음 |
| 5 | [docs/experiments/service_operations_environment.md](docs/experiments/service_operations_environment.md) | Agent 중심 통합 파이프라인 실행 환경 |
| 6 | [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) | Chaos Mesh 장애별 복구 action 실험 |
| 7 | [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md) | 평균 복구 시간, 성공률, reward 그래프 분석 |

제출용 산출물은 아래 문서에 정리되어 있다.

| 산출물 | 문서 |
| --- | --- |
| 요구사항 정의서 | [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md), [docs/submission/requirements_definition.docx](docs/submission/requirements_definition.docx) |
| 기능/API 가이드 | [docs/submission/functional_api_guide.md](docs/submission/functional_api_guide.md) |
| OpenAPI 초안 | [docs/submission/openapi_agent_registry.yaml](docs/submission/openapi_agent_registry.yaml) |
| 설치 활용 가이드 | [docs/submission/install_and_run_guide.md](docs/submission/install_and_run_guide.md) |
| 시험 가이드 | [docs/submission/test_guide.md](docs/submission/test_guide.md) |
| 실행 코드 설명서 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) |

## 교수님 요청과 ETRI 요구사항 관계

이 프로젝트에는 두 가지 요구가 함께 들어 있다.

| 구분 | 요구 내용 | 현재 반영 |
| --- | --- | --- |
| 교수님 요청 연구 | 4개 Agent가 HA, 응용관리, 인프라, 비용 관점에서 action과 reward를 설계해야 함 | 4-Agent 판단 구조, action/reward 정책, reward 기반 action ranking |
| 교수님 요청 연구 | 장애별로 필요한 복구 action을 판단해야 함 | `pod-kill`, `cpu-stress`, `memory-stress`, `network-delay` 실험 |
| 교수님 요청 연구 | 안전하지 않은 Kubernetes 명령은 실행하지 않아야 함 | Python Validator + Go Guard 이중 검증 |
| ETRI 개발 가이드 | Go 언어 개발 필수 | [go/aiops-guard](go/aiops-guard) 구현 |
| ETRI 개발 가이드 | 최소 2종 이상 LLM/코딩 에이전트 활용 | OpenAI LLM + Codex 교차 검증 구조 문서화 |
| ETRI 개발 가이드 | 프레임워크/프롬프트 중심 문서 작성 | `docs/design/`, `docs/submission/` 문서화 |
| ETRI 개발 가이드 | 로그 및 에러 메시지 최대화 | `runs/` 결과, JSONL, CSV, SVG/PNG 통계 산출 |
| ETRI 과제 방향 | CPU/GPU VM 기반 AI 응용 배포/제어 | Ops LLM 선정, CPU/GPU 배치 추천, Deployment manifest dry-run |

정리하면, 교수님 요청은 **Agent 중심 AIOps 장애 복구 연구**이고, ETRI 요구사항은 **Go, LLM 교차 검증, AI 응용 배포/운용 산출물**이다. 이 저장소는 두 흐름을 하나의 Agent 기반 운영 파이프라인으로 연결한다.

## 현재 완료 상태

| 항목 | 상태 |
| --- | --- |
| 4-Agent 역할, action, reward 정책 | 완료 |
| AutoGen GroupChat 기반 Agent 경로 | 완료 |
| Prometheus metric 입력 | 완료 |
| Chaos Mesh 장애 4종 실험 | 완료 |
| AIOpsLab Hotel Reservation 탐지 benchmark | 완료 |
| Kubernetes dry-run / real 실행 | 완료 |
| Python Validator 안전 검증 | 완료 |
| Go Guard 이중 검증 | 완료 |
| Agent 등록 관리 프로토타입 | 완료 |
| Ops LLM 선정 CLI | 완료 |
| CPU/GPU VM 배치 추천 CLI | 완료 |
| AI 서비스 배포 manifest 생성 | 완료 |
| Kubernetes server-side dry-run 검증 | 완료 |
| 통합 CLI `run-service-operations` | 완료 |
| FakeEvidenceProvider 기반 autonomous mock/test evidence loop | 완료 |
| KubernetesEvidenceProvider 기반 제한적 deployment/pod snapshot 수집 | 완료 |
| Multi-candidate recovery action 생성 | 완료 |
| Infra/Cost Agent 후보별 평가 | 완료 |
| Recovery Monitor와 실패 후 재계획 | 완료 |
| 폐루프 autonomous CLI `autonomous-run` | 완료 |
| Reward 정책별 action ranking 실험 | 완료 |
| 정량 그래프/통계 분석 | 완료 |
| Go Echo HTTP API 서버 + Swagger UI | 이번 범위 제외 |
| Prometheus metric, log enrichment, real-cluster evidence fusion | 후속 확장 |
| 실제 AWS/Azure/GCP 멀티 클라우드 연동 | ETRI VM 확보 후 후속 진행 |
| 실제 AI 서비스 Pod 상시 배포 운영 | 현재는 manifest/dry-run 중심, 후속 진행 |

## 4-Agent 역할

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 자율 복구 필요성 평가 |
| `AIApplicationManagementAgent` | 응용 배포/복구 action 제안, Kubernetes 제어 절차 관리 |
| `AISemiconductorInfraOpsAgent` | CPU/GPU/NPU 자원 수용성, replica 증가, VM 배치 가능성 검증 |
| `CostOptimizationAgent` | 비용 증가, 과잉 action, 비용 우선 정책 검증 |

Agent 등록 정보는 [config/agent_registry.json](config/agent_registry.json)에 있다.

## 실행 환경

| 환경 | 용도 |
| --- | --- |
| `base` | Anaconda 기본 환경 |
| `aiops_research` | 우리 프로젝트 실행, pytest, 4-Agent CLI, Go Guard |
| `aiopslab` | 외부 AIOpsLab 공식 코드 실행 |

보통 우리 프로젝트 작업은 다음 환경에서 실행한다.

```bash
conda activate aiops_research
cd ~/geonhae/aiops_research
```

## 빠른 실행 코드

자세한 실행 코드는 [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md)에 목적별로 정리되어 있다. README에는 대표 명령만 둔다.

### 1. 최신 코드 반영

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"
```

### 2. 전체 테스트

```bash
python -m pytest
```

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
```

### 3. Ops LLM 선정

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy quality_first
```

대표 결과:

```text
selected_model = gpt-5.5
```

### 4. CPU/GPU VM 배치 추천

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

대표 결과:

```text
selected_resource = gpu-vm-l4
action = deploy_on_gpu_vm
```

### 5. Agent 중심 통합 파이프라인

```bash
aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --mode dry-run \
  --guard-backend go
```

이 명령은 다음을 한 번에 연결한다.

```text
Ops LLM 선정
-> CPU/GPU VM 배치 계획
-> Kubernetes Deployment manifest 생성
-> manifest dry-run 검증
-> Application / Infrastructure / Cost Agent 검토
-> Python Validator + Go Guard 실행 준비
```

### 6. 폐루프 자율 4-Agent 실행

아래 명령은 실제 클러스터 변경 없이 `FakeEvidenceProvider` 기반 fake evidence로 폐루프 autonomous flow를 검증한다. 이 결과는 구조/안전성 검증용 mock 결과이며, Chaos Mesh/Prometheus/Kubernetes real 실험 결과와 구분해서 사용해야 한다.

```bash
aiops-k8s-agents autonomous-run \
  --mode mock \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

이 명령은 다음을 한 번에 수행한다.

```text
Evidence 수집
-> HA Agent evidence 기반 진단
-> Application Agent 후보 action 3종 생성
-> Infra/Cost Agent 후보별 평가
-> Coordinator 최종 action 선택
-> Python Validator + Guard backend 검증
-> Kubernetes action 실행 또는 mock 검증
-> Recovery Monitor 복구 판정
-> 실패 시 다음 후보로 재계획
```

중요한 점은 `autonomous-run`에서도 Agent가 임의의 `kubectl` 문자열을 직접 실행하지 않는다는 것이다. 모든 action은 구조화된 `RecoveryAction`으로 생성되고, 실행 전에는 반드시 Python Validator와 선택한 guard backend를 통과한다.

Evidence Collector 기반 autonomous flow는 mock/test 환경에서 동작하도록 구현되어 있으며, `KubernetesEvidenceProvider`는 deployment/pod snapshot 중심의 제한적 provider로 제공된다. Prometheus metric, log enrichment, full real-cluster evidence fusion은 후속 확장 단계로 분리한다.

### 7. Kubernetes real 장애 복구 실험

Prometheus port-forward는 별도 터미널에서 켜둔다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

실험 터미널:

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
export PROM=http://127.0.0.1:9091
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

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

### 8. 정량 그래프/통계 생성

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

aiops-k8s-agents summarize-recovery-statistics \
  --input "${LATEST}outcomes.jsonl" \
  --output-dir "${LATEST}statistics"
```

대표 산출물:

```text
statistics/quantitative_summary.md
statistics/scenario_action_statistics.csv
statistics/policy_reward_statistics.csv
statistics/mean_recovery_seconds_by_action.svg
statistics/success_rate_by_action.svg
statistics/reward_by_policy.svg
```

## 실제 장애 시나리오

| 장애 | 도구 | 대상 | 설명 |
| --- | --- | --- | --- |
| `pod-kill` | Chaos Mesh | `paymentservice` | Pod를 제거해 Kubernetes 복구 동작 확인 |
| `cpu-stress` | Chaos Mesh | `paymentservice` | CPU 부하를 주입해 action 선택 비교 |
| `memory-stress` | Chaos Mesh | `checkoutservice` | 메모리 부하와 restart/rollout 판단 확인 |
| `network-delay` | Chaos Mesh + blackbox exporter | `paymentservice` | 지연시간 증가를 Prometheus metric으로 관측 |

초기의 `CPU 95%` 입력은 mock/smoke test용 시나리오다. 현재 연구 결과의 중심은 위의 실제 Chaos Mesh/AIOpsLab 기반 실험이다.

## 문서 지도

### 제출용 문서

| 문서 | 내용 |
| --- | --- |
| [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md) | 요구사항 정의서 |
| [docs/submission/functional_api_guide.md](docs/submission/functional_api_guide.md) | 기능/API 사용 가이드 |
| [docs/submission/install_and_run_guide.md](docs/submission/install_and_run_guide.md) | 설치 및 실행 가이드 |
| [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) | 실행 코드 설명서 |
| [docs/submission/test_guide.md](docs/submission/test_guide.md) | 시험 검증 가이드 |
| [docs/submission/openapi_agent_registry.yaml](docs/submission/openapi_agent_registry.yaml) | Agent 등록 관리 OpenAPI 초안 |

### 설계 문서

| 문서 | 내용 |
| --- | --- |
| [docs/design/research_task_integration_design.md](docs/design/research_task_integration_design.md) | 교수님 요청 연구와 ETRI 과제 요구사항 통합 설계 |
| [docs/design/agent_registry_guide.md](docs/design/agent_registry_guide.md) | Agent 등록 관리 구조 |
| [docs/design/agent_action_reward_policy.md](docs/design/agent_action_reward_policy.md) | Agent별 action/reward 정책 |
| [docs/design/go_and_llm_cross_validation.md](docs/design/go_and_llm_cross_validation.md) | Go Guard와 LLM/코딩 Agent 교차 검증 |
| [docs/design/ops_llm_selection_guide.md](docs/design/ops_llm_selection_guide.md) | Ops 분석 시험 및 최적 LLM 선정 |
| [docs/design/inference_optimization_guide.md](docs/design/inference_optimization_guide.md) | CPU/GPU VM 기반 추론 배치 추천 |
| [docs/design/ai_application_deployment_strategy.md](docs/design/ai_application_deployment_strategy.md) | AI 응용 배포/제어 추론 최적화 전략 |
| [docs/design/autogen_groupchat.md](docs/design/autogen_groupchat.md) | AutoGen GroupChat 구조 |

### 실험 문서

| 문서 | 내용 |
| --- | --- |
| [docs/experiments/service_operations_environment.md](docs/experiments/service_operations_environment.md) | Agent 중심 통합 파이프라인 실행 환경 |
| [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) | Chaos Mesh 장애별 recovery action 실험 |
| [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md) | 평균 복구 시간, 성공률, reward 그래프 분석 |
| [docs/experiments/full_stack_experiment_guide.md](docs/experiments/full_stack_experiment_guide.md) | full-stack 실험 환경 구성 |
| [docs/experiments/experiment_commands.md](docs/experiments/experiment_commands.md) | 전체 실험 명령어 기록 |
| [docs/experiments/server_migration_runbook.md](docs/experiments/server_migration_runbook.md) | 서버 이관 및 실행 절차 |

### 보관 문서

| 문서 | 내용 |
| --- | --- |
| [docs/archive/first_stage_research_completion.md](docs/archive/first_stage_research_completion.md) | 1차 연구 완료 범위 정리 |
| [docs/archive/llm_cross_validation_report_20260616.md](docs/archive/llm_cross_validation_report_20260616.md) | LLM/코딩 Agent 교차 검증 기록 |
| [docs/archive/prometheus_adapter.md](docs/archive/prometheus_adapter.md) | Prometheus adapter 중간 설명 |
| [docs/archive/research_reference_integration.md](docs/archive/research_reference_integration.md) | 참고 PPT/연구자료 반영 기록 |

## 현재 연구 단계

현재 단계는 **1차 통합 프로토타입 구현 및 실험 검증 완료**로 볼 수 있다.

완료된 핵심:

- 4-Agent 구조 구현
- 실제 장애 주입과 metric 관측
- Kubernetes real action 실행
- Python Validator + Go Guard 이중 안전 검증
- Agent 등록 관리
- Ops LLM 선정
- CPU/GPU VM 기반 추론 배치 추천
- AI 서비스 Deployment manifest 생성 및 server-side dry-run 검증
- FakeEvidenceProvider 기반 autonomous mock/test loop
- KubernetesEvidenceProvider 기반 제한적 deployment/pod snapshot evidence 수집
- Reward 정책 변화에 따른 장애별 action ranking 비교
- 정량 그래프/통계 분석

후속 확장:

- Prometheus metric, log enrichment, full real-cluster evidence fusion
- 실제 AWS/Azure/GCP 멀티 클라우드 VM 연동
- 실제 GPU/NPU 스케줄링과 모델 추론 서비스 연동
- AutoGen multi-round real action 선택
- single-agent baseline 비교
- Agent 제거 ablation 실험
- Go Echo HTTP API 서버와 Swagger UI

## Latest Repository Improvement Notes

이번 개선은 전체 연구 목표를 바꾸지 않고, 기존 4-Agent AIOps 파이프라인의 약점을 보완하는 방향으로 반영되었다.

| 개선 항목 | 반영 위치 |
| --- | --- |
| 고정 규칙 기반 Agent 판단 완화 | `config/agent_decision_policy.json`, `src/aiops_k8s_agents/ha_agent.py`, `src/aiops_k8s_agents/application_agent.py` |
| metric/severity 기반 action 선택 | CPU/memory는 scale-out, restart/latency/network 계열은 rollout restart 중심으로 정책화 |
| Ops LLM benchmark 출처 명시 | `config/ops_llm_benchmark.json`의 `metadata` 필드 |
| LLM benchmark 재생성 보조 스크립트 | `scripts/build_ops_llm_benchmark_from_runs.py` |
| AutoGen 설명 보정 | [docs/design/autogen_groupchat.md](docs/design/autogen_groupchat.md) |
| Ops LLM 선정 설명 보정 | [docs/design/ops_llm_selection_guide.md](docs/design/ops_llm_selection_guide.md) |

주의할 점은 현재 AutoGen 경로가 완전 자율 장시간 토론 시스템이 아니라, structured output과 validator로 제한된 multi-agent prototype이라는 것이다. LLM이 생성한 자유 텍스트 명령은 직접 실행하지 않으며, 최종 Kubernetes action은 Python Validator와 Go Guard를 통과해야 한다.
