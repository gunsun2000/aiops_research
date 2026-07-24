# 상호감시형 안전 제어 4-Agent AIOps 연구 프레임워크 설계

## 1. 문서 목적

이 문서는 기존 `aiops_research` 프로젝트를 일회성 장애 복구 데모가 아니라,
Agent 구성, 합의 정책, Reward, 장애 시나리오와 실행 경로를 바꿔가며 후속
연구를 반복할 수 있는 프레임워크로 확장하기 위한 설계를 정의한다.

연구의 중심은 네 개 Agent를 단순히 순서대로 실행하는 것이 아니다. 네 Agent가
서로의 판단과 실행 결과를 자동으로 검토하고, 반박, 수정 요청, 거부 및
재평가를 수행하는 상호감시형 멀티에이전트 운영 구조를 구현하는 것이다.

최종 시스템 명칭은 다음과 같다.

> Configurable Mutual-Supervision, Safety-Bounded, Closed-Loop Autonomous
> 4-Agent AIOps Research Framework

한국어 명칭은 다음과 같다.

> 설정 가능한 상호감시형 안전 제어 폐쇄 루프 4-Agent AIOps 연구 프레임워크

## 2. 설계 목표

1. 네 Agent가 역할별로 독립적인 최초 판단을 생성한다.
2. Agent가 다른 Agent의 판단과 Action을 구조화된 메시지로 검토한다.
3. 반박과 수정 요청이 발생하면 제한된 횟수 안에서 자동 재협상한다.
4. Coordinator는 독단적인 최종 판단자가 아니라 상태 전달과 합의 절차를
   관리하는 중재자로 동작한다.
5. 합의된 Action도 안전 검증을 통과한 경우에만 Kubernetes에 실행한다.
6. 실행 후 네 Agent가 역할별로 복구 결과를 다시 평가한다.
7. 실패 시 다음 후보 Action을 재협상하거나 안전하게 중단한다.
8. 모든 판단, 검토, 실행과 결과를 재현 가능한 연구 데이터로 저장한다.
9. 기존 순차형 Coordinator, autonomous flow, CLI와 테스트의 호환성을 유지한다.
10. 코어 코드 수정 없이 설정 변경으로 비교 실험을 구성할 수 있게 한다.

## 3. 비목표

이번 설계의 첫 구현 단계에서는 다음을 목표로 하지 않는다.

- 임의의 LLM 자유 텍스트 또는 셸 명령 직접 실행
- 무제한 Agent 대화
- 안전 검증을 우회하는 완전 무제한 자율 제어
- 기존 순차형 및 autonomous 실행 경로 제거
- 웹 플랫폼에서의 즉시 real 실행
- AIOpsLab 외부 저장소를 프로젝트 내부로 복사
- 새로운 멀티클라우드 또는 AI App 배포 기능 추가

## 4. 전체 아키텍처

```text
Evidence Collector
        |
        v
Shared Operational State
        |
        v
4-Agent Initial Decisions
        |
        v
Peer Review Matrix
        |
        v
반박 / 수정 / 재협상 (기본 최대 2회)
        |
        v
Role-Based Consensus
        |
        v
Python Validator + Optional Independent Guard
        |
        v
Kubernetes Executor
        |
        v
Recovery Monitor
        |
        v
4-Agent Post-Execution Review
        |
        +----> 성공
        |
        +----> 다음 후보 Action 재계획
        |
        +----> 안전 중단 및 사람 검토
        |
        v
Research Event Store + Statistics
```

기존 `AIMCMPCoordinator`와 `AutonomousAIOpsCoordinator`는 유지한다. 새
상호감시 엔진은 별도 실행 경로로 추가하여 다음 세 가지 연구 조건을 동일한
Evidence와 장애 조건으로 비교할 수 있게 한다.

1. 기존 순차형 Deterministic 4-Agent
2. 상호감시형 Deterministic 4-Agent
3. 상호감시형 AutoGen 4-Agent

## 5. 핵심 구성요소

### 5.1 Shared Operational State

모든 Agent가 같은 운영 상태를 참조하도록 하는 읽기 중심의 상태 객체다.

포함 정보:

- Namespace와 Deployment
- Metric, threshold, metric policy
- Kubernetes Deployment/Pod snapshot
- 장애 및 이벤트 정보
- Agent별 최초 판단
- Peer Review 메시지
- 현재 협상 라운드
- 후보 Action과 평가
- 안전 검증 결과
- 실행 결과
- 복구 관측 결과

각 상태 변경은 기존 내용을 덮어쓰는 대신 이벤트로 남겨 연구 추적성을
보장한다.

### 5.2 Agent Registry

기본 프로파일은 다음 네 Agent로 고정한다.

- `AIServiceHASupportAgent`
- `AIApplicationManagementAgent`
- `AISemiconductorInfraOpsAgent`
- `CostOptimizationAgent`

Registry는 역할, 전문 영역, 허용 Action, 검토 대상, 거부권 범위와 정책
버전을 제공한다. 기본 4-Agent 연구를 유지하면서 향후 Agent 정책 교체 또는
새로운 연구 Agent 추가가 가능해야 한다.

### 5.3 Peer Review Protocol

모든 판단은 임의 문자열이 아니라 구조화된 메시지로 교환한다. 자유 텍스트는
설명 필드로만 사용하며 제어 데이터로 직접 해석하지 않는다.

검토 결과는 다음 네 종류다.

- `APPROVE`: 현재 판단과 Action 승인
- `REVISE`: 수정 조건과 대안 제시
- `VETO`: 전문 영역의 안전 정책 위반으로 실행 차단
- `ABSTAIN`: Evidence 부족으로 추가 관측 요청

### 5.4 Mutual Supervision Engine

최종 확장형 엔진은 다음 라운드를 실행한다.

1. 역할별 판단 생성
2. Peer Review Matrix에 따른 필수 검토
3. 수정 요청과 거부 사유 수집
4. 응용관리 Agent의 후보 Action 수정
5. 관련 Agent의 재검토
6. 합의 또는 안전 중단

첫 구현인 deterministic v1은 HA 진단을 입력으로 응용관리 Agent가 Action을
제안하고, HA·인프라·비용 Agent가 해당 실행 Action을 독립적으로 교차
검토한다. 실행 후에는 네 Agent가 모두 역할별 재평가를 수행한다. HA·인프라·
비용 판단까지 각각 다시 검토 대상으로 만드는 일반화된 완전 메시지 그래프는
후속 확장 범위다.

기본 최대 협상 횟수는 2회이며 실험 설정으로 변경할 수 있다. 단, 무제한
대화는 허용하지 않는다.

### 5.5 Consensus Policy

안전성 판단과 후보 선택을 분리한다.

```text
안전성 판단 = 역할별 Veto
안전한 후보 간 우선순위 = Reward
```

Reward가 높더라도 전문 영역의 `VETO`를 무시할 수 없다.

합의 조건:

1. 모든 필수 검토가 완료되어야 한다.
2. 전문 영역 `VETO`가 없어야 한다.
3. `REVISE`가 남아 있으면 다음 라운드로 이동해야 한다.
4. `ABSTAIN`은 Evidence 보강 후 재검토해야 한다.
5. 최대 라운드까지 합의하지 못하면 `observe_only` 또는
   `human_review_required`로 전환한다.

### 5.6 Safety Boundary

Agent 합의 결과를 자유 텍스트 명령으로 실행하지 않는다. 구조화된 Action만
실행 계층에 전달하며 실제 명령은 검증된 렌더러가 생성한다.

`real` 모드에서 다음 안전 경계는 항상 강제한다.

- Namespace/Deployment allowlist
- 등록된 Action 종류
- Replica 최소/최대 제한
- Kubernetes 이름 규칙
- 임의 셸 및 위험 명령 차단
- 한 대상당 하나의 활성 복구 작업
- 실행 전후 Kubernetes snapshot
- 실행 실패 시 cleanup
- 최대 재계획 횟수
- 안전 실패 시 사람 검토

연구 목적으로 안전 정책을 변경하는 비교는 `mock` 또는 `dry-run`에서만
허용한다. `real`에서는 고정 안전 경계를 우회할 수 없다.

### 5.7 Post-Execution Review

실행 후 각 Agent는 다음을 독립적으로 확인한다.

| Agent | 실행 후 검토 |
| --- | --- |
| HA | 서비스 가용성과 장애가 실제로 회복됐는가 |
| 응용관리 | Deployment/Pod 변경이 정상 완료됐는가 |
| 인프라 | CPU, Memory, Replica, 노드 상태가 안전한가 |
| 비용 | 불필요한 Replica 또는 자원 증가가 남았는가 |

실패가 보고되면 Evidence를 다시 수집하고 다음 후보 Action을 재협상한다.
최대 재계획 횟수를 초과하면 안전 중단하고 사람 검토가 필요함을 기록한다.

## 6. Agent 검토 관계

모든 Agent가 모든 메시지를 반복 검토하는 완전 연결 구조는 불필요한 대화량과
비용을 증가시킨다. 역할 기반 검토 관계를 사용한다. deterministic v1에서는
실행 결과를 바꾸는 응용관리 Action을 HA·인프라·비용의 세 독립 관점에서
검토한다. 아래 표는 후속 일반화 단계의 목표 검토 관계다.

| 최초 판단 | 필수 검토 Agent | 검토 목적 |
| --- | --- | --- |
| HA 장애 진단 | 응용관리, 인프라 | 실행 가능한 진단인지, 자원 상태와 일치하는지 |
| 응용관리 Action | HA, 인프라, 비용 | 복구 효과, 자원 안전성, 비용 적절성 |
| 인프라 용량 판단 | 응용관리, 비용 | 운영 가능성과 자원 증가 비용 |
| 비용 정책 판단 | 응용관리, 인프라 | 운영 가능성과 실제 자원 제약 |

역할별 강한 거부권 범위:

- HA: 가용성 악화 또는 복구 효과 부재
- 응용관리: 실행 불가능하거나 지원되지 않는 Action
- 인프라: 자원 용량, Replica 또는 배치 안전 위반
- 비용: 정책 한도를 넘는 불필요한 자원 증가

긴급 HA 복구처럼 비용과 가용성이 충돌하는 경우에도 비용 Agent의 판단을
삭제하지 않는다. 정책이 허용하는 긴급 예외 조건을 명시적으로 기록한 뒤
실행하며, 실행 후 자원 축소 검토를 의무화한다.

## 7. 데이터 모델

### 7.1 Agent Decision

필수 필드:

- `experiment_id`
- `run_id`
- `decision_id`
- `round`
- `agent`
- `decision_type`
- `diagnosis`
- `proposed_action`
- `approved`
- `reason`
- `confidence`
- `evidence_refs`
- `reward_components`
- `policy_version`
- `created_at`

### 7.2 Peer Review

필수 필드:

- `review_id`
- `experiment_id`
- `run_id`
- `round`
- `reviewer`
- `target_agent`
- `target_decision_id`
- `verdict`
- `reason`
- `suggested_action`
- `confidence`
- `evidence_refs`
- `policy_version`
- `created_at`

### 7.3 Negotiation Round

필수 필드:

- `round`
- `input_decision_ids`
- `review_ids`
- `revisions`
- `remaining_vetoes`
- `remaining_abstentions`
- `consensus_status`
- `selected_candidate_id`

### 7.4 Execution and Recovery

Action에는 고유 `action_id`를 부여한다. 실행과 복구 평가에는 다음을
기록한다.

- Action 구조
- Validation 결과
- 생성된 명령
- 실행 모드
- 실행 전후 snapshot
- 실행 stdout/stderr
- 복구 성공 여부
- 복구 시간
- Metric 변화
- 재계획 여부
- 사람 검토 필요 여부

## 8. 실행 상태 머신

```text
COLLECTING
  -> DIAGNOSING
  -> REVIEWING
  -> NEGOTIATING
  -> VALIDATING
  -> EXECUTING
  -> MONITORING
  -> SUCCEEDED
```

재계획:

```text
MONITORING
  -> REPLANNING
  -> REVIEWING
```

안전 중단:

```text
REVIEWING / VALIDATING / EXECUTING / MONITORING
  -> SAFE_STOPPED
  -> HUMAN_REVIEW_REQUIRED
```

## 9. 실행 모드

| 모드 | 목적 | Kubernetes 변경 |
| --- | --- | --- |
| `mock` | Agent 상호감시와 합의 구조 검증 | 없음 |
| `dry-run` | Kubernetes API/명령 호환성 검증 | 없음 |
| `real` | 실제 장애 복구 연구 | 있음 |

모든 모드는 동일한 판단과 기록 스키마를 사용해야 한다. 모드가 다르다는 이유로
연구 결과 스키마가 달라지면 안 된다.

## 10. 실험 설정

다음 항목을 버전이 있는 설정으로 관리한다.

- Agent 구성과 역할
- Peer Review Matrix
- 역할별 거부권
- 최대 재협상 횟수
- 합의 정책
- Action 후보
- Reward 가중치
- 장애 시나리오
- Controller 종류
- 실행 모드
- 최대 재계획 횟수

설정 파일의 해시 또는 버전을 각 실행 결과에 저장하여 동일 조건을 재현할 수
있게 한다.

## 11. 연구 결과 저장

기본 결과 구조:

```text
runs/mutual-supervision/<experiment_id>/
|-- experiment_config.json
|-- evidence.jsonl
|-- initial_decisions.jsonl
|-- peer_reviews.jsonl
|-- negotiation_rounds.jsonl
|-- safety_validations.jsonl
|-- executed_actions.jsonl
|-- post_execution_reviews.jsonl
|-- final_report.json
|-- final_report.md
`-- statistics.csv
```

파일은 `experiment_id`, `run_id`, `decision_id`, `review_id`, `action_id`로
연결한다.

## 12. 정량 평가 지표

### 합의 성능

- 합의 성공률
- 평균 재협상 횟수
- 평균 합의 시간
- 합의 실패율

### 상호감시 효과

- 반박 수
- Action 수정 수
- Veto 수
- 위험 Action 차단률
- 추가 Evidence 요청 수

### 복구 성능

- 복구 성공률
- 평균 복구 시간(MTTR)
- Metric 개선율
- 재계획 성공률

### 안전성과 효율성

- Validation 거부율
- 잘못된 실행 수
- 안전 중단 수
- 불필요한 Action 비율
- 추가 Replica
- 실행 Action 수

### Agent 기여

- Agent별 승인, 수정 요청, Veto 수
- 최종 Action 변경 기여도
- 실행 후 실패 탐지 기여도

### AutoGen 경로

- Token 사용량
- Agent별 응답시간
- API 비용
- 반복 실행 결과 일관성

## 13. 첫 구현 범위

1. 구조화 Decision, Peer Review, Negotiation 데이터 모델
2. Deterministic 상호감시 엔진
3. 역할별 Veto와 기본 최대 2회 재협상
4. 기존 Validator, Executor, Recovery Monitor 연결
5. 실행 후 네 Agent 재평가
6. 설정 기반 실험 실행 CLI
7. JSONL, JSON, Markdown, CSV 결과 저장
8. 기존 순차형과 비교 가능한 자동 테스트

후속 확장:

1. 동일 프로토콜을 사용하는 AutoGen Adapter
2. Prometheus/Chaos Mesh real 반복 실험
3. AIOpsLab Detection 결과 연결
4. 플랫폼의 상호감시 실험 화면
5. 실시간 판단, 반박, 합의 Timeline
6. 정량 그래프와 실험 비교 화면

## 14. 테스트 전략

### 단위 테스트

- Peer Review Matrix가 올바른 검토자를 선택한다.
- 각 Agent가 전문 영역에서만 강한 Veto를 생성한다.
- `REVISE` 후 Action이 수정된다.
- `VETO`가 Reward로 무시되지 않는다.
- `ABSTAIN`이 Evidence 요청으로 전환된다.
- 최대 라운드 초과 시 안전 중단한다.
- 모든 이벤트에 추적 ID와 정책 버전이 있다.

### 통합 테스트

- 합의된 안전 Action만 Executor에 전달된다.
- Validation 실패 Action은 실행 기록에 남지 않는다.
- 실행 실패 후 다음 후보로 재계획한다.
- 복구 실패 후 Post-Execution Review가 재협상을 요청한다.
- 최대 재계획 초과 시 `human_review_required`가 기록된다.
- `real` 안전 경계는 설정으로 비활성화할 수 없다.

### 회귀 테스트

- 기존 `AIMCMPCoordinator` 동작 유지
- 기존 `AutonomousAIOpsCoordinator` 동작 유지
- 기존 CLI 명령 유지
- 전체 Python 테스트 통과
- 선택적 독립 Guard가 존재하는 구성에서는 해당 테스트도 통과

## 15. 성공 기준

다음 조건을 모두 만족해야 첫 구현을 완료한 것으로 본다.

1. 동일 Evidence에서 기존 순차형과 상호감시형 실행을 비교할 수 있다.
2. 상호감시형 실행에는 최소 한 번의 명시적 Peer Review 단계가 존재한다.
3. 수정 요청이 Action 변경으로 연결되는 테스트가 있다.
4. 전문 영역 Veto가 위험 Action을 차단한다.
5. 합의 실패 시 Kubernetes 실행이 발생하지 않는다.
6. 실행 후 네 Agent의 재평가가 결과에 저장된다.
7. 정책 설정만 변경하여 합의와 Reward 실험을 구성할 수 있다.
8. 모든 실행이 재현 가능한 설정과 이벤트 로그를 남긴다.
9. 기존 기능과 테스트가 깨지지 않는다.
10. 실제 Kubernetes 제어 시 안전 경계를 우회할 수 없다.

## 16. 플랫폼 연결 원칙

웹 플랫폼은 연구 엔진의 대체물이 아니라 관찰과 실험 관리 계층이다. 핵심
엔진이 검증된 후 다음을 제공한다.

- 상호감시 실험 설정
- 현재 실행 단계와 경과시간
- Agent별 최초 판단
- Agent 간 반박과 수정 Timeline
- 최종 합의 및 안전 검증 결과
- Kubernetes 실행과 복구 상태
- 순차형/상호감시형/AutoGen 비교 그래프

웹에서 임의 명령을 입력해 실행하는 기능은 제공하지 않는다. Real 실행은
고정된 실험 프로파일, 명시적 승인, 안전 경계를 통해서만 가능해야 한다.

