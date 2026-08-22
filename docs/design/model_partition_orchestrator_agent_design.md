# Model Partition Orchestrator Agent 설계

## 1. 책임 범위

Model Partition Orchestrator Agent는 상위 Coordination Agent가 승인한 학습 또는 추론
계획과 읽기 전용 System Snapshot을 받아 `PartitionExecutionPlan`을 생성한다. 이 Agent는
실행 모드를 새로 선택하거나 GPU에 작업을 배치하지 않는다.

```text
Approved Coordination Plan + Versioned System Snapshot
  -> Deterministic Candidate Generator
  -> Hard Feasibility Filter
  -> Candidate Ranker
  -> Final Selector
  -> PartitionPlanValidator
  -> PartitionExecutionPlan
  -> External Scheduling Agent
```

Scheduling Agent는 외부 구성요소이며, Queue·placement·dispatch·실제 Runtime 실행을
담당한다. Orchestrator의 출력은 runtime schedule이 아니라 검증된 분할 계획이다.

## 2. 결정 권한

| 구성요소 | 소유 책임 | 권한 경계 |
| --- | --- | --- |
| Common Processing Core | 승인 정보, 모델 구조, Snapshot 정규화 | 상위 승인 내용을 변경하지 않음 |
| Deterministic Candidate Generator | 허용된 split boundary에서 후보 생성 | 재현 가능한 동일 입력·동일 후보군 |
| Hard Feasibility Filter | 메모리, 통신, 그래프, 정책 제약 검사 | 실패 후보를 학습 Ranker에 전달하지 않음 |
| Candidate Ranker | feasible 후보의 상대적 가치 순위화 | AI Ranker는 Hard Constraint를 통과한 후보만 순위화 |
| Final Selector | 모드별 최종 후보 결정과 안전 폴백 | Guard 실패 시 Baseline으로 복귀 |
| PartitionPlanValidator | 최종 계획 독립 검증 | Ranker보다 권위가 높으며 승인/거부 최종 경계 |
| Artifact Repository | 입력, 후보, 선택, 검증, 결과 provenance 저장 | HMAC 키는 외부에서 주입 |

## 3. 선택 모드

### Deterministic

- 정책 점수와 split point 순서로 후보를 정렬한다.
- `Baseline 선택`과 `최종 선택`이 같다.
- 학습 모델 없이 항상 재현할 수 있는 기준선이다.

### Shadow

- 등록된 Ranker가 `AI 추천`과 `predicted reward`를 계산한다.
- `최종 선택`은 항상 `Baseline 선택`을 유지한다.
- 모델 성능을 운영 결정과 분리해 비교하는 연구 모드다.

### Learned Guarded

- 관측 데이터로 학습한 등록 Ridge artifact만 사용할 수 있다.
- 표본 수, 독립 그룹 수, holdout MAE, 순위 상관성, Feature schema, OOD,
  confidence guard를 통과한 경우에만 AI 추천이 최종 선택에 영향을 줄 수 있다.
- Guard 실패, 모델 무결성 실패, 후보 부적합 시 `fallback_reason`을 기록하고
  Baseline 선택으로 안전하게 복귀한다.

## 4. Reward와 Evidence

`predicted reward`는 계획 생성 시 Ranker가 추정한 후보 가치다. `observed Evaluator
reward`는 외부 Scheduler와 Runtime 실행 후 관측 지표로 계산한 사후 결과다. 두 값을
같은 성능 근거로 취급하지 않는다.

| 값 | 생성 시점 | 사용 목적 |
| --- | --- | --- |
| Baseline score | 계획 시점 | 결정론적 정책 기준선 |
| Predicted reward | 계획 시점 | AI 후보 순위와 Shadow 비교 |
| Observed Evaluator reward | Runtime 종료 후 | 실제 결과 평가와 학습 label |

기본 Real Dataset에는 외부 HMAC 키로 인증된 observed Runtime outcome만 포함된다.
predicted, synthetic, mock, dry-run 결과는 실제 Runtime 성능이나 학습 label로 사용하지
않는다.

## 5. 재현성 기록

각 계획은 다음 항목을 함께 저장한다.

- Baseline 선택, AI 추천, 최종 선택 candidate key
- selection mode, active ranker, model version, model artifact hash
- 후보별 baseline score, predicted reward, confidence, Feature 기여도
- fallback 사용 여부와 fallback reason
- 입력 Snapshot hash, policy/strategy/Feature schema version
- 독립 `PartitionPlanValidator` 결과
- Runtime 이후 observed reward와 Dataset inclusion 여부

Dataset Builder, Trainer, Evaluator, Model Registry는 Orchestrator를 지원하는 오프라인
연구 구성요소다. 후보 생성과 Hard Constraint 판정은 계속 결정론적 코어가 담당한다.

