# 대학원 연구와 /ETRI 과제 통합 설계서

## 1. 문서 목적

이 문서는 현재 `aiops_research` 프로젝트가 두 가지 요구를 어떻게 구분하고, 어디에서 통합하는지 설명한다.

첫 번째 흐름은 교수님이 요청한 4-Agent 기반 AIOps 장애 감시/복구 연구이다. 핵심은 Kubernetes 서비스 장애를 관측하고, HA/응용관리/인프라/비용 Agent가 각자의 관점에서 판단한 뒤, 검증된 복구 action만 실행하는 것이다.

두 번째 흐름은 대학원/ETRI 과제 요구사항이다. 핵심은 Go 언어 개발, 최소 2종 이상 LLM 또는 코딩 Agent 활용, AI App 배포/운용, CPU/GPU VM 기반 배치, 향후 AWS/Azure/GCP 및 API/Swagger/MCP 연동이다.

이 프로젝트는 두 흐름을 억지로 하나로 합친 것이 아니라, **Agent 기반 AI 서비스 운영 자동화**라는 상위 구조 안에서 공통 모듈을 재사용하도록 설계했다.

## 2. 범위 구분

| 구분 | 교수님 요청 연구 | 대학원/ETRI 과제 요구 |
| --- | --- | --- |
| 중심 문제 | Kubernetes 장애 감시와 복구 자동화 | AI 응용 등록, 배포, 운용, 스케줄링 |
| 주요 대상 | Online Boutique, AIOpsLab, Chaos Mesh 장애 | AWS/Azure/GCP Ubuntu GPU VM, AI App |
| 주요 입력 | Prometheus metric, Kubernetes state, 장애 이벤트 | AI App 요구사항, GPU/CPU 조건, 비용, latency, throughput |
| 주요 판단 | 어떤 복구 action을 실행할 것인가 | 어느 CPU/GPU VM에 배포하고 어떻게 운용할 것인가 |
| 주요 Agent | HA, 응용관리, 인프라, 비용 Agent | 응용 배포/운용 Agent, 인프라 배치 Agent, 비용 Agent |
| 실행 action | observe, rollout restart, scale out | AI App 등록, 배포 계획, VM 배치, manifest 생성 |
| 안전 검증 | Python Validator, Go Guard | Go Guard, 정책 검증, 향후 API gateway 검증 |
| 산출물 성격 | 연구 실험 결과, recovery action ranking | 과제 제출용 설계서, 기능/API 가이드, 설치/시험 가이드 |

## 3. 현재 통합 구조

현재 구현된 통합 흐름은 다음과 같다.

```text
Ops LLM 선정
-> CPU/GPU VM 배치 계획
-> Kubernetes Deployment manifest 생성
-> manifest mock/dry-run 검증
-> Application / Infrastructure / Cost Agent 검토
-> 장애 입력이 있으면 AI-MCMP 4-Agent 복구 판단
-> Python Validator + Go Guard
-> Kubernetes dry-run 또는 real 실행 준비
```

이 흐름은 `src/aiops_k8s_agents/service_operations.py`와 `aiops-k8s-agents run-service-operations` CLI로 묶었다.

## 4. 통합하면 좋은 점

### 4.1 연구 일관성

기존 AIOps 장애 복구 연구와 AI App 배포/운용 과제가 모두 "AI Agent가 운영 의사결정을 수행한다"는 공통 주제를 가진다. 따라서 프로젝트를 분리해도 되지만, 완전히 따로 만들면 Agent 구조, 검증 구조, 로그 구조가 중복된다. 통합하면 하나의 연구 방향으로 설명할 수 있다.

### 4.2 안전 검증 재사용

장애 복구에서 만든 Python Validator와 Go Guard는 배포/운용 action에도 재사용할 수 있다. 즉, AI가 생성한 명령이나 배포 계획을 바로 실행하지 않고, 정책 검증을 통과한 action만 Kubernetes에 전달한다.

### 4.3 산출물 완성도 향상

교수님 요청 연구는 실험 중심이고, 대학원/ETRI 과제는 산출물 중심이다. 두 흐름을 연결하면 연구 결과뿐 아니라 요구사항 정의서, 기능/API 가이드, 설치 가이드, 시험 가이드까지 함께 제출할 수 있다.

### 4.4 확장성

현재는 kind 기반 Kubernetes와 서버 내부 GPU VM 후보를 사용하지만, 구조상 AWS/Azure/GCP 후보를 추가할 수 있다. `config/inference_optimization.json`에 cloud provider, GPU class, cost, latency, capacity 항목을 추가하면 멀티 클라우드 배치 정책으로 확장할 수 있다.

## 5. 현재 완료된 산출물

| 산출물 | 파일/경로 | 설명 |
| --- | --- | --- |
| 4-Agent 구조 | `src/aiops_k8s_agents/agents.py`, `config/agent_registry.json` | Agent 역할, action, reward 관리 |
| Agent 등록 관리 | `src/aiops_k8s_agents/agent_registry.py`, `docs/design/agent_registry_guide.md` | Agent별 허용 action과 정책 검증 |
| 장애 복구 파이프라인 | `src/aiops_k8s_agents/coordinator.py`, `src/aiops_k8s_agents/recovery_runner.py` | 장애별 action 후보 실행 및 결과 수집 |
| Ops LLM 선정 | `src/aiops_k8s_agents/ops_llm_selection.py`, `config/ops_llm_benchmark.json` | AIOps 기준으로 LLM 후보 ranking |
| CPU/GPU VM 배치 | `src/aiops_k8s_agents/inference_optimizer.py`, `config/inference_optimization.json` | workload 요구조건 기반 자원 추천 |
| 배포 manifest 생성 | `src/aiops_k8s_agents/deployment_renderer.py` | AI App Deployment manifest 생성 |
| 통합 실행 파이프라인 | `src/aiops_k8s_agents/service_operations.py` | LLM 선정, 배치, manifest, Agent 검토, 복구 판단 연결 |
| Python 안전 검증 | `src/aiops_k8s_agents/validator.py`, `src/aiops_k8s_agents/executor.py` | namespace/deployment/action/replica 검증 |
| Go 안전 검증 | `go/aiops-guard` | Go 언어 기반 2차 action guard |
| 실험 결과 분석 | `src/aiops_k8s_agents/recovery_statistics.py` | 복구 시간, 성공률, reward 통계/그래프 생성 |
| 제출 문서 | `docs/submission/` | 요구사항, 기능/API, 설치, 시험 가이드 |

## 6. 아직 남은 확장 범위

| 항목 | 현재 상태 | 다음 단계 |
| --- | --- | --- |
| Go Echo HTTP API 서버 | 아직 미구현 | CLI를 HTTP API로 감싸고 Swagger UI 제공 |
| 실제 멀티 클라우드 API 연동 | 아직 미구현 | AWS/Azure/GCP VM 후보와 실제 API 연결 |
| MCP/웹 콘솔 연동 | 아직 미구현 | 베스핀글로벌 API, 웹 콘솔, MCP와 연동 |
| 실제 AI 서비스 Pod 상시 배포 | 부분 구현 | manifest dry-run 이후 실제 apply와 서비스 모니터링 확장 |
| AutoGen multi-round real 실행 | 부분 구현 | 실제 장애 상황에서 장시간 토론/반박/재합의 구조 확장 |

## 7. 발표/보고서에서의 설명 문장

다음 문장으로 설명하면 두 흐름의 차이와 통합 이유를 동시에 말할 수 있다.

> 본 연구는 Kubernetes 장애 복구를 위한 4-Agent AIOps 구조를 중심으로 시작했으며, 대학원/ETRI 과제 요구사항에 맞추어 Go 기반 안전 검증, LLM 교차 검증, CPU/GPU VM 기반 AI 응용 배포/운용 계획 기능을 확장하였다. 두 흐름은 동일한 Agent 기반 운영 자동화 구조 안에서 통합되며, 장애 복구와 AI App 배포/운용을 하나의 안전한 서비스 운영 파이프라인으로 연결한다.
