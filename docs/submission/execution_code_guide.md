# 실행 코드 설명서

## 1. 문서 목적

이 문서는 프로젝트를 실행할 때 어떤 명령을 어떤 목적에 사용하는지 정리한 설명서이다. 단순 명령어 목록이 아니라, 대학원 연구 본체인 **4-Agent AIOps 장애 감시/복구 실험**과 보조/보관 기능을 구분해서 설명한다.

## 2. 실행 환경

| 환경 | 목적 |
| --- | --- |
| `base` | Anaconda 기본 환경 |
| `aiops_research` | 우리 프로젝트 실행, pytest, 4-Agent CLI |
| `aiopslab` | 외부 AIOpsLab 공식 코드 실행 |

일반적으로 우리 프로젝트는 다음 환경에서 실행한다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
```

서버 Kubernetes 실험을 할 때는 kind kubeconfig를 명시한다.

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
kubectl get nodes
```

## 3. 설치와 기본 검증

### 3.1 최신 코드 반영

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"
```

### 3.2 Python 테스트

```bash
python -m pytest
```

의미:

- Agent 판단 로직 검증
- validator 검증
- CLI 출력 검증
- recovery action 실험 코드 검증
- autonomous/recovery action 실험 코드 검증

### 3.3 선택적 Go Guard 테스트

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
go run ./cmd/aiops-guard --input ../../examples/go_guard_scale_action.json
```

의미:

- Python Validator 이후 Go Guard가 동일 action을 한 번 더 검증하는지 확인
- 위험한 namespace, deployment, replica, action이 차단되는지 확인
- 현재 대학원 연구 본체가 아니라 선택적 이중 검증 모듈로 보관

## 4. 대학원 연구 실행 코드

대학원 연구의 중심은 4-Agent가 장애 상황을 판단하고, 안전한 Kubernetes 복구 action을 결정하는 것이다.

### 4.1 Agent 목록 확인

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json
```

확인 내용:

- HA 지원 Agent
- 응용관리 Agent
- AI반도체 인프라 운용 Agent
- 비용 최적화 Agent

### 4.2 Agent action 검증

```bash
aiops-k8s-agents validate-agent-action \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent \
  --action app_scale_deployment
```

의미:

- 특정 Agent가 수행할 수 있는 action인지 확인
- Agent 등록 관리 프로토타입의 핵심 기능

### 4.3 복구 action 실행

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

의미:

- Kubernetes 복구 action을 실행한다.
- `--guard-backend go`를 사용하면 Python 검증 후 Go Guard가 한 번 더 검증한다.
- `--mode real`은 실제 Kubernetes API에 action을 전달한다.

### 4.4 폐루프 자율 4-Agent 실행

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

출력에서 확인할 핵심:

```text
collected_evidence_summary
diagnosis
generated_candidates
infra_evaluations
cost_evaluations
selected_action
validation_result
execution_result
recovery_monitoring
replanning_attempts
policy_update_recommendations
```

의미:

- 단일 metric 입력만 보는 구조를 넘어, evidence 기반으로 장애 원인을 진단한다.
- 현재 `autonomous-run` evidence flow는 `FakeEvidenceProvider` 기반 mock/test 시나리오를 안정적으로 검증하도록 구현되어 있다.
- `--evidence-source kubernetes`는 deployment/pod snapshot 중심의 제한적 provider이며, Prometheus metric과 log enrichment를 결합한 full real-cluster evidence fusion은 후속 확장이다.
- Application Agent가 `observe_only`, `rollout_restart`, `scale_out` 후보를 모두 생성한다.
- Infra Agent와 Cost Agent가 각 후보를 별도로 평가한다.
- Coordinator가 가장 적절한 action을 선택한다.
- 실행 후 Recovery Monitor가 복구 여부를 판단한다.
- 실패하면 `--max-replan-attempts` 범위 안에서 다음 후보로 재계획한다.
- mock mode에서는 실제 Kubernetes resource를 바꾸지 않는다.
- mock evidence 결과는 실제 Chaos Mesh/Prometheus/Kubernetes real 실험 결과와 구분해서 기록한다.

## 5. 보조/보관 기능 실행 코드

아래 기능은 개발 과정에서 구현했지만, 현재 대학원 연구 본체에서는 뒤로 뺀다. 별도 과제나 후속 확장에서 AI App 배포/운용, CPU/GPU VM 기반 배치, Ops LLM 선정, Go/LLM 교차 검증이 필요할 때 재사용한다.

### 5.1 Ops LLM 선정

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy quality_first
```

출력에서 확인할 핵심:

```text
selected_model = gpt-5.5
ranking = 후보 LLM별 점수
```

의미:

- 여러 LLM 후보를 AIOps 기준으로 비교한다.
- 품질, 비용, latency, action validity, consistency를 기준으로 모델을 선택한다.
- `gpt-4o-mini`는 저비용 smoke-test/fallback 모델로 남길 수 있다.

### 5.2 CPU/GPU VM 배치 추천

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

출력에서 확인할 핵심:

```text
selected_resource = gpu-vm-l4
action = deploy_on_gpu_vm
slo_satisfied = true
```

의미:

- AI App의 latency, throughput, accelerator, cost, capacity 요구를 보고 적절한 CPU/GPU VM 후보를 선택한다.
- 현재는 실제 AWS/Azure/GCP API 연동 전 단계의 정책 기반 추천 모듈이다.

### 5.3 AI 응용 배포/제어 계획 생성

```bash
aiops-k8s-agents plan-inference-deployment \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

출력에서 확인할 핵심:

```text
deployment_plan.kubernetes.namespace
deployment_plan.kubernetes.deployment
deployment_plan.kubernetes.resources
control_actions
monitoring_metrics
```

의미:

- 선택된 CPU/GPU VM 자원에 맞는 Kubernetes 배포 계획을 생성한다.
- 실제 배포 전 어떤 namespace, deployment, resource request/limit, control action을 사용할지 확인한다.

## 6. 보조/보관: AI 서비스 운영 통합 파이프라인 실행 코드

이 통합 파이프라인은 Ops LLM 선정, CPU/GPU VM 배치, AI 서비스 deployment manifest, 4-Agent 검토를 한 번에 묶어 보여주는 확장 기능이다. 현재 대학원 연구 본체는 Chaos Mesh/AIOpsLab 장애 감시와 Kubernetes recovery action 실험이므로, 이 명령은 부록 또는 후속 과제용으로 분리한다.

```bash
aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --mode mock \
  --guard-backend go
```

출력에서 확인할 핵심:

```text
selected_llm
selected_resource
deployment_plan
deployment_manifest
deployment_dry_run
agent_reviews
recovery_pipeline_ready
guard_backend
```

의미:

- Ops LLM 선정
- CPU/GPU VM 배치 추천
- AI 서비스 배포 manifest 생성
- manifest mock/dry-run 검증
- 응용/인프라/비용 Agent 검토
- Go Guard 연결 준비

장애 복구 판단까지 함께 연결하려면 metric 입력을 추가한다.

```bash
aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --mode mock \
  --guard-backend go
```

## 7. Real 장애 실험 실행 코드

Prometheus port-forward를 별도 터미널에서 켠다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

실험 터미널에서 Prometheus 연결을 확인한다.

```bash
export PROM=http://127.0.0.1:9091
curl -sS "$PROM/-/ready"
```

network-delay 실험에 필요한 latency query를 지정한다.

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
```

36회 recovery action 실험을 실행한다.

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

결과를 확인한다.

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
wc -l "$LATEST/outcomes.jsonl"
cat "$LATEST/analysis/reward_policy_comparison.md"
```

정상 기준:

```text
36 outcomes.jsonl
```

## 8. 정량 분석 실행 코드

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

aiops-k8s-agents summarize-recovery-statistics \
  --input "${LATEST}outcomes.jsonl" \
  --output-dir "${LATEST}statistics"
```

생성되는 산출물:

```text
statistics/quantitative_summary.md
statistics/scenario_action_statistics.csv
statistics/policy_reward_statistics.csv
statistics/mean_recovery_seconds_by_action.svg
statistics/success_rate_by_action.svg
statistics/reward_by_policy.svg
```

의미:

- 평균 복구 시간 비교
- action별 성공률 비교
- reward 정책별 선택 action 비교
- 발표용 그래프 생성

## 9. 연구 구조의 장점

| 장점 | 설명 |
| --- | --- |
| 연구 중심성 | 장애 감시, Agent 판단, 복구 action, 안전 검증, 결과 분석 흐름이 한 프로젝트 안에서 재현됨 |
| 안전성 강화 | Python Validator를 기본 안전 검증기로 사용하고, 필요하면 Go Guard를 선택적으로 추가 |
| 산출물 명확화 | 요구사항, 설치, 시험, 실행 코드, 실험 해석 문서를 분리 |
| 실험 재현성 | CLI, JSON output, runs 로그, statistics 산출물로 재현 가능 |
| 확장성 | 향후 full evidence fusion, AutoGen multi-round real 실행, baseline/ablation 연구로 확장 가능 |
