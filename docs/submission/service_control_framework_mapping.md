# AI 기반 서비스 제어 및 관리 자동화 프레임워크 매핑

> 보관 문서: 현재 대학원 연구 본체는 4-Agent 기반 Kubernetes 장애 감시/복구 실험이다. 이 문서는 별도 과제 성격의 서비스 제어/AI App 배포 기능을 현재 코드와 어떻게 연결했는지 설명하는 참고 문서이며, README 본문 기준의 핵심 범위는 아니다.

이 문서는 대학원 연구와 별도 과제 성격의 **AI 기반 서비스 제어 및 관리 자동화 프레임워크** 항목을 현재 `aiops_research` 저장소 구현과 어떻게 연결할 수 있는지 설명한다.

핵심 표현은 다음과 같다.

> 본 프로젝트는 Kubernetes 서비스 복구와 AI 서비스 운영을 위한 **안전 제약 기반 폐루프 자율 4-Agent AIOps 프레임워크**이다.

즉, 4개 Agent가 evidence를 수집하고, 장애를 진단하며, 여러 복구 action 후보를 만들고, Infra/Cost 관점에서 후보를 평가한 뒤, 안전 검증을 통과한 action만 Kubernetes에 전달한다. 단, 현재 autonomous evidence flow는 `FakeEvidenceProvider` 기반 mock/test loop와 제한적인 Kubernetes deployment/pod snapshot provider까지 구현되어 있으며, Prometheus metric, log enrichment, full real-cluster evidence fusion은 후속 확장 단계로 분리한다.

## 1. 과제 항목과 현재 구현 매핑

| 과제 항목 | 현재 구현 | 주요 파일 | 실행 명령 |
| --- | --- | --- | --- |
| Ops 분석 시험 및 최적 LLM 선정 | LLM 후보의 품질, 비용, 지연, action 안전성 기준 ranking | `config/ops_llm_benchmark.json`, `src/aiops_k8s_agents/ops_llm_selection.py` | `aiops-k8s-agents select-ops-llm --policy quality_first` |
| AI LLM 운영 관리 구조 설계 | LLM 선정, CPU/GPU 배치, manifest, Agent 검토를 하나의 운영 파이프라인으로 연결 | `src/aiops_k8s_agents/service_operations.py` | `aiops-k8s-agents run-service-operations ...` |
| AI 에이전트 등록 관리 프로토타입 | Agent 역할, bounded action, reward signal 등록/조회/검증 | `config/agent_registry.json`, `src/aiops_k8s_agents/agent_registry.py` | `list-agents`, `show-agent`, `validate-agent-action`, `register-agent` |
| AI 응용 자동화 에이전트 설계 | HA, Application, Infra, Cost Agent와 Coordinator 구현 | `ha_agent.py`, `application_agent.py`, `infra_agent.py`, `cost_agent.py`, `coordinator.py` | `aiops-k8s-agents run ...` |
| CPU/GPU VM 기반 AI 응용 배포/제어 추론 최적화 전략 | workload 조건에 맞는 CPU/GPU VM 후보 추천, deployment plan 생성 | `config/inference_optimization.json`, `src/aiops_k8s_agents/inference_optimizer.py` | `recommend-inference-placement`, `plan-inference-deployment` |
| 안전한 Kubernetes 실행 | Python Validator와 Go Guard 이중 검증 | `src/aiops_k8s_agents/validator.py`, `go/aiops-guard` | `execute-recovery-action --guard-backend go ...` |
| 폐루프 자율 Agent 운영 | mock/test evidence 수집, 제한적 Kubernetes snapshot, 진단, 후보 생성, 후보 평가, 실행, 복구 모니터링, 재계획 | `src/aiops_k8s_agents/evidence.py`, `src/aiops_k8s_agents/autonomous.py`, `src/aiops_k8s_agents/recovery_monitor.py` | `aiops-k8s-agents autonomous-run ...` |
| 실험 결과 추적 | real/mock/dry-run 결과와 통계 산출물 구분 | `runs/`, `src/aiops_k8s_agents/recovery_statistics.py` | `summarize-recovery-statistics ...` |

## 2. 폐루프 autonomous 구조

현재 추가된 autonomous 흐름은 다음 순서로 동작한다.

```text
Evidence Collector
-> HA Agent evidence 기반 진단
-> Application Agent multi-candidate recovery planning
-> Infra Agent candidate feasibility evaluation
-> Cost Agent candidate cost evaluation
-> Coordinator final action selection
-> Python Validator + Go Guard validation
-> Kubernetes mock/dry-run/real execution
-> Recovery Monitor assessment
-> bounded replanning if recovery fails
-> final report and policy recommendation
```

Evidence 구현 범위는 다음과 같이 구분한다.

- `FakeEvidenceProvider`: mock/test autonomous loop 검증용 evidence provider
- `KubernetesEvidenceProvider`: deployment/pod 상태 snapshot 중심의 제한적 provider
- future extension: Prometheus metric, log enrichment, full real-cluster evidence fusion

중요한 안전 제약은 다음과 같다.

- LLM 또는 AutoGen이 임의의 `kubectl` command를 직접 실행하지 않는다.
- Agent는 구조화된 `RecoveryAction` 후보만 생성한다.
- 실제 실행 전에는 Python Validator가 namespace, deployment, action, replica 범위를 검증한다.
- `--guard-backend go`를 사용하면 Go Guard가 동일 action을 한 번 더 검증한다.
- 복구 실패 후 재계획은 `max_replan_attempts` 안에서만 수행한다.
- 정책 변경은 자동 적용하지 않고 `requires_human_review: true` recommendation으로만 남긴다.

## 3. 실행 모드 구분

| 모드 | 의미 | 실제 Kubernetes 변경 여부 | 사용 목적 |
| --- | --- | --- | --- |
| `mock` | 구조와 안전 검증만 수행 | 없음 | 로컬/서버 빠른 기능 확인 |
| `dry-run` | Kubernetes API server-side validation 수행 | 없음 | 명령/API 호환성 확인 |
| `real` | 검증을 통과한 action을 실제 실행 | 있음 | 연구실 서버 kind/full-stack 실험 |

mock 결과를 real 실험 결과처럼 쓰면 안 된다. 발표와 문서에서는 항상 결과 출처를 `mock`, `dry-run`, `real`로 구분해야 한다.

## 4. 대표 실행 명령

### 4.1 최적 LLM 선정

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy quality_first
```

대표 결과:

```text
selected_model = gpt-5.5
```

### 4.2 CPU/GPU VM 배치 추천

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

### 4.3 AI 서비스 배포 계획과 Agent 검토 통합

```bash
aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --mode mock \
  --guard-backend go
```

이 명령은 Ops LLM 선정, CPU/GPU VM 배치 추천, Deployment manifest 생성, Agent 검토, guard backend 연결 상태를 한 번에 보여준다.

### 4.4 폐루프 autonomous 4-Agent 실행

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

대표 확인 필드:

```text
final_status
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

## 5. 현재 구현과 future work 구분

| 구분 | 현재 상태 |
| --- | --- |
| deterministic 4-Agent recovery 판단 | 구현 완료 |
| AutoGen structured multi-agent decision 경로 | 구현 완료 |
| FakeEvidenceProvider 기반 autonomous mock/test loop | 구현 완료 |
| KubernetesEvidenceProvider 기반 제한적 deployment/pod snapshot | 구현 완료 |
| Recovery Monitor와 bounded replanning | 구현 완료 |
| Chaos Mesh/Prometheus/Kubernetes real recovery 실험 | 구현 완료 |
| Go Guard 기반 이중 검증 | 구현 완료 |
| CPU/GPU VM placement recommendation | 구현 완료 |
| AI 서비스 Deployment manifest 생성 및 dry-run | 구현 완료 |
| Prometheus/log enrichment 기반 full autonomous evidence fusion | future work |
| 실제 GPU/NPU 클러스터 스케줄링 | future work |
| 실제 TPU/NPU 환경 검증 | future work |
| AWS/Azure/GCP 멀티 클라우드 API 연동 | future work |
| 실제 모델 inference service 상시 운영 연동 | future work |
| Go Echo HTTP API 서버와 Swagger UI | 이번 범위 제외 |

## 6. 실험 결과 출처 표기 원칙

실험 결과를 문서나 발표에 넣을 때는 반드시 출처를 함께 적는다.

예시:

```text
This result was generated from runs/recovery-action-pilot/20260616_173903/outcomes.jsonl
using aiops-k8s-agents summarize-recovery-statistics.
```

구분 기준:

- `runs/.../outcomes.jsonl`: 실제 반복 실험 raw result
- `analysis/reward_policy_comparison.md`: reward policy별 action ranking 분석
- `statistics/*.csv`: 정량 통계 테이블
- `statistics/*.svg`, `statistics/*.png`: 발표용 그래프
- `mock` 출력: 기능 구조 확인용 prototype result
- `dry-run` 출력: Kubernetes API 호환성 검증
- `real` 출력: 실제 Kubernetes resource 변경이 포함된 실험

## 7. 최종 정확성 보완

본 프로젝트의 autonomous flow는 무제한 자율 실행 시스템이 아니다. 자율성은 evidence 기반 진단, 후보 action 생성, 후보 평가, 복구 모니터링, 실패 시 제한적 재계획에 해당한다. 실제 Kubernetes 실행은 Python Validator와 Go Guard를 통과한 bounded action으로 제한된다.

`observe_only`는 복구 명령이 아니라 read-only observation이다. 즉 Kubernetes 상태를 변경하지 않고 현재 deployment/pod 상태와 Kubernetes 자체 복구 여부를 확인하는 action이다. 리포트에서는 다음처럼 상태 변경 action과 구분한다.

```json
{
  "kind": "observe_only",
  "state_changed": false,
  "action_effect_type": "read_only_observation"
}
```

반대로 `rollout_restart`와 `scale_out`은 Kubernetes 상태를 변경하는 action이므로 `state_changed: true`, `action_effect_type: "kubernetes_state_change"`로 해석한다.

Infra Agent의 현재 구현 범위도 다음처럼 제한해서 해석한다.

> Infra Agent reviews Kubernetes replica/deployment safety and infrastructure capacity constraints in the current research prototype. Real GPU/NPU cluster scheduling remains future work.

즉 현재 Infra Agent는 Kubernetes replica 안전성, deployment 안전성, 인프라 수용 가능성 검토를 담당한다. 실제 CPU/GPU VM 배치, GPU/NPU 클러스터 스케줄링, accelerator-level orchestration은 후속 확장 범위이다.
