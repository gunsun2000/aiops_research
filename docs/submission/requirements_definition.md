# 요구사항 정의서

## 1. 목적

본 프로젝트는 Kubernetes 환경에서 발생하는 서비스 장애를 4개의 AI Agent가 역할별로 판단하고, 안전 검증을 통과한 복구 action만 실행하는 AIOps 연구 프로토타입을 구현한다.

핵심 목표는 다음과 같다.

- 장애 상태 관측
- 4-Agent 기반 복구 판단
- action/reward 기반 교차 검증
- Python Validator와 선택적 Go Guard를 통한 안전 검증
- Kubernetes mock, dry-run, real 실행
- 반복 실험 결과 저장과 정량 분석

## 2. 범위

### 포함 범위

| 항목 | 설명 |
| --- | --- |
| 4-Agent 장애 판단 | HA, 응용관리, 인프라 운용, 비용 최적화 Agent |
| 장애 주입 | Chaos Mesh 기반 pod-kill, cpu-stress, memory-stress, network-delay |
| 상태 관측 | Prometheus, Kubernetes deployment/pod 상태 |
| 실행 action | observe_only, rollout_restart, scale_out |
| 안전 검증 | Python Validator, 선택적 Go Guard |
| 결과 분석 | JSONL, CSV, Markdown, PNG, SVG |

### 제외 범위

| 항목 | 이유 |
| --- | --- |
| Ops LLM 모델 선정 기능 | 본 연구의 중심은 LLM 모델 비교가 아니라 4-Agent 복구 판단 구조 |
| CPU/GPU VM 기반 AI App 배치 | 장애 복구 연구 본체와 직접 관련이 약함 |
| AI App deployment manifest 생성 | 현재 목표는 복구 action 검증 |
| Swagger/OpenAPI 서버 | API 서버 개발 범위가 아님 |
| 멀티클라우드 VM 스케줄링 | 후속 확장 가능 범위 |

## 3. 기능 요구사항

| ID | 요구사항 | 상태 |
| --- | --- | --- |
| FR-01 | 장애 이벤트 또는 metric 입력을 구조화된 `AlertEvent`로 변환한다. | 완료 |
| FR-02 | HA Agent가 장애 원인과 복구 필요성을 판단한다. | 완료 |
| FR-03 | Application Agent가 bounded recovery action 후보를 생성한다. | 완료 |
| FR-04 | Infrastructure Agent가 replica/deployment 안전성을 검토한다. | 완료 |
| FR-05 | Cost Agent가 비용과 과잉 action 여부를 검토한다. | 완료 |
| FR-06 | Python Validator가 namespace, deployment, replica limit을 검증한다. | 완료 |
| FR-07 | 선택적으로 Go Guard가 최종 action을 한 번 더 검증한다. | 완료 |
| FR-08 | mock, dry-run, real 실행 모드를 제공한다. | 완료 |
| FR-09 | Chaos Mesh 장애 주입 실험을 반복 실행한다. | 완료 |
| FR-10 | 실험 결과를 저장하고 정량 분석 자료를 생성한다. | 완료 |

## 4. 비기능 요구사항

| 항목 | 요구사항 |
| --- | --- |
| 안전성 | allowlist 밖 namespace/deployment는 실행하지 않는다. |
| 재현성 | 실험 결과를 JSONL/CSV/Markdown으로 저장한다. |
| 설명 가능성 | Agent별 decision, action, reward를 metadata로 남긴다. |
| 확장성 | Agent Registry와 action/reward 정책을 설정 파일로 관리한다. |
| 검증성 | `python -m pytest`와 `go test ./...`로 핵심 로직을 검증한다. |

## 5. 산출물

| 산출물 | 위치 |
| --- | --- |
| 요구사항 정의서 | `docs/submission/requirements_definition.md` |
| Word 요구사항 정의서 | `docs/submission/requirements_definition.docx` |
| 설치 및 실행 가이드 | `docs/submission/install_and_run_guide.md` |
| 실행 코드 가이드 | `docs/submission/execution_code_guide.md` |
| 시험 가이드 | `docs/submission/test_guide.md` |
| Agent Registry 가이드 | `docs/design/agent_registry_guide.md` |
| Action/Reward 정책 | `docs/design/agent_action_reward_policy.md` |
| Recovery 실험 가이드 | `docs/experiments/recovery_action_experiment_guide.md` |
| 정량 분석 가이드 | `docs/experiments/recovery_quantitative_analysis_guide.md` |
