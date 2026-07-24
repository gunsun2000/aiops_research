# 통합 AIOps 연구 워크스페이스 설계

## 1. 목적

현재 Control Plane은 대시보드, 장애 실험, 4-Agent 판단, 상호감시,
안전 검증, 실험 결과를 각각 독립된 화면과 프론트엔드 상태로 관리한다.
백엔드 기능은 연결되어 있지만 사용자는 하나의 실험이 단계별로 이어진다는
느낌을 받기 어렵다.

이번 개편의 목적은 다음과 같다.

- 하나의 실험 조건과 `experiment_id`를 전체 운영 흐름이 공유한다.
- 장애 관측부터 Agent 판단, 상호검토, 안전 검증, 실행, 사후평가까지
  하나의 화면에서 추적한다.
- 개별 기능 설명보다 현재 실험의 상태, 근거, 결정, 결과를 우선 표시한다.
- 플랫폼의 mock 안전 경계와 CLI 기반 real 실행 경계를 정확히 유지한다.
- 향후 AutoGen 다중 라운드, Prometheus enrichment, real Kubernetes 실행을
  같은 세션 모델에 추가할 수 있게 한다.

## 2. 연구 플랫폼의 정보 구조

사이드바는 기능 단계를 나열하지 않고 연구 작업 단위로 정리한다.

1. **연구 개요**
   - 연구 목표, 프레임워크 상태, 최근 실험, 주요 성능 지표
2. **운영 실험**
   - 장애 조건 설정
   - Evidence
   - 4-Agent 판단과 상호감시
   - 안전 검증과 실행
   - 사후평가와 결과
3. **Agent & Policy**
   - Agent Registry
   - 역할, 허용 Action, 상호검토 관계
   - Action/Reward 및 안전 정책
4. **실험 기록**
   - 현재 세션과 기존 JSONL/CSV/PNG/Markdown 산출물
   - 결과 비교와 통계
5. **연구 문서**
   - DOCX 연구 보고서와 운영·시험 가이드

기존의 `장애 실험`, `4-Agent 판단`, `상호감시 실험`, `안전 검증`은
사이드바의 독립 메뉴에서 제거하고 `운영 실험`의 단계로 통합한다.

## 3. 통합 실험 세션 모델

플랫폼은 다음 형태의 단일 세션을 기준으로 렌더링한다.

```text
ExperimentSession
├── experiment_id
├── created_at
├── mode
├── status
├── protocol_profile
│   ├── profile_id
│   ├── profile_version
│   └── config_hash
├── condition
│   ├── namespace
│   ├── deployment
│   ├── scenario
│   ├── metric
│   ├── value
│   └── threshold
├── evidence
├── diagnosis
├── initial_decisions
├── peer_reviews
├── negotiation
├── selected_action
├── safety_validation
├── execution_result
├── post_execution_reviews
├── recovery_observation
└── artifacts
```

프론트엔드는 별도의 `mockResult`, `mutualResult`, `latestRun`을 핵심 상태로
사용하지 않는다. `currentSession`을 단일 진실 공급원으로 사용하고,
기존 서버 실험 결과는 `experimentHistory`로 분리한다.

## 4. 교체 가능한 연구 프로토콜

### 4.1 ResearchProtocolProfile

상호감시 규칙과 실험 조건은 Coordinator 코드에 고정하지 않는다.
실행 엔진은 다음 구조의 `ResearchProtocolProfile`을 입력으로 받는다.

```text
ResearchProtocolProfile
├── profile_id
├── version
├── agent_set
│   ├── implementation_id
│   ├── enabled
│   ├── runtime
│   ├── model
│   ├── veto_scope
│   └── consensus_weight
├── review_matrix
├── consensus_strategy
├── max_negotiation_rounds
├── max_replan_attempts
├── fallback_action
├── action_space
├── reward_weights
├── evidence_policy
├── scenario_set
└── experiment_tags
```

프로파일 원문은 정규화한 뒤 SHA-256 설정 해시를 생성한다. 모든 실험 결과와
event stream에는 `profile_id`, `version`, `config_hash`를 함께 기록한다.

### 4.2 기본 4-Agent 프로파일

기본 프로파일은 `four-agent-role-veto-v1`로 정의한다.

| Agent | 주 역할 | blocking veto 범위 |
| --- | --- | --- |
| HA | 장애·가용성·복구 필요성 | 가용성 저하, 복구 실패 위험 |
| Application | bounded Action 제안 | Action 실행 가능성, 대상 서비스 일치 |
| Infrastructure | 용량·Replica·자원 검토 | 자원 안전성, 인프라 수용 한계 |
| Cost | 비용·과잉 대응 검토 | 예산 상한, 불필요한 자원 증가 |

기본 합의 규칙은 다음과 같다.

- 각 Agent는 자신의 `veto_scope` 안에서만 blocking veto를 행사한다.
- scope 밖의 반대는 `revise` 또는 non-blocking objection으로 기록한다.
- 최대 2회 자동 재협상한다.
- 합의 실패 시 `observe_only`로 전환하고 `human_review_required=true`를 남긴다.
- Python Validator는 프로파일과 무관하게 필수 안전 경계로 유지한다.
- Go Guard는 선택적인 이종 구현 교차 검증으로 유지한다.

### 4.3 교체 가능한 합의 전략

최소 세 가지 전략을 공통 인터페이스로 제공한다.

- `role_based_veto`: 역할 범위 안의 veto가 blocking이다.
- `unanimous_veto`: 하나의 veto라도 있으면 재협상 또는 안전 중단한다.
- `weighted_majority`: Agent별 가중치로 합의를 계산한다.

합의 전략이 달라져도 allowlist, replica limit, command validation 같은
최종 안전 검증은 우회할 수 없다. `weighted_majority`가 인프라 경고를
승인하더라도 Validator가 안전 범위를 위반한 Action을 차단한다.

### 4.4 동적 Agent Registry

4-Agent는 기본 구성이며 실행 엔진의 고정 필드로 취급하지 않는다.
Registry는 다음 정보를 가진다.

- Agent 이름과 연구 역할
- `implementation_id`
- deterministic 또는 AutoGen runtime adapter
- 활성화 여부
- 입력 Evidence 종류
- 생성 가능한 Action 또는 review 종류
- `veto_scope`
- 검토 대상
- 모델·프롬프트 참조

프로파일은 Registry에 등록된 Agent 구현체를 추가, 비활성화, 교체할 수 있다.
완전히 새로운 판단 로직은 `AgentAdapter` 구현과 Registry 등록이 필요하다.
설정 파일만으로 임의의 Python 코드를 실행하지 않는다.

### 4.5 실험 변수와 비교

코어 엔진을 수정하지 않고 다음 비교가 가능해야 한다.

- 단방향 검토와 상호감시
- 1회 합의와 다중 라운드 재협상
- 역할별 veto, 전체 veto, 가중 다수결
- deterministic Agent와 AutoGen Agent
- Reward 정책별 Action 변화
- Agent 비활성화·교체
- 새로운 등록 Agent 추가
- 안전장치 구성 비교

장애 시나리오와 Action도 Registry로 관리한다. 기존 handler로 표현할 수 있는
시나리오와 Action은 설정으로 조합하고, 새로운 Kubernetes 제어 동작은
별도의 bounded Action adapter와 Validator 규칙을 등록해야 한다.

## 5. 운영 실험 화면

### 5.1 상단 실행 컨텍스트

화면 상단에는 현재 세션에 필요한 정보만 고정 표시한다.

- `experiment_id`
- 프로토콜 프로파일과 설정 해시
- 실행 모드
- 대상 namespace/deployment
- 현재 단계
- 최종 상태
- 사람 검토 필요 여부

### 5.2 단계 내비게이션

다음 7단계를 하나의 연결된 단계 표시기로 제공한다.

1. 조건 설정
2. Evidence
3. Agent 진단
4. 상호검토·합의
5. 안전 검증
6. 실행·복구 관찰
7. 결과·산출물

실행 전에는 조건 설정만 활성화한다. 실행 후에는 모든 완료 단계가
동일한 `experiment_id`의 데이터로 채워진다. 사용자는 단계 표시기를 눌러
세부 패널로 이동할 수 있지만, 별도의 애플리케이션처럼 전환되지는 않는다.

### 5.3 본문 구성

본문은 세 영역으로 구성한다.

- **실험 설정 영역:** 장애 시나리오와 안전 범위를 설정한다.
- **의사결정 타임라인:** Evidence, Agent 제안, peer review, revision/veto,
  consensus, safety gate, execution, post-review를 시간순으로 표시한다.
- **실행 컨텍스트 레일:** 현재 Action, Validator 결과, recovery 상태,
  artifact 경로를 요약한다.

시각적으로는 독립 카드의 반복을 줄이고 하나의 연속 타임라인과
구분선 기반 레이아웃을 사용한다.

`Agent & Policy` 화면에서는 실행 전에 프로파일을 선택하고 다음 항목을
비교할 수 있게 한다.

- Agent 구성과 runtime
- 역할별 veto 범위
- review matrix
- 합의 전략과 최대 라운드
- Action space
- Reward 가중치

## 6. 백엔드 인터페이스

### 6.1 플랫폼 capability

```http
GET /api/platform
```

응답에는 `api_version`, 지원 기능, 실행 경계를 포함한다.
프론트엔드가 기대하는 버전과 다르거나 endpoint가 없으면
`서버 재시작 필요` 상태를 명확히 표시한다. 이를 통해 정적 UI 파일만
갱신되고 FastAPI 프로세스가 이전 라우트를 유지하는 문제를 숨기지 않는다.

### 6.2 프로토콜 조회

```http
GET /api/protocol-profiles
GET /api/protocol-profiles/{profile_id}
```

등록된 프로파일과 설정 해시를 반환한다. UI는 반환된 프로파일만 실행
요청에 사용할 수 있다.

### 6.3 통합 mock 실행

```http
POST /api/experiments/mock
```

기존 mutual-supervision 엔진을 실행하고 정규화된 `ExperimentSession`을
반환한다. 요청에는 `profile_id`를 포함하고 UI의 모든 단계는 이 응답
하나를 공유한다.

### 6.4 세션 조회

```http
GET /api/experiments/{experiment_id}
```

현재 프로세스에서 실행한 세션을 다시 조회한다. 초기 구현은 제한된
in-memory session registry를 사용하고, 연구 산출물은 기존 JSONL/JSON
event store에 계속 저장한다.

`real` 실행 endpoint는 이번 UI 범위에 추가하지 않는다. 실제 Kubernetes
변경은 기존 CLI에서 명시적으로 승인해야 한다.

## 7. Agent 상호감시 표현

현재 deterministic v1 계약을 정확히 반영한다.

1. HA Agent가 장애와 복구 필요성을 진단한다.
2. Application Agent가 bounded Action 후보를 제안한다.
3. HA, Infrastructure, Cost Agent가 제안을 독립적으로 검토한다.
4. `approve`, `revise`, `veto`, `abstain`을 라운드별로 표시한다.
5. 합의된 Action만 Python Validator와 선택적 Go Guard로 전달한다.
6. 실행 후 4개 Agent가 역할별로 결과를 재평가한다.

Coordinator는 다섯 번째 의사결정 Agent로 표현하지 않는다. 세션 상태,
메시지 전달, 라운드, 합의 조건을 관리하는 protocol coordinator로 표시한다.

## 8. 오류 및 안전 경계

- endpoint 부재 또는 API 버전 불일치는 일반 실행 실패와 구분한다.
- API non-2xx 응답을 정상 결과처럼 렌더링하지 않는다.
- validation 실패 시 실행 단계를 `blocked`로 표시한다.
- lock 충돌, allowlist 위반, replica 제한 위반은 이유와 함께 표시한다.
- 실행되지 않은 Action은 post-execution review가 없는 이유를 표시한다.
- unknown metric은 `observe_only` 또는 안전 중단으로 처리한다.
- mock 결과를 real Kubernetes 결과처럼 표시하지 않는다.
- 존재하지 않는 Agent, Action, 프로파일 참조를 실행 전에 거부한다.
- 프로파일 설정 해시가 실행 도중 변경되면 해당 세션을 중단한다.

## 9. 실험 기록 연결

운영 실험이 완료되면 다음 연결을 제공한다.

- 현재 세션 JSON
- JSONL event streams
- statistics CSV
- final report Markdown
- 기존 recovery-action-pilot 결과
- full-stack 및 AIOpsLab 결과
- 프로토콜 프로파일 원문과 설정 해시
- Agent별 veto, revision, 기여도

현재 세션은 `실험 기록` 화면의 첫 항목으로 즉시 나타난다. 서버에만 존재하는
기존 real 결과와 브라우저의 mock 세션은 모드와 출처를 명확히 구분한다.

## 10. 검증 기준

### 기능 검증

- 한 번의 mock 실행으로 7단계가 같은 `experiment_id`를 표시한다.
- 상호감시 결과가 안전 검증과 결과 화면에 자동 반영된다.
- 화면을 이동해도 현재 세션이 유지된다.
- API 오류가 빈 합의 결과로 보이지 않고 오류 상태로 표시된다.
- 이전 서버 프로세스가 실행 중이면 재시작 안내가 표시된다.
- 모든 결과에 동일한 profile ID, version, config hash가 기록된다.
- Agent & Policy 화면에서 프로파일별 차이를 확인할 수 있다.

### 안전 검증

- 웹 UI는 mock 실행만 제공한다.
- allowlist와 replica 제한이 기존 Validator에서 유지된다.
- Go Guard 선택 시 결과 metadata에 backend가 표시된다.
- validation 실패 Action은 실행 결과에 포함되지 않는다.
- 역할 범위 밖 blocking veto는 정책에 따라 revise 또는 objection으로 처리된다.
- 합의 전략을 바꿔도 필수 Validator를 우회할 수 없다.

### 연구 확장성 검증

- 역할별 veto 프로파일에서 최대 2회 재협상이 적용된다.
- `unanimous_veto`와 `weighted_majority`가 서로 다른 합의 결과를 생성한다.
- Agent 비활성화가 프로파일과 실행 결과에 반영된다.
- 등록되지 않은 Agent 구현체는 안전하게 거부된다.
- deterministic/AutoGen adapter 선택이 실행 metadata에 기록된다.
- 프로파일을 바꾼 두 실행을 설정 해시로 구분할 수 있다.

### 회귀 검증

- `python -m pytest`
- `cd go/aiops-guard && go test ./...`
- 데스크톱 및 모바일 브라우저에서 가로 넘침과 텍스트 중첩 확인
- 대시보드, 운영 실험, Agent & Policy, 실험 기록, 연구 문서 라우트 확인

## 11. 구현 범위

이번 구현에 포함한다.

- 사이드바 정보 구조 개편
- 통합 운영 실험 화면
- `ExperimentSession` 정규화
- `ResearchProtocolProfile` schema, loader, 설정 해시
- 4-Agent 기본 프로파일
- 동적 Agent Registry와 Agent adapter 경계
- 역할별 veto, 전체 veto, 가중 다수결 전략
- Agent 활성화·교체와 등록 구현체 추가 경로
- 프로파일·합의·Agent 기여도 연구 로그
- platform capability/version 확인
- 프로토콜 조회 API
- mock 세션 실행·조회 API
- 현재 세션의 실험 기록 연결
- UI/API 오류 처리와 테스트

이번 구현에 포함하지 않는다.

- 웹 UI에서 real Kubernetes 실행
- Prometheus·로그의 완전한 real evidence fusion
- 임의 Agent 코드를 설정 파일만으로 동적 실행
- 등록되지 않은 임의 Kubernetes Action 실행
- 모든 프로토콜 조합의 real-cluster 비교 실험 완료
- AutoGen 자유 토론 기반 완전 일반화 message graph
- 인증, 다중 사용자, 외부 데이터베이스
