# 4-Agent AIOps 연구 콘솔 정보 구조 개편 설계

## 1. 목적

현재 연구 콘솔은 복구 실험, Agent 판단, 결과, 비교 실험, AIOpsLab을 한 문서에
연속 배치한다. 기능은 연결되어 있지만 사용자가 현재 수행 중인 작업과 기능 간
관계를 파악하기 어렵다.

이번 개편의 목표는 기존 API와 실행 엔진을 유지하면서 다음 사용 흐름을 명확하게
제공하는 것이다.

```text
실험 조건
  -> Evidence
  -> 4-Agent 판단과 상호검토
  -> 합의와 안전 검증
  -> Kubernetes 복구
  -> 결과 분석과 기록
```

각 화면은 독립 도구가 아니다. 동일한 `ExperimentSession`을 서로 다른 관점에서
조회하고 조작하는 작업 화면이다.

## 2. 변경 원칙

- 기존 FastAPI, Job Runner, SSE, AutoGen, AIOpsLab, 비교 실험 API를 변경하지 않는다.
- 기존 `mock`, `dry-run`, `real` 안전 경계를 유지한다.
- 모든 화면이 현재 `experiment_id`, 시나리오, Controller, 합의 프로파일, 실행 단계를 공유한다.
- 한 화면에는 하나의 주요 작업만 둔다.
- 실제 연결이 없는 기능은 `미연결`로 표시하고 완료된 것처럼 보이지 않게 한다.
- AIOpsLab은 복구 실험 내부 단계가 아니라 별도 탐지 Benchmark로 유지한다.
- AutoGen은 별도 Agent가 아니라 4-Agent를 구동하는 선택 가능한 Controller로 표시한다.
- 기존 CLI와 연구 산출물 형식을 유지한다.

## 3. 화면 구조

### 3.1 운영 개요

연구 환경과 최근 실행을 빠르게 파악하는 첫 화면이다.

- 활성 `ExperimentSession`
- 현재 실행 단계와 상태
- Kubernetes, Prometheus, Chaos Mesh, AutoGen, AIOpsLab 연결 상태
- 최근 복구 실험과 Benchmark 요약
- 새 실험 시작 버튼

세부 Agent 판단, 긴 이벤트 로그, 전체 비교 그래프는 배치하지 않는다.

### 3.2 복구 실험

Chaos Mesh 기반 Kubernetes 복구 실험의 설정과 실행을 담당한다.

- 장애 시나리오: Pod Kill, CPU Stress, Memory Stress, Network Delay
- 실행 모드: Mock, Dry-run, Real
- Controller: Deterministic, AutoGen GroupChat
- 합의 프로파일과 반복 횟수
- 7단계 Job 진행 상태
- Evidence 요약
- 4-Agent 현재 판단
- 합의 Action과 안전 검증 요약
- 실행, 취소, 재연결

이벤트 로그는 기본적으로 접고, 실행 중이거나 오류가 발생한 경우에만 강조한다.

### 3.3 Agent 상호감시

4-Agent 연구 질문을 검증하는 상세 화면이다.

- Agent별 역할과 veto 범위
- 최초 판단과 Action 제안
- peer review와 수정 요청
- 재협상 라운드
- 최종 합의와 Agent별 기여
- Deterministic/AutoGen provenance
- AutoGen GroupChat transcript와 모델 상태

AutoGen 연결이 없으면 transcript 대신 연결 실패 이유를 표시한다.

### 3.4 관측 데이터

Agent 판단에 사용된 Evidence의 출처와 값을 확인한다.

- Prometheus metric과 timestamp
- Kubernetes deployment/pod snapshot
- Chaos Mesh 주입 상태
- Evidence provider 종류
- stale, empty, timeout 오류 구분
- Mock과 real Evidence 배지

이 화면은 실험 결과를 생성하지 않고 현재 세션의 Evidence를 설명한다.

### 3.5 비교 분석

복구 Action과 연구 프로파일을 반복 비교한다.

- 장애별 Action 성공률
- 평균 복구 시간
- Metric 개선률
- Reward 정책별 ranking
- Controller와 합의 정책 비교
- 반복 수와 measurement validity
- PNG, CSV, JSONL, Markdown 산출물

기존 recovery comparison Job API와 artifact URL을 그대로 사용한다.

### 3.6 AIOpsLab

AIOpsLab Detection Benchmark를 실행하고 결과를 조회한다.

- Benchmark 선택과 반복 횟수
- 환경 사전 점검
- 실행 상태와 SSE 이벤트
- Accuracy, TTD, Action steps, Reward
- 결과 파일 다운로드

Chaos Mesh 복구 결과와 혼합하지 않고 별도 실험 유형으로 표시한다.

### 3.7 실험 기록

서버에 저장된 실험과 산출물을 재조회한다.

- 최근 Experiment Job
- 최근 Recovery Comparison Job
- 최근 AIOpsLab Job
- 상태, 모드, Evidence 종류, 프로파일
- 산출물 다운로드
- 실행 중 Job 재연결

## 4. 공통 세션 컨텍스트

상단 공통 바는 화면 이동 후에도 다음 값을 유지한다.

| 필드 | 의미 |
| --- | --- |
| `experiment_id` | 현재 복구 실험 식별자 |
| `scenario` | 선택된 장애 시나리오 |
| `controller` | Deterministic 또는 AutoGen |
| `protocol_profile` | 합의와 veto 정책 |
| `current_stage` | 현재 Job 실행 단계 |

비교 실험과 AIOpsLab은 각각 `comparison_job_id`, `aiopslab_job_id`를 사용한다.
현재 복구 실험 식별자를 덮어쓰지 않는다.

## 5. 상태 관리

기존 JavaScript 상태 객체를 유지하되 화면 상태를 추가한다.

```text
activeView
current experimentId / job
current comparisonJobId / comparisonJob
current aiopslabJobId / aiopslabJob
connections
selectedScenario
events
```

화면 이동은 Job을 취소하거나 SSE를 끊지 않는다. URL hash로 현재 화면을 기록해
새로고침 후 같은 화면으로 복원한다. Job 복원은 기존 목록 API를 사용한다.

## 6. AutoGen 연결

AutoGen은 복구 실험 화면에서 Controller로 선택한다. Agent 상호감시 화면은
동일 실험의 transcript를 표시한다.

```text
Evidence
  -> AutoGen GroupChat 4-Agent
  -> 구조화된 AgentDecision
  -> 합의 결과
  -> Python Validator
  -> bounded Kubernetes Action
```

AutoGen도 Validator와 allowlist를 우회할 수 없다. Credential 또는 model client가
없으면 선택을 비활성화하고 정확한 원인을 표시한다.

## 7. 시각 설계

- 배경은 밝은 중성 회색, 주요 표면은 흰색으로 구성한다.
- 주색은 잉크 네이비, 상태 강조는 청록을 사용한다.
- 주의는 절제된 황색, 실패만 적색을 사용한다.
- 과도한 그라디언트, 장식 배경, 중첩 카드, 큰 둥근 모서리를 사용하지 않는다.
- 정보 밀도는 유지하되 화면마다 하나의 질문에만 답하도록 한다.
- Desktop은 고정 Sidebar와 본문, Mobile은 가로 스크롤 Navigation으로 전환한다.
- 긴 문자열은 줄바꿈하고 고정 형식 요소에는 안정적인 크기를 부여한다.

## 8. 오류와 안전 UX

- Real 실행은 기존 확인 문구와 서버 Gate를 유지한다.
- 연결 실패는 관련 화면에만 표시하고 다른 Mock 연구를 막지 않는다.
- 실행 중에는 단계, 경과시간, 이벤트 수, 취소 버튼을 표시한다.
- Validation 거부는 `failed`가 아니라 `blocked`와 사유로 표시한다.
- Cleanup 실패는 복구 성공과 별도로 강조한다.
- Mock, Dry-run, Real 결과를 색상과 텍스트 배지로 구분한다.
- 오래된 API/UI 버전은 전역 경고로 표시한다.

## 9. 구현 경계

이번 변경은 다음 파일의 UI 구조와 정적 계약에 집중한다.

- `ui/control_plane_static/index.html`
- `ui/control_plane_static/styles.css`
- `ui/control_plane_static/app.js`
- `tests/test_control_plane_ui.py`

백엔드 변경은 기존 API 응답에 UI가 반드시 필요로 하는 필드가 없는 경우에만
추가하며, 기존 route와 응답 필드를 삭제하지 않는다.

## 10. 검증 기준

- 일곱 개 화면이 독립적으로 전환된다.
- 화면 이동 후 현재 Job과 SSE 연결이 유지된다.
- 모든 기존 DOM ID와 API 호출이 보존된다.
- AutoGen 연결 상태와 transcript가 Agent 화면에서 확인된다.
- 비교 실험과 AIOpsLab이 복구 실험 화면에서 분리된다.
- Mock/Dry-run/Real 경계 문구가 유지된다.
- Desktop과 Mobile에서 겹침, 잘림, 가로 넘침이 없다.
- `python -m pytest`가 통과한다.
- 브라우저 콘솔 오류 없이 Mock 실험을 실행하고 결과 화면으로 이동할 수 있다.

## 11. 제외 범위

- 새로운 Kubernetes Action 추가
- 새로운 장애 시나리오 추가
- 인증과 사용자 관리
- 인터넷 공개 배포
- 백엔드 Job Runner 재작성
- Ubuntu real 결과를 로컬에서 대신 생성하는 기능
