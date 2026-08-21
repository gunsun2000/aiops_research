# Model Partition Orchestrator Agent Learned Candidate Ranker 설계서

## 1. 목적

본 설계는 현재의 `Model Partition Orchestrator Agent`에 학습 기반 후보 순위화 기능을 추가한다. 외부 통합 아키텍처와 입출력 계약은 변경하지 않는다.

```text
Federated Coordination Agent
        |
        | CoordinationPlan + SystemSnapshot + optional WorkloadForecast
        v
Model Partition Orchestrator Agent
        |
        | validated PartitionExecutionPlan
        v
Scheduling Agent (External)
```

AI는 Hard Constraint를 통과한 분할 후보들의 실행 후 Reward를 예측하고 후보 순위를 보조한다. 실행 모드 승인, 후보 생성, 안전성 판정, Scheduling, 실제 Runtime 제어는 학습 모델에 위임하지 않는다.

첫 번째 목표는 기존 결정론적 정책을 제거하는 것이 아니라 다음 세 선택 방식을 동일 Agent 내부에서 비교할 수 있게 만드는 것이다.

1. `deterministic`: 기존 버전 정책 점수로 선택한다.
2. `shadow`: 결정론적 후보를 선택하되 학습 모델의 추천과 예측을 함께 기록한다.
3. `learned_guarded`: 학습 모델이 충분한 신뢰도를 가질 때만 후보를 선택하고, 그 외에는 결정론적 정책으로 자동 복귀한다.

## 2. 연구 질문

- RQ1. 실행 후 관측된 성능을 학습한 Ranker가 결정론적 정책보다 높은 Runtime Reward의 후보를 추천하는가?
- RQ2. Workload Forecast와 System Snapshot을 포함하면 후보 순위의 정확도가 향상되는가?
- RQ3. Snapshot, Workload, Network 조건이 변할 때 학습 Ranker의 일반화 성능은 유지되는가?
- RQ4. 신뢰도 기반 Fallback이 잘못된 AI 선택을 제한하면서도 정책 개선 효과를 유지하는가?

## 3. 범위와 비범위

### 3.1 포함 범위

- 현재 결정론적 Candidate Generator와 Hard Feasibility Filter 재사용
- 공통 `CandidateRanker` 계약
- 결정론적 Ranker와 학습 기반 Reward Prediction Ranker
- 실행 결과를 후보 단위 학습 Dataset으로 변환
- 모델 학습, 평가, 버전 저장, 로딩
- Shadow 및 Guarded Learned 선택
- 선택 근거, 모델 버전, 예측 Reward, Fallback 이유 저장
- Control Plane API, CLI, Web Workspace에서 정책 선택과 비교 결과 표시
- 기존 Evaluator와 Runtime Feedback을 학습 Label로 연결

### 3.2 제외 범위

- FL, SL, 일반 분산 추론 실행 모드 선택 또는 검증 책임 변경
- Federated Coordination Agent의 Participant, Round, Aggregation 정책 결정
- Scheduling Agent의 Queue, Placement, Dispatch 구현
- Communication & Network Optimization Agent의 Route와 Bandwidth 결정
- 실제 학습·추론 Runtime 실행
- Hard Constraint를 학습 모델이 우회하거나 완화하는 기능
- LLM이 분할 계획 JSON을 직접 생성하거나 실행 후보를 무검증으로 선택하는 기능
- 실제 관측 데이터 없이 학습 성능 또는 최적 정책을 주장하는 기능

## 4. 내부 아키텍처

외부 아키텍처는 유지하고 `Candidate Evaluator & Selector` 내부만 확장한다.

```text
CoordinationPlan + Immutable Context
                  |
                  v
Common Processing Core
                  |
                  v
Training / Inference Partition Strategy
                  |
                  v
Deterministic Candidate Generator
                  |
                  v
Hard Feasibility Filter
                  |
                  +-------------------------------+
                  | feasible candidates only      |
                  v                               v
       Deterministic Policy Ranker      Learned Reward Ranker
                  |                               |
                  +-------------+-----------------+
                                v
                  Selection Mode Controller
             deterministic | shadow | learned_guarded
                                |
                                v
                    Independent Plan Validator
                                |
                                v
                 Versioned PartitionExecutionPlan
                                |
                                v
                    Scheduling Handoff (External)

Runtime / Scheduling Feedback
                  |
                  v
Evaluator -> Candidate Outcome Dataset -> Offline Trainer
```

`Hard Feasibility Filter`는 Ranker보다 앞에 위치하고 `PartitionPlanValidator`는 선택 후 독립적으로 다시 검증한다. 따라서 학습 모델은 실행 불가능 후보를 실행 가능하게 만들 수 없다.

## 5. Candidate Ranker 계약

새 모듈 `partition_ranking.py`에 다음 개념을 둔다.

```text
CandidateRanker
- rank(request, intent, candidates) -> CandidateRanking
- ranker_id
- ranker_version
- feature_schema_version
```

```text
CandidateRanking
- selected_candidate_key
- ordered_candidates
- selection_mode
- active_ranker
- model_version
- model_artifact_hash
- confidence
- fallback_used
- fallback_reason
- rationale
```

```text
CandidateRankingEntry
- candidate_key
- baseline_score
- predicted_reward
- prediction_confidence
- rank
- eligible
- warnings
```

`candidate_key`는 Split Point, Device 배정, Strategy Version을 canonical JSON으로 직렬화한 뒤 SHA-256으로 생성한다. 임의 Timestamp와 Plan ID는 Key에 포함하지 않는다.

기존 `PartitionCandidate.score`는 결정론적 Baseline 점수로 보존한다. 학습 모델의 `predicted_reward`로 덮어쓰지 않는다. Baseline은 낮을수록 우수하고 Reward 예측은 높을수록 우수하므로 두 값을 명시적으로 분리한다.

### 5.1 DeterministicPolicyRanker

현재 정렬 규칙을 그대로 유지한다.

```text
(not candidate.valid, candidate.score, candidate.split_points)
```

동일 입력, 동일 Snapshot, 동일 Policy Version은 동일 후보를 선택한다.

### 5.2 LearnedRewardRanker

유효 후보 각각에 대해 Runtime Reward를 예측하고 다음 순서로 정렬한다.

1. `predicted_reward` 내림차순
2. `prediction_confidence` 내림차순
3. 기존 `baseline_score` 오름차순
4. `candidate_key` 오름차순

예측치는 `[-1.0, 1.0]` 범위로 제한한다. 모델 추론 오류, Schema 불일치, 비유한 값은 예외를 외부로 전파하지 않고 구조화된 Fallback으로 처리한다.

## 6. 선택 모드

### 6.1 Deterministic

- 기존 Ranker만 실행한다.
- 기존 CLI, API, 시험의 기본값으로 유지한다.
- 과거 입력과 출력의 호환성을 보장한다.

### 6.2 Shadow

- 실제 `selected_candidate`는 Deterministic Ranker가 결정한다.
- Learned Ranker의 추천, 예측 Reward, 순위 차이를 Artifact에 기록한다.
- 학습 모델이 없어도 실험은 중단하지 않는다.
- 실제 제어 권한은 없다.

Shadow는 첫 번째 운영 단계이며, 충분한 Real Runtime Outcome이 쌓이기 전에는 기본 연구 모드로 사용한다.

### 6.3 Learned Guarded

다음 조건을 모두 만족할 때만 Learned Ranker의 후보를 선택한다.

- 모델 Artifact Hash 검증과 Feature Schema Version 일치
- 학습 Dataset이 최소 표본 기준 충족
- 모델 검증 지표가 정책 기준 충족
- 현재 Feature가 학습 범위에서 심각하게 이탈하지 않음
- 예측 Confidence가 정책 임계값 이상
- 추천 후보가 Hard Feasibility Filter를 통과함
- 선택 후 독립 Validator 재검증 통과

하나라도 만족하지 않으면 Deterministic Ranker로 복귀하고 `fallback_reason`을 저장한다. Fallback은 실패가 아니라 안전한 정상 동작이다.

## 7. Feature Schema

Feature는 `partition-feature-v1`로 버전 관리한다. 원본 식별자와 자유 텍스트를 모델 입력으로 직접 사용하지 않는다.

### 7.1 Request와 Context Feature

- `plan_type`: training 또는 inference one-hot
- 승인된 Execution Mode one-hot
- Layer 수와 Participant 수
- 총 Compute Units
- 총 Parameter, Activation, Working Memory Bytes
- Device Compute 처리량의 최소, 평균, 최대
- Device 가용 Memory의 최소, 평균, 최대
- Network Bandwidth의 최소, 평균, 최대
- Network Latency의 최소, 평균, 최대
- 최대 허용 Latency와 Transfer Bytes
- 최소 Memory Headroom Ratio
- Workload Forecast의 Request Rate, Batch Size, Sequence Length
- Forecast Uncertainty와 각 누락 여부 Indicator

### 7.2 Candidate Feature

- Partition 수
- 각 Partition Compute Share의 최소, 평균, 최대
- `estimated_compute_ms`
- `estimated_transfer_ms`
- `estimated_total_latency_ms`
- `estimated_step_time_ms`
- `total_transfer_bytes`
- `gradient_transfer_bytes`
- `maximum_memory_pressure`
- `maximum_load_imbalance`
- `predicted_resilience_risk`
- 기존 `baseline_score`
- Split Point의 정규화된 최소, 평균, 최대 위치

모든 연속 Feature는 Model Artifact에 저장된 학습 통계로 정규화한다. Feature 추가·삭제·의미 변경은 Feature Schema Version을 증가시킨다.

## 8. 학습 Label과 Dataset

### 8.1 Label

기본 Label은 동일 후보 실행 후 `PartitionPlanEvaluator`가 생성한 `observed` Reward다.

```text
target_reward = observed PartitionEvaluation.reward
range = [-1.0, 1.0]
```

다음 조건을 모두 만족한 Outcome만 기본 학습 Dataset에 포함한다.

- `evidence_level == observed`
- Runtime Evidence의 `source`와 `observed_at` 존재
- Plan ID, Plan Version, Candidate Key가 일치
- Validator가 해당 실행 전 결과에 포함됨
- Metrics가 유한하고 단위 검증을 통과함

예측 Reward, Mock, Dry-run, 합성 Outcome은 실제 관측 Dataset과 섞지 않는다. 이들은 별도 `synthetic` 또는 `predicted` Dataset Scope로 저장하며 Real 성능 주장에 사용하지 않는다.

### 8.2 한 행의 구조

```text
PartitionRankingTrainingRow
- row_id
- job_id
- plan_id / plan_version
- candidate_key
- input_snapshot_hash
- policy_version / strategy_version
- feature_schema_version
- features
- target_reward
- reward_components
- evidence_level
- evidence_source / observed_at
- selected_by
- selection_probability (알 수 없으면 null)
- runtime_outcome_ref
```

한 번 실행된 선택 후보에 대해서만 관측 Label을 부여한다. 실행되지 않은 대안 후보에 선택 후보의 Reward를 복사하지 않는다. 대안의 반사실적 Reward가 없으므로 초기 Dataset은 선택 편향을 가진다는 사실을 보고서에 명시한다.

### 8.3 Dataset 분할

동일 Job, Snapshot 또는 Plan Lineage가 학습과 시험에 동시에 들어가지 않도록 Group 단위로 분리한다. 단순 행 무작위 분할은 데이터 누수 위험 때문에 사용하지 않는다.

## 9. 학습 모델과 Artifact

첫 구현은 Reward 회귀 기반 선형 Ranker를 사용한다.

- 학습: `scikit-learn`의 정규화된 Ridge Regression
- Runtime 추론: JSON으로 내보낸 계수와 정규화 통계를 이용한 순수 Python 계산
- 이유: 작은 Dataset에서도 재현 가능하고, Feature별 영향과 선택 근거를 설명할 수 있으며, Runtime에 Pickle 로딩을 요구하지 않음

`scikit-learn`은 `ml` Optional Dependency로만 추가한다. 기존 기본 설치와 Deterministic 실행은 ML 의존성 없이 계속 동작한다.

```text
PartitionRankerModelArtifact
- schema_version
- model_type: ridge_reward_regressor
- model_version
- feature_schema_version
- trained_at
- training_dataset_hash
- training_scope
- sample_count / group_count
- feature_order
- feature_mean / feature_scale
- coefficients / intercept
- training_feature_ranges
- validation_metrics
- confidence_policy
- artifact_hash
```

Artifact는 JSON으로 저장하고 Canonical Hash를 검증한다. 임의 외부 경로의 Model Artifact를 Web 요청으로 직접 로딩하지 않는다. 서버가 허용한 Model Registry 경로의 Artifact만 사용할 수 있다.

## 10. Confidence와 분포 이탈

`prediction_confidence`는 LLM식 주관적 확률이 아니라 다음 근거를 결합한 운영 지표다.

- Hold-out MAE와 Rank Correlation
- 학습 표본 수와 Group 수
- 현재 Feature의 학습 범위 이탈 비율
- Forecast 누락과 Uncertainty
- 모델 Artifact 검증 상태

초기 정책 기본값은 다음과 같이 둔다.

- 최소 관측 표본: 30
- 최소 독립 Group: 5
- 최대 허용 Hold-out MAE: 0.25
- 최소 Spearman Rank Correlation: 0.30
- 최소 선택 Confidence: 0.70
- 심각한 Out-of-Distribution Feature 비율: 20% 이상

이 값은 `config/model_partition_policy.json`의 버전 정책으로 이동하며 실험을 통해 조정한다. 기준 미달 모델은 `shadow`에서는 표시할 수 있지만 `learned_guarded` 선택 권한을 갖지 않는다.

## 11. Evaluator와 Feedback 연결

현재 `PartitionPlanEvaluator`는 Predicted 또는 Observed Reward를 생성한다. Learned Ranker는 Evaluator를 대체하지 않는다.

```text
PartitionExecutionPlan
        |
        v
External Scheduling / Runtime
        |
        v
ObservedPartitionMetrics + Runtime Feedback
        |
        v
PartitionPlanEvaluator
        |
        +-> observed reward and components
        +-> bounded repartition signal
        +-> candidate outcome dataset row
```

Evaluator는 사후 평가와 Label 생성의 권위 있는 구성요소다. Ranker는 이전 Outcome을 학습해 사전 후보 순위를 예측한다. 동일 실행의 Evaluator Reward를 해당 실행 전에 사용하지 않는다.

`placement_rejected`, `device_unavailable`, `transfer_failure`, `latency_slo_violation`은 기존 Bounded Repartition 경로를 유지한다. 재분할에서도 동일 선택 모드를 적용하되 이전에 제외된 후보와 자원은 다시 활성화하지 않는다.

## 12. 출력과 재현성 Metadata

`PartitionExecutionPlan` 또는 Plan Report에 다음 선택 Metadata를 추가한다.

```text
selection
- mode
- active_ranker_id / active_ranker_version
- baseline_selected_candidate_key
- learned_selected_candidate_key
- final_selected_candidate_key
- model_version / model_artifact_hash
- feature_schema_version
- ranking_entries
- confidence
- fallback_used / fallback_reason
```

`deterministic_signature`에는 선택 모드, Ranker Version, Model Artifact Hash와 최종 선택 후보를 포함한다. 동일 입력, 동일 Snapshot, 동일 정책, 동일 Model Artifact는 동일 결과를 생성해야 한다.

## 13. API와 CLI

기존 API와 CLI의 기본 동작은 변경하지 않는다.

### 13.1 Plan 요청 확장

```text
selection_mode: deterministic | shadow | learned_guarded
ranker_model_version: optional registered version
```

요청에서 임의 파일 경로는 받지 않는다.

### 13.2 상태 조회

```text
GET /api/model-partition/rankers
GET /api/model-partition/rankers/{model_version}
```

상태 응답은 Model 존재 여부, Schema 호환성, 학습 Scope, 표본 수, 검증 지표, Guarded 사용 가능 여부를 포함한다.

### 13.3 연구용 CLI

```text
aiops-k8s-agents build-partition-ranking-dataset
aiops-k8s-agents train-partition-ranker
aiops-k8s-agents evaluate-partition-ranker
aiops-k8s-agents plan-model-partition-v2 --selection-mode shadow
```

학습 명령은 입력 Artifact, 출력 Dataset/Model, Dataset Hash, Model Version을 명시적으로 출력한다.

## 14. 플랫폼 UI

기존 `AI Workload Orchestration` Workspace의 네 단계 구조는 유지한다.

### Plan Intake

- 기존 입력과 Snapshot 출처 표시
- Selection Mode 선택
- 등록된 Model Version과 사용 가능 상태 표시

### Partition Strategy

- Strategy와 정책 목적함수 표시
- 결정론적 후보 생성과 Hard Constraint 경계가 AI와 무관함을 표시

### Candidate Analysis

- 후보별 Baseline Score와 Predicted Reward를 분리해 표시
- Baseline 선택과 AI 추천을 나란히 비교
- 선택 이유와 상위 Feature 기여도 표시
- Shadow에서는 `AI 추천은 실행 선택에 사용되지 않음`을 명시

### Handoff & Feedback

- 최종 선택 주체와 Fallback 여부
- 독립 Validator 결과
- Predicted와 Observed Reward 구분
- Runtime Feedback 이후 Outcome과 학습 Dataset 반영 여부
- Scheduling은 외부 Agent임을 유지

Model Artifact가 없거나 기준 미달이면 Learned Guarded 선택을 비활성화하고 이유를 표시한다. Mock/Predicted Dataset으로 학습한 모델은 `연구용 합성 모델`로 표시하며 Real Runtime 검증 모델과 같은 상태로 보이지 않게 한다.

## 15. 안전 경계

1. 후보 생성과 Hard Constraint는 결정론적 코드가 담당한다.
2. 학습 Ranker는 유효 후보만 입력받는다.
3. 최종 선택은 독립 Validator를 다시 통과해야 한다.
4. 모델 누락, 손상, Schema 불일치, 낮은 Confidence, 분포 이탈은 결정론적 Fallback으로 처리한다.
5. Learned Ranker는 Participant, Resource Budget, SLA 또는 금지 Split Boundary를 변경할 수 없다.
6. Scheduling Agent와 Runtime Controller에 직접 명령을 전송하지 않는다.
7. 예측 결과와 실제 관측 결과를 UI, JSON, 보고서에서 구분한다.
8. 실제 관측 Dataset이 부족하면 AI가 구현되어 있어도 성능 개선을 주장하지 않는다.

## 16. 실험 설계

### 16.1 Offline 평가

- Hold-out MAE와 RMSE
- Spearman Rank Correlation
- Baseline 선택과 Learned 추천의 Top-1 일치율
- 관측 후보 집합에서의 NDCG
- 학습 Scope별 성능: predicted, synthetic, observed

실행하지 않은 후보의 실제 Reward가 없으면 Regret와 최적 후보 적중률을 확정 지표로 보고하지 않는다.

### 16.2 Shadow 실험

- Baseline 선택과 Learned 추천 불일치율
- 추천 후보의 Confidence 분포
- Fallback 사유 분포
- Workload, Snapshot, Strategy별 성능 변화
- Feature 분포 이탈률

### 16.3 Guarded Online 비교

충분한 관측 데이터와 안전 검증 후 통제된 조건에서 수행한다.

- Deterministic 대 Learned Guarded의 Observed Reward
- Step Time 또는 Latency
- Memory Pressure와 Transfer Bytes
- Validator 거부율
- Runtime/Scheduling Feedback 발생률
- 재분할 횟수와 Human Review 전환율

후보 선택 정책의 인과 효과를 비교하려면 허용된 후보 내 통제된 탐색 또는 무작위 배정과 충분한 반복이 필요하다. 과거 선택 로그만으로 장애별 또는 Workload별 전역 최적 정책을 주장하지 않는다.

## 17. 시험 전략

### 17.1 Ranker 단위 시험

- 기존 Deterministic 정렬 결과 보존
- Learned Reward 내림차순과 안정적 Tie-break
- 유효하지 않은 후보가 Learned Ranker에 전달되지 않음
- Model Artifact Hash와 Feature Schema 검증
- 비유한 예측, 누락 Feature, OOD 입력의 Fallback
- 동일 입력과 Artifact의 동일 순위

### 17.2 Dataset 시험

- Predicted와 Observed Outcome 분리
- Plan, Version, Candidate Key 불일치 거부
- 실행되지 않은 대안에 Label을 복사하지 않음
- Group 기반 Train/Test 분리
- Dataset Hash 안정성

### 17.3 통합 시험

- `deterministic`의 기존 Plan과 Signature 호환성
- `shadow`가 최종 선택을 변경하지 않음
- `learned_guarded`가 신뢰도 기준 미달 시 Fallback
- Learned 선택 후 Validator 거부 시 실행 또는 Handoff 차단
- Feedback Replan에서 누적 제외 조건 보존
- API, CLI, UI에 Ranker Metadata 노출

### 17.4 연구 경계 시험

- Mock/Predicted Model을 Real 검증 완료로 표시하지 않음
- Scheduling 실행 성공을 내부에서 합성하지 않음
- 모델이 없어도 Deterministic 계획 가능
- ML Optional Dependency가 없어도 기존 전체 시험 통과

## 18. 파일 경계

### 신규 모듈

- `partition_ranking.py`: Ranker Protocol, Deterministic 및 Learned Ranker, Fallback
- `partition_features.py`: 버전 Feature 추출과 OOD 검사
- `partition_learning.py`: Dataset, Offline Trainer, 평가와 JSON Model Export
- `partition_ranker_repository.py`: 허용된 Model Artifact 저장과 Hash 검증

### 수정 모듈

- `model_partition_agent.py`: Candidate 생성과 Ranker 선택을 분리
- `partition_models.py`: Ranking Metadata 계약
- `partition_service.py`: Selection Mode와 Ranker 주입, Outcome Dataset 연결
- `partition_evaluator.py`: Candidate Outcome Label 생성 Metadata 보강
- `partition_artifacts.py`: Ranking과 Model Provenance 저장
- `partition_repository.py`: Plan과 Model Version 참조 보존
- `control_plane_web.py`: Ranker 상태와 요청 옵션 API
- `cli.py`: Dataset, 학습, 평가 명령
- `config/model_partition_policy.json`: Ranker Guard와 Confidence 정책
- `pyproject.toml`: 선택적 `ml` 학습 의존성
- `ui/control_plane_static/*`: Baseline/AI 비교와 Fallback 표시

## 19. 단계별 구현 순서

### Phase 1: Ranker 추상화와 호환성

- `CandidateRanker`와 `DeterministicPolicyRanker`
- 기존 선택 결과와 Signature 회귀 시험
- Plan Report의 Selection Metadata

### Phase 2: Dataset과 Model Artifact

- Feature Extractor
- Observed Outcome Dataset Builder
- Group Split과 Offline Evaluation
- JSON Ridge Model 학습·내보내기·검증

### Phase 3: Shadow Mode

- Learned Ranker 로딩과 예측
- Baseline과 Learned 추천 동시 기록
- API, CLI, UI 비교 표시
- Predicted, Synthetic, Observed Scope 표시

### Phase 4: Learned Guarded

- Confidence와 OOD Gate
- 결정론적 Fallback
- 독립 Validator 재검증
- 통제된 비교 실험

### Phase 5: Feedback 학습 루프

- Runtime Outcome 자동 Dataset 반영
- Model Version 갱신은 Offline 승인 절차로만 수행
- 기존 Plan의 Model Provenance 보존
- Shadow 재평가 후 다음 Guarded Version 승격

## 20. 완료 기준

1. 외부 `CoordinationPlan -> PartitionExecutionPlan -> Scheduling Handoff` 계약이 유지된다.
2. 기존 Deterministic 입력은 기존 후보를 선택하고 기존 시험이 통과한다.
3. AI Ranker는 Hard Constraint를 통과한 후보만 순위화한다.
4. Shadow Mode는 Plan 선택을 바꾸지 않고 비교 근거를 저장한다.
5. Learned Guarded는 신뢰도 또는 Schema 기준 미달 시 Deterministic으로 복귀한다.
6. Plan에 Ranker, Feature Schema, Model Artifact Hash와 Fallback 근거가 남는다.
7. Observed Outcome만 기본 학습 Label로 사용하고 Mock/Predicted 데이터와 분리한다.
8. 동일 입력, Snapshot, Policy, Model Artifact는 동일 결과를 생성한다.
9. Scheduling과 실제 Runtime 실행은 외부 범위로 유지된다.
10. 기존 Recovery, AIOpsLab, AutoGen, Model Partition Legacy 경로가 깨지지 않는다.
11. ML Optional Dependency 없이 기존 Deterministic Runtime과 전체 시험이 동작한다.
12. 실제 관측 데이터가 부족한 상태를 `AI 성능 검증 완료`로 표시하지 않는다.
