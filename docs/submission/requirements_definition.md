# AIOps 4-Agent 장애 감시/복구 자동화 요구사항 정의서

## 1. 연구 개발 범위

본 프로젝트의 현재 중심은 **Kubernetes 기반 서비스 장애를 4개의 AI Agent가 판단하고, 안전하게 검증된 복구 action만 실행하는 AIOps 연구 프로토타입**이다.
초기 개발 과정에서 Go Guard, Ops LLM 선정, CPU/GPU VM 배치 추천 같은 확장 기능도 구현했지만, 본 요구사항 정의서에서는 대학원 연구 본체에 해당하는 장애 감시/복구 자동화 범위를 우선한다.

핵심 구현 범위는 다음과 같다.

- 4-Agent 기반 장애 진단, 복구 action 제안, 인프라/비용 관점 교차 검증
- Action/Reward 정책 기반 후보 action 평가
- Prometheus, AIOpsLab, Chaos Mesh, Kubernetes 상태 기반 실험
- Python Validator 기반 안전 실행 제어
- mock, dry-run, real 모드별 Kubernetes action 검증
- 실험 결과 JSON/JSONL/CSV/Markdown/그래프 저장

보조 또는 보관 범위는 다음과 같다.

- Go Guard: 선택적 이중 검증 모듈
- Ops LLM 선정: LLM 운영 연구로 확장할 때 사용할 보조 기능
- CPU/GPU VM 기반 AI 응용 배포/제어: 별도 과제 또는 후속 확장 기능
- Swagger/API/멀티클라우드: 현재 대학원 연구 본문에서는 제외

## 2. 핵심 목표

역할이 분리된 4개 AI Agent가 장애 상태를 해석하고, 서로 다른 운영 목표를 교차 검증한 뒤, 안전하게 검증된 Kubernetes action만 실행하도록 한다.

시스템의 최종 목표는 다음과 같다.

- 장애 관측: Prometheus, AIOpsLab, Chaos Mesh 실험 결과를 입력으로 사용한다.
- 판단 분리: HA, 응용관리, 인프라, 비용 관점의 Agent 판단을 분리한다.
- Action 구조화: LLM 자유 텍스트 명령을 직접 실행하지 않고 구조화 action으로 변환한다.
- 안전 검증: Python Validator를 통해 namespace, deployment, replica 범위, action type을 검증한다. Go Guard는 선택적 보조 검증기로 둔다.
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
| FR-07 | Python Validator 기반 최종 action guard | 완료 |
| FR-08 | Agent 등록 관리 프로토타입 | 완료 |
| FR-09 | CPU/GPU VM 기반 추론 배치 최적화 추천 | 보조/보관 |
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
- `src/aiops_k8s_agents/agent_registry.py`: Agent registry 모듈
- `src/aiops_k8s_agents/validator.py`: Python 기반 Kubernetes action validator
- `src/aiops_k8s_agents/recovery_runner.py`: 장애별 recovery action 실험 runner
- `src/aiops_k8s_agents/recovery_statistics.py`: 정량 통계/그래프 생성 모듈
- `docs/experiments/recovery_action_experiment_guide.md`: 장애별 recovery action 실험 가이드
- `docs/submission/test_guide.md`: 시험 검증 가이드

## 6. 현재 연구 단계의 의미

현재 단계는 단순 계획이 아니라 **구현된 1차 연구 프로토타입**이다.
AIOpsLab, Chaos Mesh, Prometheus, Kubernetes real 실행, Agent registry, Python Validator, recovery action 실험과 정량 분석까지 연결 가능한 구조를 갖추었다.

향후 연구에서는 이 구조를 기반으로 single-agent baseline, Agent 제거 실험, 더 큰 action space, Prometheus/log 기반 full evidence fusion까지 확장한다.
