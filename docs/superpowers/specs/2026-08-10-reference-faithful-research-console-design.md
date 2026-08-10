# 참고 화면 충실형 AIOps 연구 콘솔 설계

## 1. 목적

현재 4-Agent AIOps 연구 플랫폼의 기능과 백엔드 API를 유지하면서, 사용자가 실험의 목적과 진행 상태를 한눈에 이해할 수 있도록 화면 구조를 재설계한다.

참고 이미지의 명확한 정보 계층과 화면 분리를 채택하되, 이미지에 포함된 예시 수치나 연결 상태를 정적 값으로 복제하지 않는다. 모든 상태, Metric, Reward, MTTR 및 실험 결과는 현재 플랫폼 API와 `ExperimentSession`에서 가져온 실제 값만 표시한다.

## 2. 범위

이번 변경은 다음 다섯 화면을 대상으로 한다.

1. 시스템 개요
2. 복구 실험
3. AIOpsLab Benchmark
4. 실험 결과
5. 실험 상세

백엔드 실험 엔진, 4-Agent 의사결정, 안전 검증, Kubernetes 실행 경계 및 결과 저장 형식은 변경하지 않는다.

## 3. 공통 레이아웃

### 사이드바

- 고정 너비의 남색 사이드바를 사용한다.
- 브랜드, 네 개의 주 메뉴, 실제 시스템 연결 상태를 위에서 아래 순서로 배치한다.
- 현재 선택된 메뉴는 파란색 배경과 명확한 아이콘으로 표시한다.
- Kubernetes, Prometheus, Chaos Mesh, AIOpsLab, AutoGen 상태는 `/api/connections` 응답만 사용한다.
- 미연결 상태를 연결됨으로 꾸미지 않는다.

### 본문

- 흰색 또는 매우 옅은 회색 작업 영역을 사용한다.
- 화면마다 제목, 한 줄 설명, 주요 작업 버튼을 같은 위치에 둔다.
- 콘텐츠 최대 너비를 제한하여 넓은 모니터에서도 정보가 과도하게 퍼지지 않게 한다.
- 카드 반경은 작게 유지하고 중첩 카드는 사용하지 않는다.
- 파랑은 선택과 실행, 초록은 성공, 주황은 안전 중단, 빨강은 실패에만 사용한다.

## 4. 화면 설계

### 4.1 시스템 개요

시스템 개요는 현재 실험과 연구 파이프라인의 상태를 요약하는 대시보드다.

- 상단 상태 스트립: 시나리오, Controller, 실행 모드, 상태, 시작 시간
- 8단계 흐름: 장애 조건, Evidence, HA 진단, Action 제안, Infra/Cost 검토, 안전 검증, 실행, 복구 확인
- 빠른 실험 시작: 시나리오, Controller, 실행 모드, 고급 설정
- 현재 실행 상태: 단계 진행률과 최근 이벤트
- Agent 현황: HA, Application, Infrastructure, Cost의 판단과 승인 상태
- 최근 결과: 최종 Action, 복구 성공, MTTR, Reward, Evidence 변화

실행 중에는 단계가 순서대로 강조되며, 종료 후에는 성공·중단·실패 상태가 그대로 남는다.

### 4.2 복구 실험

복구 실험 화면은 설정을 위에서 아래 순서로 결정하는 작업 화면이다.

- 1단계: Pod Kill, CPU Stress, Memory Stress, Network Delay 선택 카드
- 2단계: Deterministic Mutual Supervision 또는 AutoGen Round-Robin 선택
- 3단계: Mock, Dry-run, Real 실행 모드 선택
- 고급 설정: Protocol Profile, 반복 횟수, AutoGen 모델
- 우측 요약: 선택된 시나리오, Controller, 실행 모드와 각 모드의 안전 경계

AutoGen 사용 조건이 충족되지 않으면 비활성 상태와 구체적인 사유를 표시한다. Real 실행은 현재의 확인 문구, 환경변수 Gate, allowlist 검증을 그대로 유지한다.

실험 시작 후 설정 영역은 실시간 실행 화면으로 전환되고, 단계, 경과 시간, Agent 판단, 안전 검증, 이벤트 로그와 취소 기능을 표시한다.

### 4.3 AIOpsLab Benchmark

AIOpsLab 화면은 복구 실험과 분리된 탐지 성능 평가 화면으로 구성한다.

- 좌측: 실제 benchmark catalog 시나리오 목록
- 중앙: 선택 시나리오 설명과 최근 평가 지표
- 우측: 실행 모드, 반복 횟수, 실행 버튼
- 하단: 최근 Benchmark 결과
- 탭: 벤치마크 평가, 모델 성능 비교, 실험 이력

현재 프로젝트가 계산하는 Accuracy, TTD, Steps, Reward와 evaluator 기반 Agent별 Reward를 우선 표시한다. F1, Precision, Recall, AUC는 실제 계산값이 존재할 때만 표시한다.

### 4.4 실험 결과

실험 결과 화면은 연구 데이터 조회와 비교를 담당한다.

- 탭: 실험 목록, 복구 전략 비교, 성과 대시보드
- 필터: 기간, 시나리오, Controller, 실행 모드, 결과
- 목록: Experiment ID, 실행 시간, 시나리오, Controller, 모드, 결과, MTTR, Reward
- 요약: 총 실험 수, 성공률, 평균 MTTR, 평균 Reward
- 결과 분포: 성공, 실패, 안전 중단을 구분

Mock, Dry-run, Real 결과는 배지와 Evidence Source를 통해 명확하게 구분한다. 합성 데이터는 실제 Kubernetes 성능 결과처럼 표시하지 않는다.

### 4.5 실험 상세

실험 상세 화면은 하나의 `experiment_id`에 속한 전체 연구 근거를 제공한다.

- 탭: 요약, 타임라인, Agent 판단, Evidence, 로그, 이벤트
- 요약: 결과, 최종 Action, MTTR, Reward, 안전 검증
- Evidence: 복구 전후 Metric과 Kubernetes 상태
- 실험 정보: 시나리오, Controller, 실행 모드, 시작·종료 시간
- Agent 합의: 각 Agent의 승인·거부·재협상 결과
- 작업: 결과 다운로드, 동일 설정 재실행

상세 화면은 저장된 Job 또는 `ExperimentSession`만 읽으며 화면용 임의 값을 생성하지 않는다.

## 5. 데이터와 상태 흐름

```text
Connection API
  -> 사이드바 연결 상태

Scenario/Controller/Mode 선택
  -> Experiment Job 생성
  -> SSE 진행 이벤트
  -> 4-Agent 판단 및 안전 검증
  -> 실행·복구 결과
  -> ExperimentSession/Artifact 저장
  -> 개요·결과·상세 화면 갱신

AIOpsLab Catalog
  -> Benchmark Job
  -> Detection Result
  -> Evaluator Reward
  -> 비교 및 이력 화면
```

## 6. 구현 원칙

- 기존 DOM ID와 API 호출 계약을 가능한 한 유지한다.
- `index.html`은 의미 있는 화면 구조만 담당한다.
- 공통 스타일과 화면별 스타일을 CSS 섹션으로 명확히 나눈다.
- 기존 JavaScript의 데이터 로딩과 Job 제어 로직을 재사용한다.
- `reference-ui.js`와 보조 스크립트의 중복 렌더링을 줄이고 화면별 렌더 함수의 책임을 분리한다.
- 접근 가능한 버튼, 탭, 폼 라벨과 키보드 포커스 상태를 제공한다.
- 모바일에서는 사이드바를 상단 메뉴 또는 접이식 내비게이션으로 전환한다.

## 7. 오류와 빈 상태

- 연결 실패: 해당 연결만 미연결로 표시하고 Mock 기능은 유지한다.
- 데이터 없음: 0이나 성공으로 꾸미지 않고 명시적인 빈 상태를 표시한다.
- Job 실패: 실패 단계, 원인, cleanup 결과를 함께 표시한다.
- AutoGen 자격증명 없음: Controller를 비활성화하고 설정 필요 사유를 표시한다.
- Real 실행 불가: 누락된 Kubernetes, Prometheus, Chaos Mesh 또는 AIOpsLab 조건을 열거한다.

## 8. 검증 기준

- 기존 Python 전체 테스트와 Go Guard 테스트가 통과해야 한다.
- 네 개 주요 메뉴와 실험 상세 화면이 모두 정상 전환되어야 한다.
- Mock 실험 생성, SSE 진행, 취소, 결과 조회가 기존과 동일하게 동작해야 한다.
- AIOpsLab benchmark 실행과 비교 탭이 정상 동작해야 한다.
- 1440x900, 1920x1080, 390x844 화면에서 잘림과 겹침이 없어야 한다.
- 브라우저 콘솔 오류가 없어야 한다.
- Mock, Dry-run, Real과 연결 상태가 실제 백엔드 값과 일치해야 한다.

## 9. 비범위

- 새로운 실험 엔진 개발
- Kubernetes·Prometheus·Chaos Mesh 설치 자동화
- 새로운 AIOpsLab 데이터셋 또는 Metric 계산식 추가
- 사용자 인증과 다중 사용자 권한 관리
- 정적 예시 데이터를 실제 연구 결과로 저장하는 기능
