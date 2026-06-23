# AIOps 4-Agent 연구 핵심 제출 요약

이 문서는 대학원 연구 발표 또는 평가자에게 보여줄 때 남겨야 할 핵심 항목만 정리한 제출용 요약이다. 전체 프로젝트 파일을 줄이는 것이 아니라, 발표와 보고서에서는 아래 내용 중심으로 설명한다.

## 1. 연구 한 줄 요약

본 프로젝트는 Kubernetes 기반 서비스 장애 상황에서 4개의 AI Agent가 운영 evidence를 수집하고, 장애를 진단하며, 여러 recovery action 후보를 생성·평가한 뒤 Python Validator와 Go Guard를 통과한 action만 실행하는 **안전 제약 기반 폐루프 자율 4-Agent AIOps 프레임워크**이다. 현재 autonomous evidence flow는 mock/test용 `FakeEvidenceProvider`와 제한적인 Kubernetes deployment/pod snapshot provider까지 구현되어 있으며, Prometheus metric과 log를 결합한 full real-cluster evidence fusion은 후속 확장으로 분리한다.

## 2. 과제 개발 가이드 대응 현황

| 개발 가이드 항목 | 현재 상태 | 프로젝트 산출물 |
| --- | --- | --- |
| Go 언어 개발 필수 | 완료 | `go/aiops-guard` |
| 최소 2종 이상 LLM/코딩 에이전트 활용 | 완료 | AutoGen 4-Agent 경로, Codex 기반 코드 작성/검증, LLM 교차 검증 문서 |
| 교차 검증 | 완료 | Python validator + Go guard 이중 검증, Agent action/reward 합의 구조 |
| 프레임워크/프롬프트 중심 문서 작성 | 완료 | `docs/design/agent_registry_guide.md`, `docs/design/go_and_llm_cross_validation.md`, `docs/design/ops_llm_selection_guide.md` |
| 산출물 문서 최소화 | 정리 완료 | 이 문서 기준으로 핵심 산출물만 설명 |
| 로그 및 에러 메시지 최대화 | 완료 | `runs/`, `outcomes.jsonl`, `statistics/`, pytest 로그, kubectl 결과 |
| 개발은 코딩 에이전트, 사람은 시험 검증 위주 | 완료 | Codex가 구현/테스트 작성, 연구자는 서버 실험 실행 및 결과 검증 |

## 3. 연구에서 실제로 구현한 핵심 기능

| 구분 | 구현 내용 | 대표 파일 |
| --- | --- | --- |
| 4-Agent 구조 | HA, 응용관리, 인프라, 비용 최적화 Agent 역할 분리 | `src/aiops_k8s_agents/agents.py`, `config/agent_registry.json` |
| Agent 등록 관리 | Agent별 역할, action, reward, 승인/거부 조건 관리 | `config/agent_registry.json`, `docs/design/agent_registry_guide.md` |
| Action/Reward 정책 | 장애별 후보 action 평가 및 reward 정책별 action ranking | `config/recovery_action_experiments.json`, `docs/design/agent_action_reward_policy.md` |
| Evidence 기반 자율 판단 | fake evidence 기반 mock/test loop, 제한적 Kubernetes snapshot, 진단, 후보 생성, 후보별 평가, 복구 모니터링, 재계획 | `src/aiops_k8s_agents/evidence.py`, `src/aiops_k8s_agents/autonomous.py`, `src/aiops_k8s_agents/recovery_monitor.py` |
| Kubernetes 안전 실행 | allowlist, replica 범위, namespace/deployment 검증 | `src/aiops_k8s_agents/validator.py`, `src/aiops_k8s_agents/executor.py` |
| Go 기반 Guard | 최종 action을 Go 언어로 한 번 더 검증 | `go/aiops-guard` |
| Prometheus 연동 | metric 기반 상태 관측 및 실험 입력 | `src/aiops_k8s_agents/prometheus.py` |
| Chaos Mesh 실험 | pod-kill, cpu-stress, memory-stress, network-delay 장애 주입 | `k8s/chaos/` |
| AIOpsLab 연동 | Hotel Reservation 탐지 benchmark 실험 | `scripts/server_aiopslab_auto_detection.py` |
| 정량 분석 | 평균 복구 시간, 성공률, reward 정책별 선택 결과 분석 | `src/aiops_k8s_agents/recovery_statistics.py` |
| 그래프 산출 | 발표용 PNG와 확대용 SVG 그래프 생성 | `runs/recovery-action-pilot/<run>/statistics/` |

## 4. 발표와 보고서에 남길 핵심 실험

### 4.1 AIOpsLab 탐지 Benchmark

- 목적: AIOpsLab 환경에서 장애 탐지/분석 흐름이 동작하는지 확인
- 대상: Hotel Reservation detection 문제
- 의미: 4-Agent 제어 구조가 실제 AIOpsLab benchmark와 결합 가능함을 보임

### 4.2 Chaos Mesh 기반 Real 장애 실험

| 장애 시나리오 | 대상 서비스 | 의미 |
| --- | --- | --- |
| `pod-kill` | `paymentservice` | Kubernetes 자체 복구와 과잉 action 여부 확인 |
| `cpu-stress` | `paymentservice` | CPU 부하 상황에서 action 선택 비교 |
| `memory-stress` | `checkoutservice` | memory 장애 상황에서 restart/scale action 비교 |
| `network-delay` | `paymentservice` | 네트워크 지연 상황에서 복구 action 비교 |

### 4.3 Recovery Action Matrix

- 실험 구성: 4개 장애 x 3개 action x 3회 반복 = 총 36회
- action 후보:
  - `observe_only`
  - `rollout_restart`
  - `scale_out`
- 핵심 결과:
  - 36개 측정 모두 유효
  - 복구 성공률은 모든 조합에서 100%
  - action 차이는 성공률보다 평균 복구 시간과 reward ranking에서 더 잘 드러남

## 5. 발표에 넣을 핵심 그래프

| 그래프 | 파일 | 발표에서 말할 내용 |
| --- | --- | --- |
| 평균 복구 시간 | `mean_recovery_seconds_by_action.png` | 장애/action 조합별 성능 차이 |
| 복구 성공률 | `success_rate_by_action.png` | 모든 조합이 복구 성공 조건을 만족 |
| reward 정책별 선택 | `reward_by_policy.png` | cost/HA/infra 우선 정책에 따라 action 선택이 달라짐 |

`success_rate_by_action.png`는 모든 값이 1.000이므로 차이가 없어 보이는 것이 정상이다. 이 그래프는 성능 비교용이 아니라 안정성 확인용으로 사용한다.

## 6. 제출용 산출물 목록

| 산출물 요구 | 현재 파일 |
| --- | --- |
| 요구사항 정의서 | `docs/submission/requirements_definition.md`, `docs/submission/requirements_definition.docx` |
| 기능/API 가이드 | `docs/submission/functional_api_guide.md`, `docs/submission/service_control_framework_mapping.md`, `docs/submission/openapi_agent_registry.yaml` |
| 설치 활용 가이드 | `docs/submission/install_and_run_guide.md` |
| 시험 가이드 | `docs/submission/test_guide.md` |
| Go 개발 설명 | `docs/design/go_and_llm_cross_validation.md`, `go/aiops-guard/README.md` |
| Agent 등록 관리 설명 | `docs/design/agent_registry_guide.md` |
| LLM 선정 설명 | `docs/design/ops_llm_selection_guide.md` |
| 추론 배포 최적화 전략 | `docs/design/inference_optimization_guide.md`, `docs/design/ai_application_deployment_strategy.md` |
| Recovery 실험 설명 | `docs/experiments/recovery_action_experiment_guide.md` |
| 정량 분석 설명 | `docs/experiments/recovery_quantitative_analysis_guide.md` |

## 7. 발표에서 뒤로 빼도 되는 내용

아래 항목은 개발 과정에서는 중요했지만, 최종 발표에서는 핵심 흐름을 흐릴 수 있으므로 부록 또는 질의응답용으로만 사용한다.

- 초기 CPU 95% mock 시나리오
- Docker/kubectl/kind 설치 시행착오
- 실패했던 port-forward 로그
- 전체 터미널 로그 원문
- 모든 JSON/CSV의 세부 행
- 내부 테스트 코드 전체 설명

## 8. 대학원 연구 설명 핵심 문장

본 연구에서는 AI 기반 서비스 제어 및 관리 자동화 프레임워크의 1차 구현으로, 4-Agent 역할 분담 구조와 action/reward 기반 교차 검증 방식을 설계하였다. 또한 Go 언어 기반 안전 검증기를 추가하여 LLM이 제안한 Kubernetes action을 독립적으로 재검증하도록 구성하였다. 이후 AIOpsLab, Chaos Mesh, Prometheus, Kubernetes 환경에서 실제 장애 주입 및 복구 action 실험을 수행하고, 평균 복구 시간과 reward 정책별 action 선택 결과를 정량 분석하였다.

## 9. 현재 단계와 다음 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1차 연구 | 4-Agent 구조 설계, Go guard, real 장애 실험, 정량 분석 | 완료에 가까움 |
| 2차 연구 | Agent 제거 실험, single-agent baseline, reward 민감도 확장 | 다음 단계 |
| 3차 연구 | GPU/NPU 실제 스케줄링, 대규모 AIOpsLab full-scale 확장 | 향후 확장 |

현재 프로젝트는 단순 mock 프로토타입이 아니라, 실제 서버의 Kubernetes/Chaos Mesh 환경에서 real-mode 장애 실험과 정량 분석까지 수행한 1차 연구 결과물로 정리할 수 있다.
