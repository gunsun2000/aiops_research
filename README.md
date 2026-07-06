# AIOps 4-Agent Kubernetes 자동화 연구

![AIOps 4-Agent 프로젝트 진행 구조 및 연결 흐름](docs/assets/architecture_overview.png)

이 저장소는 **4개의 AI Agent가 Kubernetes 기반 서비스 장애를 판단하고, Action/Reward 정책과 Python Validator를 거쳐 안전한 Kubernetes 복구 Action만 실행하는 AIOps 자동화 연구 프로토타입**이다.

핵심은 API 서버 자체가 아니라 다음 흐름이다.

```text
AIOpsLab / Chaos Mesh 장애 주입
-> Prometheus / Kubernetes 상태 관측
-> AI-MCMP Coordinator
-> 4-Agent 판단
-> Action / Reward 교차 검증
-> Python Validator
-> kubectl dry-run 또는 real 실행
-> 실행 결과와 metric 저장 및 분석
```

## 먼저 볼 문서

처음 보는 사람은 아래 순서대로 보면 된다.

| 순서 | 문서 | 무엇을 나타내는가 |
| --- | --- | --- |
| 1 | [docs/core_submission_summary.md](docs/core_submission_summary.md) | 대학원 연구/평가자에게 보여줄 핵심 요약 |
| 2 | [docs/README.md](docs/README.md) | `docs/` 폴더 전체 문서 지도 |
| 3 | [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) | Chaos Mesh 장애별 복구 action 실험 |
| 4 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) | 목적별 실행 코드 전체 모음 |
| 5 | [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md) | 평균 복구 시간, 성공률, reward 그래프 분석 |

연구 재현과 결과 정리에 필요한 문서는 아래에 정리되어 있다.

| 문서 성격 | 문서 |
| --- | --- |
| 요구사항 정의서 | [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md), [docs/submission/requirements_definition.docx](docs/submission/requirements_definition.docx) |
| 설치 활용 가이드 | [docs/submission/install_and_run_guide.md](docs/submission/install_and_run_guide.md) |
| 시험 가이드 | [docs/submission/test_guide.md](docs/submission/test_guide.md) |
| 실행 코드 설명서 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) |

## 대학원 연구 중심 정리

현재 저장소의 중심은 **4-Agent 기반 AIOps 장애 감시/복구 자동화 연구**다. 별도 과제 대응 과정에서 추가했던 기능 중 연구에 도움이 되는 요소만 보조 모듈로 남기고, AI App 배포/CPU-GPU VM 배치/API 산출물 성격이 강한 요소는 archive 또는 별도 과제에서 다룬다.

| 구분 | 이 프로젝트에서의 처리 |
| --- | --- |
| 4-Agent 장애 판단 | 연구 본체로 유지 |
| Action/Reward 정책 | 연구 본체로 유지 |
| AIOpsLab / Chaos Mesh / Prometheus / Kubernetes 실험 | 연구 본체로 유지 |
| Python Validator | 기본 안전 검증기로 유지 |
| Agent Registry | 4-Agent 역할과 허용 action 관리용으로 유지 |
| Go Guard | 선택적 이중 검증 모듈로 보관 |
| Ops LLM 선정 | 본문에서 제외하고 보조/보관 기능으로 분리 |
| CPU/GPU VM 기반 AI 응용 배포 | 별도 과제 성격으로 분리 |
| Swagger/API/멀티클라우드 설명 | README 본문에서 제외 |

## 현재 핵심 구성

README에서는 긴 완료 체크리스트를 두지 않고, 현재 저장소가 어떤 흐름으로 동작하는지만 요약한다. 세부 구현 범위와 산출물 기준은 [docs/core_submission_summary.md](docs/core_submission_summary.md), [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md), [docs/archive/first_stage_research_completion.md](docs/archive/first_stage_research_completion.md)에 분리했다.

| 계층 | 포함 내용 |
| --- | --- |
| Agent 판단 계층 | AI-MCMP Coordinator, HA/Application/Infra/Cost 4-Agent, action/reward 정책 |
| 관측 및 실험 계층 | AIOpsLab, Chaos Mesh, Prometheus, Kubernetes 상태 관측 |
| 안전 실행 계층 | Python Validator, kubectl mock/dry-run/real 실행, 선택적 Go Guard |
| 연구 보조 계층 | Agent Registry, AutoGen mock/dry-run 경로, 실험 재현 문서 |
| 결과 분석 계층 | JSON/JSONL 로그, CSV, Markdown 요약, PNG/SVG 정량 그래프 |

## 4-Agent 역할

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 자율 복구 필요성 평가 |
| `AIApplicationManagementAgent` | 응용 배포/복구 action 제안, Kubernetes 제어 절차 관리 |
| `AISemiconductorInfraOpsAgent` | 현재 연구에서는 Kubernetes replica/deployment 안전성과 인프라 수용 가능성을 검토한다. 실제 GPU/NPU 클러스터 스케줄링은 후속 확장이다. |
| `CostOptimizationAgent` | 비용 증가, 과잉 action, 비용 우선 정책 검증 |

Agent 등록 정보는 [config/agent_registry.json](config/agent_registry.json)에 있다.

## 실행 환경

| 환경 | 용도 |
| --- | --- |
| `base` | Anaconda 기본 환경 |
| `aiops_research` | 우리 프로젝트 실행, pytest, 4-Agent CLI |
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

선택적으로 Go Guard까지 확인할 때만 다음을 실행한다.

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
```

### 3. 폐루프 자율 4-Agent 실행

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

중요한 점은 `autonomous-run`에서도 Agent가 임의의 `kubectl` 문자열을 직접 실행하지 않는다는 것이다. 본 프로젝트의 자율성은 Agent의 evidence 기반 판단, 후보 action 생성, 복구 모니터링, 실패 시 재계획에 해당한다. 실제 Kubernetes 실행은 구조화된 `RecoveryAction`으로 제한되며, 실행 전에는 반드시 Python Validator와 선택한 guard backend를 통과한다.

`observe_only`는 Kubernetes 상태를 변경하는 복구 action이 아니다. 이 action은 read-only observation, 즉 추가 관찰과 Kubernetes 자체 복구 여부 확인을 의미하며, 리포트에는 `state_changed: false`, `action_effect_type: "read_only_observation"`으로 표시된다. `rollout_restart`와 `scale_out`은 실제 상태 변경 action으로 구분한다.

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

### 연구 재현 문서

| 문서 | 내용 |
| --- | --- |
| [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md) | 요구사항 정의서 |
| [docs/submission/install_and_run_guide.md](docs/submission/install_and_run_guide.md) | 설치 및 실행 가이드 |
| [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) | 실행 코드 설명서 |
| [docs/submission/test_guide.md](docs/submission/test_guide.md) | 시험 검증 가이드 |

### 설계 문서

| 문서 | 내용 |
| --- | --- |
| [docs/design/agent_registry_guide.md](docs/design/agent_registry_guide.md) | Agent 등록 관리 구조 |
| [docs/design/agent_action_reward_policy.md](docs/design/agent_action_reward_policy.md) | Agent별 action/reward 정책 |
| [docs/design/autogen_groupchat.md](docs/design/autogen_groupchat.md) | AutoGen GroupChat 구조 |

### 실험 문서

| 문서 | 내용 |
| --- | --- |
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
| [docs/archive/etri_extension.md](docs/archive/etri_extension.md) | 별도 과제 성격 확장 기능 보관 설명 |

## 현재 연구 단계

현재 저장소는 **4-Agent AIOps 장애 감시/복구 연구를 중심으로, 비교 실험과 정량 분석을 확장하는 단계**다. README에는 완료 항목을 길게 반복하지 않고, 세부 결과는 문서별로 분리한다.

| 보고 싶은 내용 | 문서 |
| --- | --- |
| 1차 연구 범위 | [docs/archive/first_stage_research_completion.md](docs/archive/first_stage_research_completion.md) |
| 실행 코드 전체 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) |
| 시험 절차 | [docs/submission/test_guide.md](docs/submission/test_guide.md) |
| 실험 결과 해석 | [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) |

다음 확장:

- Prometheus metric, log enrichment, full real-cluster evidence fusion
- AutoGen multi-round real action 선택
- single-agent baseline 비교
- Agent 제거 ablation 실험

## Latest Repository Improvement Notes

이번 개선은 전체 연구 목표를 바꾸지 않고, 기존 4-Agent AIOps 파이프라인의 약점을 보완하는 방향으로 반영되었다.

| 개선 항목 | 반영 위치 |
| --- | --- |
| 고정 규칙 기반 Agent 판단 완화 | `config/agent_decision_policy.json`, `src/aiops_k8s_agents/ha_agent.py`, `src/aiops_k8s_agents/application_agent.py` |
| metric/severity 기반 action 선택 | CPU/memory는 scale-out, restart/latency/network 계열은 rollout restart 중심으로 정책화 |
| AutoGen 설명 보정 | [docs/design/autogen_groupchat.md](docs/design/autogen_groupchat.md) |

주의할 점은 현재 AutoGen 경로가 완전 자율 장시간 토론 시스템이 아니라, structured output과 validator로 제한된 multi-agent prototype이라는 것이다. LLM이 생성한 자유 텍스트 명령은 직접 실행하지 않으며, 최종 Kubernetes action은 Python Validator를 통과해야 한다. Go Guard는 대학원 연구 본체가 아니라 선택적 이중 검증 모듈로 보관한다.
