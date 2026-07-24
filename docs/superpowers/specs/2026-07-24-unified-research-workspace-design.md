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

## 4. 운영 실험 화면

### 4.1 상단 실행 컨텍스트

화면 상단에는 현재 세션에 필요한 정보만 고정 표시한다.

- `experiment_id`
- 실행 모드
- 대상 namespace/deployment
- 현재 단계
- 최종 상태
- 사람 검토 필요 여부

### 4.2 단계 내비게이션

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

### 4.3 본문 구성

본문은 세 영역으로 구성한다.

- **실험 설정 영역:** 장애 시나리오와 안전 범위를 설정한다.
- **의사결정 타임라인:** Evidence, Agent 제안, peer review, revision/veto,
  consensus, safety gate, execution, post-review를 시간순으로 표시한다.
- **실행 컨텍스트 레일:** 현재 Action, Validator 결과, recovery 상태,
  artifact 경로를 요약한다.

시각적으로는 독립 카드의 반복을 줄이고 하나의 연속 타임라인과
구분선 기반 레이아웃을 사용한다.

## 5. 백엔드 인터페이스

### 5.1 플랫폼 capability

```http
GET /api/platform
```

응답에는 `api_version`, 지원 기능, 실행 경계를 포함한다.
프론트엔드가 기대하는 버전과 다르거나 endpoint가 없으면
`서버 재시작 필요` 상태를 명확히 표시한다. 이를 통해 정적 UI 파일만
갱신되고 FastAPI 프로세스가 이전 라우트를 유지하는 문제를 숨기지 않는다.

### 5.2 통합 mock 실행

```http
POST /api/experiments/mock
```

기존 mutual-supervision 엔진을 실행하고 정규화된 `ExperimentSession`을
반환한다. UI의 모든 단계는 이 응답 하나를 공유한다.

### 5.3 세션 조회

```http
GET /api/experiments/{experiment_id}
```

현재 프로세스에서 실행한 세션을 다시 조회한다. 초기 구현은 제한된
in-memory session registry를 사용하고, 연구 산출물은 기존 JSONL/JSON
event store에 계속 저장한다.

`real` 실행 endpoint는 이번 UI 범위에 추가하지 않는다. 실제 Kubernetes
변경은 기존 CLI에서 명시적으로 승인해야 한다.

## 6. Agent 상호감시 표현

현재 deterministic v1 계약을 정확히 반영한다.

1. HA Agent가 장애와 복구 필요성을 진단한다.
2. Application Agent가 bounded Action 후보를 제안한다.
3. HA, Infrastructure, Cost Agent가 제안을 독립적으로 검토한다.
4. `approve`, `revise`, `veto`, `abstain`을 라운드별로 표시한다.
5. 합의된 Action만 Python Validator와 선택적 Go Guard로 전달한다.
6. 실행 후 4개 Agent가 역할별로 결과를 재평가한다.

Coordinator는 다섯 번째 의사결정 Agent로 표현하지 않는다. 세션 상태,
메시지 전달, 라운드, 합의 조건을 관리하는 protocol coordinator로 표시한다.

## 7. 오류 및 안전 경계

- endpoint 부재 또는 API 버전 불일치는 일반 실행 실패와 구분한다.
- API non-2xx 응답을 정상 결과처럼 렌더링하지 않는다.
- validation 실패 시 실행 단계를 `blocked`로 표시한다.
- lock 충돌, allowlist 위반, replica 제한 위반은 이유와 함께 표시한다.
- 실행되지 않은 Action은 post-execution review가 없는 이유를 표시한다.
- unknown metric은 `observe_only` 또는 안전 중단으로 처리한다.
- mock 결과를 real Kubernetes 결과처럼 표시하지 않는다.

## 8. 실험 기록 연결

운영 실험이 완료되면 다음 연결을 제공한다.

- 현재 세션 JSON
- JSONL event streams
- statistics CSV
- final report Markdown
- 기존 recovery-action-pilot 결과
- full-stack 및 AIOpsLab 결과

현재 세션은 `실험 기록` 화면의 첫 항목으로 즉시 나타난다. 서버에만 존재하는
기존 real 결과와 브라우저의 mock 세션은 모드와 출처를 명확히 구분한다.

## 9. 검증 기준

### 기능 검증

- 한 번의 mock 실행으로 7단계가 같은 `experiment_id`를 표시한다.
- 상호감시 결과가 안전 검증과 결과 화면에 자동 반영된다.
- 화면을 이동해도 현재 세션이 유지된다.
- API 오류가 빈 합의 결과로 보이지 않고 오류 상태로 표시된다.
- 이전 서버 프로세스가 실행 중이면 재시작 안내가 표시된다.

### 안전 검증

- 웹 UI는 mock 실행만 제공한다.
- allowlist와 replica 제한이 기존 Validator에서 유지된다.
- Go Guard 선택 시 결과 metadata에 backend가 표시된다.
- validation 실패 Action은 실행 결과에 포함되지 않는다.

### 회귀 검증

- `python -m pytest`
- `cd go/aiops-guard && go test ./...`
- 데스크톱 및 모바일 브라우저에서 가로 넘침과 텍스트 중첩 확인
- 대시보드, 운영 실험, Agent & Policy, 실험 기록, 연구 문서 라우트 확인

## 10. 구현 범위

이번 구현에 포함한다.

- 사이드바 정보 구조 개편
- 통합 운영 실험 화면
- `ExperimentSession` 정규화
- platform capability/version 확인
- mock 세션 실행·조회 API
- 현재 세션의 실험 기록 연결
- UI/API 오류 처리와 테스트

이번 구현에 포함하지 않는다.

- 웹 UI에서 real Kubernetes 실행
- Prometheus·로그의 완전한 real evidence fusion
- AutoGen 자유 토론 기반 일반화된 message graph
- 인증, 다중 사용자, 외부 데이터베이스

