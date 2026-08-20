# Model Partition Orchestrator Agent V2 통합 설계서

## 1. 목적

본 설계는 현재 구현된 결정론적 모델 분할 계획 기능을 통합 아키텍처의 `Model Partition Orchestrator Agent`로 확장한다. Agent는 상위 Coordination 계층이 승인한 학습 또는 추론 계획과 버전이 고정된 시스템 Context를 입력받아 다음 작업을 수행한다.

1. 입력 계약과 승인 출처를 정규화한다.
2. Training 또는 Inference Partition Strategy를 적용한다.
3. 결정론적으로 복수의 분할 후보와 실행 그래프를 생성한다.
4. 자원, 통신, 성능 요구량과 Hard Constraint를 평가한다.
5. 최종 `PartitionExecutionPlan`과 대안, 가정, 경고를 생성한다.
6. Scheduling 또는 Runtime 피드백을 받아 제한된 범위에서 재분할한다.

이 Agent는 실행 모드를 선택하지 않으며 Scheduling, 배치, 실제 학습·추론 실행을 담당하지 않는다. 검증된 실행 계획을 외부 Scheduling Agent에 전달하는 것이 책임의 끝이다.

## 2. 현재 구현과 확장 범위

### 2.1 현재 구현 완료

- 승인된 `FederatedRoundPlan` 입력 검증
- 순서가 고정된 모델 Layer와 참여 Device 표현
- 연속된 Split Point 후보 생성
- Logical Partition과 DAG 생성
- Compute, Memory, Communication, Latency 추정
- Memory, Transfer, Latency 제약 기반 후보 거부
- 버전이 있는 결정론적 정책 점수와 후보 선택
- Planner와 분리된 `PartitionPlanValidator`
- 실행 전 예측 Reward를 생성하는 `PartitionPlanEvaluator`
- 제한된 실패 신호를 이용한 재계획
- CLI, Control Plane API, Web Workspace, JSON Artifact

### 2.2 V2에서 추가

- Training과 Inference Coordination Plan 입력 계약 분리
- 읽기 전용 Common Context와 Workload Forecast 입력
- Common Processing Core
- Training/Inference Strategy Plugin
- Model Registry Context와 Model Structure Profile 참조
- Candidate 생성 전 Early Feasibility Validation
- 설명, 경고, Confidence를 포함한 후보 평가
- `PartitionExecutionPlan` 버전과 입력 Snapshot Hash
- Plan Repository와 부모·자식 재계획 이력
- Scheduling/Runtime Feedback 수신 계약
- Feedback 기반 Bounded Repartition
- UI의 Intake, Strategy, Candidate Analysis, Handoff/Feedback 단계화

## 3. 전체 아키텍처 위치

```text
Job Request + Workload Forecast + Shared State
                         |
                         v
Federated Coordination Agent
                         |
                         | TrainingCoordinationPlan
                         | or InferenceCoordinationPlan
                         v
Model Partition Orchestrator Agent
  1. Common Processing Core
  2. Training / Inference Partition Strategy
  3. Deterministic Planning Pipeline
  4. Plan Validation and Evaluation
  5. Plan Versioning and Repository
  6. Feedback Analysis and Bounded Repartition
                         |
                         | PartitionExecutionPlan
                         v
Scheduling Agent <-> Communication & Network Optimization Agent
                         |
                         v
AI Workload Execution Controller
```

기존 장애 복구 실험은 `Recovery Research Profile`로 유지한다. Model Partition 기능은 별도의 `AI Workload Orchestration Profile`에서 실행되며 복구용 HA/Application/Infrastructure/Cost Agent에 다섯 번째 Agent로 삽입하지 않는다.

## 4. 책임 경계

### 4.1 Agent가 수행하는 일

- 승인된 상위 Plan과 Snapshot의 형식·출처 검증
- 학습 또는 추론 전략에 필요한 Partition Intent 생성
- 분할 후보, Logical Partition, Execution Graph 생성
- 자원·통신·성능 요구량 추정
- Hard Constraint 적용과 실행 불가능 후보 차단
- 결정론적 후보 선택과 선택 근거 생성
- 검증된 Plan의 버전 저장과 Scheduling Handoff 준비
- 실패 Feedback에 대한 제한된 재분할 또는 사람 검토 요청

### 4.2 Agent가 수행하지 않는 일

- FL, SL, 일반 분산 추론 모드 선택
- Federated Participant와 Aggregation Policy 결정
- 실제 Queue, Placement, Dispatch 결정
- Network Route와 Bandwidth 최적화
- 학습·추론 Runtime 시작, 중단, 취소, Rollback
- 실제 GPU 성능이 없는 상태에서 실측 성능 주장
- 복구 실험용 4-Agent 역할 대체

## 5. 입력 계약

### 5.1 CoordinationPlanEnvelope

모든 입력은 공통 Envelope를 사용한다.

```text
CoordinationPlanEnvelope
- plan_type: training | inference
- plan_id
- job_id
- approved: true
- approved_by
- approval_ref
- approved_at
- schema_version
- payload
```

`approved`, `approved_by`, `approval_ref`, `schema_version` 중 하나라도 유효하지 않으면 Fail Closed 처리한다.

### 5.2 TrainingCoordinationPlan

```text
TrainingCoordinationPlan
- model_id
- approved_model_version
- coordination_mode
- participants
- round_policy
- aggregation_policy
- synchronization_policy
- training_objective
- resource_budget
- constraints
```

`coordination_mode`는 상위 계층의 승인 결과다. Model Partition Orchestrator는 이를 선택하지 않고 참조한다.

### 5.3 InferenceCoordinationPlan

```text
InferenceCoordinationPlan
- model_id
- approved_model_version
- service_objective
- latency_slo_ms
- minimum_throughput_rps
- availability_target
- traffic_policy
- concurrency_policy
- participants
- resource_budget
- constraints
```

### 5.4 PartitionSystemContext

Context는 계획 중 변경할 수 없는 읽기 전용 Snapshot이다.

```text
PartitionSystemContext
- snapshot_id
- snapshot_version
- collected_at
- model_structure_profile
- model_registry_context
- resource_snapshot
- network_assessment
- previous_plan_history
- workload_forecast
```

동일한 Plan, Context Snapshot, Policy Version은 동일한 결과를 생성해야 한다.

### 5.5 WorkloadForecast

Workload Forecast는 Advisory 입력이다. 누락되어도 기본 정책으로 계획할 수 있지만 출력의 가정과 Confidence에 반영한다.

```text
WorkloadForecast
- forecast_id
- horizon_seconds
- expected_request_rate
- expected_batch_size
- expected_sequence_length
- uncertainty
- source
```

## 6. Common Processing Core

Common Processing Core는 Training과 Inference 전략 전에 동일하게 실행된다.

### 6.1 Coordination Plan Intake & Normalizer

- 입력 Schema Version 확인
- 승인 출처 확인
- 단위와 식별자 정규화
- 중복 Participant 제거와 순서 고정
- 입력 Hash 생성

### 6.2 Workload Model Router

- `plan_type`에 따라 Training 또는 Inference Strategy 선택
- 알 수 없는 유형은 임의 추론하지 않고 `unsupported_plan_type`으로 차단

### 6.3 Model / Registry Context Resolver

- 승인된 모델 버전과 Registry 버전 일치 확인
- Model Structure Profile 조회
- Layer 순서, Parameter, Activation, Working Memory 정보 확인

### 6.4 Model Analyzer & Profile Resolver

- Layer와 Block 경계 정규화
- 분할 가능한 경계와 금지 경계 계산
- 공유 Parameter, Residual Connection, KV Cache 등 전략별 제약 표기

### 6.5 Constraint & Early Feasibility Validator

- 최소 참여 Device 수
- 모델 전체 Memory와 Device Memory
- 필수 Network Link
- SLA와 Resource Budget 형식
- Strategy 실행에 필요한 Metadata 존재 여부

초기 검증에 실패하면 후보 생성을 시작하지 않고 구조화된 Safe Failure를 반환한다.

## 7. Partition Strategy

Strategy는 공통 `PartitionStrategy` 계약을 구현한다.

```text
PartitionStrategy
- strategy_id
- strategy_version
- supports(plan_type, coordination_mode)
- build_partition_intent(plan, context)
- validate_strategy_constraints(intent)
```

출력 `PartitionIntent`는 다음 정보를 포함한다.

```text
PartitionIntent
- strategy_id
- allowed_partition_methods
- allowed_split_boundaries
- forbidden_split_boundaries
- graph_requirements
- memory_rules
- communication_rules
- optimization_objectives
- assumptions
- warnings
```

### 7.1 Training Partition Strategy

- DP, TP, PP, Hybrid 정책을 승인된 상위 Plan 범위에서 해석
- SL Split Point와 Forward/Backward Graph 생성 조건
- Gradient 및 Parameter Communication 추정 규칙
- Aggregation과 Checkpoint Boundary
- Worker Demand, Step Time, Load Balance 목적함수

### 7.2 Inference Partition Strategy

- Whole 또는 Split Inference
- TP, PP, SP, DP, Model Sharding 정책
- Forward-only Graph
- KV Cache와 Batch/Concurrency Memory
- Replica Demand
- Latency와 Throughput 목적함수

V2 첫 구현은 현재 기능을 `InferencePartitionStrategy`로 이동하는 것부터 시작한다. Training Strategy는 동일 계약 위에 별도로 추가한다.

## 8. Deterministic Planning Pipeline

### 8.1 Candidate Generator

- Strategy가 허용한 경계만 이용해 후보 생성
- 후보 순서는 항상 결정론적으로 정렬
- 후보마다 `candidate_id`와 생성 근거 저장

### 8.2 Execution Graph Builder

- Training은 Forward, Backward, Gradient, Aggregation Edge 지원
- Inference는 Forward, Pipeline, Cache Transfer Edge 지원
- 순환 여부와 Layer Coverage 검증 가능 구조 유지

### 8.3 Resource, Communication, Performance Estimators

- Device별 Compute와 Memory Demand
- Link별 Transfer Bytes와 Transfer Time
- 예상 Latency, Throughput, Step Time
- Training Communication과 Inference Activation/KV Cache 구분
- 추정치의 출처와 추정 모델 버전 기록

### 8.4 Hard Feasibility Filter

다음 위반은 점수 감점이 아니라 즉시 후보 거부로 처리한다.

- 승인되지 않은 실행 모드
- 모델 버전 불일치
- Layer 누락·중복·순서 위반
- DAG 순환
- Device Memory 초과
- 필수 Network Link 부재
- Resource Budget 초과
- 명시적 SLA 위반

### 8.5 Candidate Evaluator & Selector

유효 후보만 점수화한다. 점수는 Strategy별 Versioned Policy를 사용하며 실행 전에는 `predicted_reward`로 표기한다.

- Training: Step Time, Balance, Memory, Communication, Resilience
- Inference: Latency, Throughput, Memory, Communication, Replica Cost

동점은 안정적인 Candidate ID 순서로 결정한다.

### 8.6 Explanation, Warning, Confidence

선택 결과에는 다음 정보가 반드시 포함된다.

- 선택 이유
- 거부된 대안과 거부 이유
- 사용된 가정
- 입력 누락 또는 Forecast 불확실성 경고
- Confidence와 산정 근거
- 예측치와 실측치 구분

### 8.7 Plan Versioning & Repository

- `plan_id`
- `plan_version`
- `parent_plan_id`
- `input_snapshot_hash`
- `policy_version`
- `strategy_version`
- `created_at`
- `replan_reason`

Plan은 기존 JSON Artifact 구조에 저장하며 이후 SQLite Job Store와 연결할 수 있는 식별자를 유지한다.

## 9. 출력 계약

```text
PartitionExecutionPlan
- plan_id
- plan_version
- parent_plan_id
- job_id
- model_id
- approved_model_version
- plan_type
- approved_execution_mode
- strategy_id / strategy_version
- policy_version
- input_snapshot_id / input_snapshot_hash
- logical_partitions
- execution_graph
- resource_demand
- communication_demand
- performance_estimates
- selected_candidate
- alternative_candidates
- assumptions
- warnings
- confidence
- validation_result
- predicted_reward
- handoff_status
- human_review_required
- errors
```

`validation_result.valid=true`인 Plan만 Scheduling Handoff 대상이 된다. 출력은 실행 명령이 아니다.

## 10. Scheduling Handoff

Scheduling Agent는 본 저장소 외부 구성요소로 취급한다. V2는 다음 경계까지만 구현한다.

```text
SchedulingHandoff
- handoff_id
- partition_plan_id
- partition_plan_version
- created_at
- status: ready | acknowledged | rejected
- scheduler_ref
```

실제 Scheduler가 없는 환경에서는 `ready` 상태와 JSON Artifact까지만 생성한다. Mock 응답을 실제 Scheduling 성공으로 표시하지 않는다.

## 11. Feedback Analysis와 Bounded Repartition

### 11.1 Feedback 계약

```text
PartitionRuntimeFeedback
- feedback_id
- plan_id / plan_version
- source: scheduler | runtime | network | operator
- signal
- observed_metrics
- failed_device
- failed_link
- reason
- received_at
```

지원 신호:

- `placement_rejected`
- `device_unavailable`
- `memory_exceeded`
- `latency_slo_violation`
- `throughput_slo_violation`
- `transfer_failure`
- `runtime_capacity_changed`

### 11.2 제한 재분할 규칙

1. 원본 입력과 Snapshot Version을 보존한다.
2. Feedback과 충돌하는 후보 또는 자원만 제외한다.
3. 정책의 최대 재계획 횟수까지만 수행한다.
4. 새 Plan은 이전 Plan을 `parent_plan_id`로 참조한다.
5. 개선되지 않거나 후보가 없으면 `human_review_required=true`로 종료한다.
6. 무한 재계획과 자동 범위 확대를 금지한다.

## 12. Control Plane API

기존 API를 유지하면서 V2 계약을 추가한다.

```text
GET  /api/model-partition/examples
POST /api/model-partition/plans
GET  /api/model-partition/plans/{plan_id}
POST /api/model-partition/plans/{plan_id}/feedback
GET  /api/model-partition/plans/{plan_id}/history
GET  /api/model-partition/strategies
```

기존 `FederatedRoundPlan` 요청은 Legacy Adapter가 `InferenceCoordinationPlan`과 `PartitionSystemContext`로 변환한다. 기존 CLI와 테스트는 유지한다.

## 13. 플랫폼 UI

`AI Workload Orchestration` Workspace는 네 단계로 구성한다.

### 13.1 Plan Intake

- Training/Inference Plan 유형
- 승인 Plan ID와 승인 주체
- Model 및 Model Version
- Context Snapshot Version
- Participant와 Forecast 요약
- 입력 검증 상태

### 13.2 Partition Strategy

- 적용 Strategy와 Version
- 허용·금지 Split Boundary
- Graph와 Memory 규칙
- 적용 목적함수
- 가정과 경고

### 13.3 Candidate Analysis

- 후보별 Latency, Throughput 또는 Step Time
- Memory Pressure와 Communication
- 정책 점수와 Hard Constraint 상태
- 선택된 Logical Partition과 Execution Graph
- 거부 후보의 구체적인 거부 이유

### 13.4 Handoff & Feedback

- 독립 Validator 결과
- Predicted Reward와 Confidence
- Plan Version과 Snapshot Hash
- Scheduling Handoff 상태
- Feedback와 재분할 Timeline
- 원본 Plan과 재분할 Plan 비교

각 단계는 요약을 기본으로 표시하고 상세 근거는 명시적으로 펼친다. 실행 전 예측 결과와 실제 Runtime Feedback을 색상과 문구로 구분한다.

## 14. Artifact와 재현성

각 실행은 다음 Artifact를 저장한다.

- 원본 Coordination Plan
- 정규화된 입력
- Context Snapshot과 Hash
- Strategy Intent
- 전체 후보와 거부 이유
- 선택된 PartitionExecutionPlan
- Validator 결과
- Predicted 또는 Observed Evaluation
- Scheduling Handoff
- Feedback와 Repartition History
- Policy, Strategy, Schema Version

동일 입력 재현성 검증을 위해 비결정적 Timestamp와 ID를 제외한 `deterministic_signature`를 생성한다.

## 15. 실패 처리

모든 실패는 구조화된 Error Code와 사용자 메시지를 제공한다.

- `approved_plan_required`
- `approval_provenance_required`
- `unsupported_plan_type`
- `model_version_mismatch`
- `model_profile_missing`
- `invalid_system_snapshot`
- `strategy_not_supported`
- `early_feasibility_failed`
- `no_feasible_partition`
- `partition_validation_failed`
- `scheduling_handoff_rejected`
- `replan_attempts_exhausted`

Unexpected Exception의 전체 Traceback은 서버 로그에 기록하고 UI에는 요약 메시지와 Plan/Job ID만 표시한다.

## 16. 시험 전략

### 16.1 계약 시험

- Training/Inference Plan 역직렬화
- 승인 정보와 Model Version 누락 차단
- Snapshot 불변성과 Hash 안정성
- Legacy 입력 호환성

### 16.2 Strategy 시험

- Training/Inference Router
- 지원하지 않는 Mode Fail Closed
- Split Boundary와 Graph Requirement
- Forecast 유무에 따른 가정과 Confidence

### 16.3 Planning 시험

- 동일 입력의 동일 Candidate 순서와 선택 결과
- Layer Coverage와 DAG
- Training Forward/Backward 및 Inference Forward Graph
- 자원·통신·성능 추정
- Hard Constraint 후보 차단

### 16.4 Feedback 시험

- Scheduling Reject 후 대안 Plan 선택
- Device/Link 실패 후 자원 제외
- SLA 위반 후 이전 후보 제외
- 최대 재계획 횟수와 Human Review 전환
- 부모·자식 Plan Version History

### 16.5 API/UI 시험

- 기존 API 회귀 방지
- Plan Intake부터 Handoff까지 단계 표시
- 예측과 실측 결과 구분
- 실패 시 Traceback 미노출
- Desktop/Mobile Overflow 및 키보드 접근성

## 17. 단계별 구현 순서

### Phase 1: 계약과 호환성

- V2 입력·출력 모델
- Legacy Adapter
- Context Snapshot Hash
- 기존 시험 유지

### Phase 2: Common Core와 Inference Strategy

- 현재 Planner를 Inference Strategy 기반 Pipeline으로 이동
- Registry/Profile Resolver
- Early Feasibility Validator

### Phase 3: Training Strategy

- 학습 Graph와 Communication 규칙
- Training Candidate 평가 정책

### Phase 4: Versioning과 Handoff

- Plan Repository
- Scheduling Handoff Artifact와 API

### Phase 5: Feedback와 Repartition

- Feedback API
- Plan History
- Bounded Repartition

### Phase 6: UI와 연구 실험

- 4단계 Workspace
- 결정성, 정책 비교, Feedback 재계획 실험
- 정량 통계와 다운로드 Artifact

## 18. 완료 기준

- 기존 Recovery Profile, CLI, API, 테스트가 유지된다.
- 기존 Model Partition 요청은 Legacy Adapter로 계속 동작한다.
- Training과 Inference Plan이 명시적으로 분리된다.
- 동일 Plan, Snapshot, Policy는 동일한 결정론적 Signature를 생성한다.
- Hard Constraint 위반 후보는 선택될 수 없다.
- 출력에는 Plan Version, Snapshot Hash, Strategy/Policy Version이 존재한다.
- Scheduling Feedback으로 생성된 Plan은 부모 Plan과 사유를 추적할 수 있다.
- 재계획 실패는 안전 중단과 Human Review로 종료된다.
- UI에서 입력, 전략, 후보, 검증, Handoff, Feedback 관계가 구분된다.
- Mock/예측 결과를 실제 GPU·Runtime 결과로 표시하지 않는다.
- 전체 Python 테스트와 Go Guard 테스트가 통과한다.

