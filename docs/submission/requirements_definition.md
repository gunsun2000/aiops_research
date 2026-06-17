# AIOps 4-Agent 서비스 제어 자동화 요구사항 정의서

## 1. 연구 개발 범위

본 프로젝트는 1차년도 연구 개발 내용 중 **AI 기반 서비스 제어 및 관리 자동화 프레임워크**에 해당한다.
세부적으로는 다음 항목을 구현 대상으로 둔다.

- AI LLM 운영 관리 구조 설계 및 프로토타입
- AI 에이전트 등록 관리 프로토타입
- AI 응용 자동화 에이전트 설계 및 프로토타입
- CPU/GPU VM 기반 AI 응용 배포/제어에 특화된 추론 최적화 전략
- Go 언어 기반 최종 Kubernetes action 검증 모듈
- 최소 2종 이상의 LLM/코딩 에이전트 관점 교차 검증 문서화

## 2. 핵심 목표

역할이 분리된 4개 AI Agent가 장애 상태를 해석하고, 서로 다른 운영 목표를 교차 검증한 뒤, 안전하게 검증된 Kubernetes action만 실행하도록 한다.

시스템의 최종 목표는 다음과 같다.

- 장애 관측: Prometheus, AIOpsLab, Chaos Mesh 실험 결과를 입력으로 사용한다.
- 판단 분리: HA, 응용관리, 인프라, 비용 관점의 Agent 판단을 분리한다.
- Action 구조화: LLM 자유 텍스트 명령을 직접 실행하지 않고 구조화 action으로 변환한다.
- 안전 검증: Python validator와 Go guard를 통해 namespace, deployment, replica 범위, action type을 검증한다.
- 실행 검증: mock, dry-run, real 모드에서 동일한 action 템플릿을 사용한다.
- 실험 기록: 장애별 action, reward, Kubernetes 상태, metric 결과를 JSON/Markdown으로 저장한다.

## 3. 기능 요구사항

| ID | 요구사항 | 구현 상태 |
| --- | --- | --- |
| FR-01 | 4-Agent 역할 분리 및 action/reward 정책 설계 | 완료 |
| FR-02 | AutoGen GroupChat 기반 Agent 대화 경로 | 완료 |
| FR-03 | Prometheus metric 입력 기반 실행 경로 | 완료 |
| FR-04 | Chaos Mesh 장애 4종 실험 | 완료 |
| FR-05 | AIOpsLab Hotel Reservation 탐지 benchmark 연동 | 완료 |
| FR-06 | Kubernetes real 제어 및 상태 확인 | 완료 |
| FR-07 | Go 언어 기반 최종 action guard | 완료 |
| FR-08 | Agent 등록 관리 프로토타입 | 완료 |
| FR-09 | CPU/GPU VM 기반 추론 배치 최적화 추천 | 완료 |
| FR-10 | Reward 정책 변화에 따른 action ranking 비교 | 완료 |
| FR-11 | 장애별 최적 action 선택 실험 | 완료 |
| FR-12 | 프로덕션 API 서버 형태의 Agent Registry 서비스 | 향후 확장 |

## 4. 비기능 요구사항

| 항목 | 요구사항 |
| --- | --- |
| 이식성 | 로컬, kind, 연구실 서버에서 동일한 명령 템플릿을 사용한다. |
| 안전성 | validator를 통과하지 않은 action은 real 모드에서도 실행하지 않는다. |
| 재현성 | 모든 실험은 CLI 명령과 JSON 설정 파일로 재현 가능해야 한다. |
| 관측성 | 실행 결과, reward, before/after Kubernetes 상태를 파일로 저장한다. |
| 확장성 | 새로운 Agent, action, reward signal을 registry JSON에 추가할 수 있어야 한다. |

## 5. 주요 산출물

- `config/agent_registry.json`: 4-Agent 등록 관리 설정
- `config/inference_optimization.json`: CPU/GPU VM 추론 배치 정책
- `src/aiops_k8s_agents/agent_registry.py`: Agent registry 모듈
- `src/aiops_k8s_agents/inference_optimizer.py`: 추론 최적화 모듈
- `go/aiops-guard`: Go 기반 Kubernetes action guard
- `docs/submission/functional_api_guide.md`: 기능/API 가이드
- `docs/submission/test_guide.md`: 시험 검증 가이드

## 6. 현재 연구 단계의 의미

현재 단계는 단순 계획이 아니라 **구현된 1차 통합 프로토타입**이다.
AIOpsLab, Chaos Mesh, Prometheus, Kubernetes real 실행, Go guard, Agent registry, 추론 최적화까지 연결 가능한 구조를 갖추었다.

향후 연구에서는 이 구조를 기반으로 single-agent baseline, Agent 제거 실험, 더 큰 action space, GPU/NPU 실제 스케줄링까지 확장한다.
