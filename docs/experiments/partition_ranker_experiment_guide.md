# Model Partition Reward Ranker 실험 가이드

## 1. 연구 질문

이 실험은 결정론적 Model Partition 후보군을 유지하면서 학습 Ranker가 후보 순위를
개선할 수 있는지 평가한다.

1. `shadow`에서 AI 추천이 Baseline 선택과 얼마나 자주 다른가?
2. AI 추천은 observed Evaluator reward가 높은 후보를 더 잘 선택하는가?
3. `learned_guarded`에서 Guard 통과·폴백 비율과 실제 성능 변화는 어떠한가?

Scheduling Agent는 외부 구성요소다. 본 실험의 최종 출력은
`PartitionExecutionPlan`이며 실제 Queue·placement·GPU dispatch 결과가 아니다.

## 2. 증거 범위

- Deterministic candidate generation과 Hard Feasibility Filter가 후보군을 확정한다.
- AI Ranker는 Hard Constraint를 통과한 후보만 순위화한다.
- `PartitionPlanValidator`가 최종 계획을 독립적으로 승인하거나 거부한다.
- 기본 학습 범위는 HMAC 인증된 `observed` Runtime outcome이다.
- **predicted·mock·dry-run 결과는 Real Runtime 성능 근거로 사용하지 않는다.**
- Recovery 실험, AIOpsLab Benchmark, AutoGen Controller 실험은 이 Dataset과 별도다.

## 3. 환경 준비

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[ml]"

export PARTITION_ARTIFACT_ROOT="$PWD/runs/model-partition"
export PARTITION_DATASET="$PWD/runs/model-partition-learning/observed-dataset.jsonl"
export PARTITION_RANKER_REGISTRY="$PWD/runs/model-partition-rankers"
export PARTITION_SIGNING_KEY_FILE="$HOME/.config/aiops/partition-artifact.hmac"
mkdir -p "$(dirname "$PARTITION_DATASET")" "$PARTITION_RANKER_REGISTRY" "$(dirname "$PARTITION_SIGNING_KEY_FILE")"
```

HMAC 키는 저장소 밖에서 생성하고 화면·로그·Git에 출력하지 않는다. 최초 한 번만 다음처럼
생성한다.

```bash
python - "$PARTITION_SIGNING_KEY_FILE" <<'PY'
from pathlib import Path
import secrets
import sys

path = Path(sys.argv[1]).expanduser()
if not path.exists():
    path.write_bytes(secrets.token_bytes(32))
    path.chmod(0o600)
print(f"artifact HMAC key ready: {path}")
PY
```

## 4. Observed Dataset 생성

사전에 같은 HMAC 키로 서명된 planning artifact와 외부 Runtime outcome이 있어야 한다.
Runtime outcome에는 source, timestamp, selected candidate binding, 실제 지표,
Evaluator reward가 포함되어야 한다.

```bash
aiops-k8s-agents build-partition-ranking-dataset \
  --artifact-root "$PARTITION_ARTIFACT_ROOT" \
  --output "$PARTITION_DATASET" \
  --scope observed \
  --artifact-signing-key-file "$PARTITION_SIGNING_KEY_FILE"
```

출력의 `row_count`와 `rejections`를 함께 보관한다. 행이 0개라면 mock 데이터를 넣어
우회하지 않고 인증·binding·관측 필드 오류를 먼저 수정한다.

## 5. 학습과 독립 평가

```bash
aiops-k8s-agents train-partition-ranker \
  --dataset "$PARTITION_DATASET" \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --model-version partition-ridge-observed-v1 \
  --seed 17 \
  --artifact-signing-key-file "$PARTITION_SIGNING_KEY_FILE"

aiops-k8s-agents evaluate-partition-ranker \
  --dataset "$PARTITION_DATASET" \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --model-version partition-ridge-observed-v1 \
  --artifact-signing-key-file "$PARTITION_SIGNING_KEY_FILE"
```

평가 결과에는 Dataset hash, model artifact hash, holdout MAE, Spearman correlation,
표본·독립 그룹 수, `guarded_eligible`을 기록한다.

## 6. 동일 입력 비교

### Baseline

```bash
aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --selection-mode deterministic \
  --artifact-root "$PARTITION_ARTIFACT_ROOT"
```

### Shadow

```bash
aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --selection-mode shadow \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --ranker-model-version partition-ridge-observed-v1 \
  --artifact-root "$PARTITION_ARTIFACT_ROOT"
```

Shadow 추천은 실행 후보를 변경하지 않는다. Baseline 선택과 AI 추천이 모두 기록되지만
최종 선택은 Baseline이다.

### Learned Guarded

```bash
aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --selection-mode learned_guarded \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --ranker-model-version partition-ridge-observed-v1 \
  --artifact-root "$PARTITION_ARTIFACT_ROOT"
```

Guard를 통과하지 못하면 명령은 위험한 후보를 강제하지 않고 Baseline으로 폴백하거나
명시적인 오류를 반환한다. `fallback_used`, `fallback_reason`, model version/hash를 반드시
결과와 함께 보고한다.

## 7. 비교 지표

| 지표 | 의미 |
| --- | --- |
| Baseline-AI agreement | 두 선택이 같은 비율 |
| Final-Baseline change rate | Guarded 모드가 최종 결정을 바꾼 비율 |
| Guard pass/fallback rate | 안전 경계를 통과하거나 폴백한 비율 |
| Observed reward delta | Runtime 실행 후 Baseline 대비 Evaluator reward 차이 |
| SLO / feasibility violation | AI 선택이 제약을 위반했는지 여부 |
| Dataset inclusion rate | 인증된 observed 결과가 학습 행으로 포함된 비율 |

논문 결과에서는 predicted reward 개선과 observed reward 개선을 별도 표로 제시한다.

