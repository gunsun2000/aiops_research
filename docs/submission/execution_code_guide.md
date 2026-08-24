# 실행 코드 가이드

이 문서는 현재 연구 본체에서 사용하는 주요 실행 명령어만 정리합니다.

## 1. 기본 준비

서버:

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
```

로컬 Windows:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
```

## 2. 테스트

Python 테스트:

```bash
python -m pytest
```

Go Guard 테스트:

```bash
cd go/aiops-guard
go test ./...
cd ~/geonhae/aiops_research
```

## 3. Agent Registry 확인

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json
```

```bash
aiops-k8s-agents validate-agent-action \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent \
  --action app_scale_deployment
```

## 4. 단일 mock 실행

```bash
aiops-k8s-agents run \
  --mode mock \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is high" \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

의미:

- 4-Agent 판단 흐름을 빠르게 확인한다.
- 실제 Kubernetes resource는 변경하지 않는다.
- 초기 smoke test 용도다.

## 5. Autonomous mock 실행

```bash
aiops-k8s-agents autonomous-run \
  --mode mock \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

의미:

- FakeEvidenceProvider 기반 autonomous loop를 확인한다.
- mock/test 환경용 autonomous evidence flow다.
- Prometheus metric, log enrichment, full real-cluster evidence fusion은 후속 확장이다.

## 6. Prometheus 연결

터미널 A:

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

터미널 B:

```bash
export PROM=http://127.0.0.1:9091
curl -sS "$PROM/-/ready"
curl -sSG "$PROM/api/v1/query" --data-urlencode 'query=up'
```

network-delay 실험에 사용할 latency query:

```bash
curl -sSG "$PROM/api/v1/query" \
  --data-urlencode 'query=max(probe_duration_seconds{target="paymentservice"})'

export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
```

## 7. Recovery action 36회 real 실험

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

실험 구성:

```text
4개 장애 x 3개 action x 3회 = 36회

장애: pod-kill, cpu-stress, memory-stress, network-delay
Action: observe_only, rollout_restart, scale_out
```

결과 확인:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

echo "$LATEST"
wc -l "$LATEST/outcomes.jsonl"
cat "$LATEST/analysis/reward_policy_comparison.md"
```

실패 항목 확인:

```bash
python - "$LATEST/outcomes.jsonl" <<'PY'
import json, sys

for line in open(sys.argv[1], encoding="utf-8"):
    row = json.loads(line)
    if not row.get("measurement_valid"):
        print("treatment:", row.get("treatment_id"))
        print("scenario:", row.get("scenario"))
        print("error:", row.get("error"))
        print()
PY
```

## 8. 정량 통계와 그래프 생성

```bash
bash scripts/server_recovery_statistics.sh
```

결과 확인:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

ls "$LATEST/statistics"
cat "$LATEST/statistics/quantitative_summary.md"
```

생성되는 대표 파일:

- `quantitative_summary.md`
- `quantitative_summary.json`
- `scenario_action_statistics.csv`
- `policy_reward_statistics.csv`
- `mean_recovery_seconds_by_action.png`
- `success_rate_by_action.png`
- `reward_by_policy.png`

## 9. 전체 AIOps 실험 요약

```bash
CONFIRM_REAL_RUN=YES \
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
bash scripts/server_finalize_research.sh
```

결과 요약 생성:

```bash
LATEST_FINAL=$(ls -dt runs/final-real/*/ | head -1)

aiops-k8s-agents summarize-full-stack-runs \
  --runs-dir "$LATEST_FINAL" \
  --output-md "$LATEST_FINAL/final_summary.md" \
  --output-csv "$LATEST_FINAL/final_summary.csv"

cat "$LATEST_FINAL/final_summary.md"
cat "$LATEST_FINAL/final_summary.csv"
```

## 10. AIOpsLab benchmark

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab

bash scripts/server_aiopslab_auto_detection.sh
```

반복 실행:

```bash
bash scripts/server_aiopslab_repeat_detection.sh
bash scripts/server_aiopslab_summarize_runs.sh
```

## 11. Model Partition Orchestrator V2

Model Partition Orchestrator는 승인된 Coordination Plan과 읽기 전용 Snapshot에서
후보 분할을 **계획·검증·평가**합니다. `Scheduling Handoff`는 외부 Scheduling Agent가
소비할 versioned contract와 artifact를 준비할 뿐입니다. Queue/placement, GPU 할당,
학습·추론 runtime은 실행하지 않습니다. observed evidence의 source와 timestamp가 없으면
reward와 성능 값은 모두 predicted입니다.

현재 checkout의 V2 CLI를 사용하려면 먼저 editable install을 수행합니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e .

PARTITION_ROOT=runs/model-partition-docs
mkdir -p "$PARTITION_ROOT"
```

### V2 inference와 training 계획

다음 committed input은 각각 승인된 Inference와 Training Coordination Plan입니다.

```bash
aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_inference_v2.json \
  --policy config/model_partition_policy.json \
  --artifact-root "$PARTITION_ROOT" \
  > "$PARTITION_ROOT/inference-v1.json"

aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --policy config/model_partition_policy.json \
  --artifact-root "$PARTITION_ROOT" \
  > "$PARTITION_ROOT/training-v1.json"
```

각 report에는 candidate, independent validation, `plan_version`, Snapshot hash,
`scheduling_handoff`가 포함됩니다. `scheduler_ref: null`은 외부 Scheduler가 아직
연결되지 않았음을 뜻하며 Scheduling 성공을 의미하지 않습니다.

### Federated Coordination Agent schema 0.4 입력

FL, SL, PARTITIONED 계획은 participant/model context와 결합한 뒤 같은 planning core로
처리합니다. 예제 context는 실제 Prometheus 측정값이 아닌 계약 재현용입니다.

```bash
export AIOPS_FEDERATED_CONTEXT_PATH="$PWD/config/examples/federated_coordination_context_v04.json"
bash scripts/start_research_console.sh restart

for plan in fl sl inference; do
  curl -sS -X POST http://127.0.0.1:18180/api/model-partition/coordination-plan \
    -H 'Content-Type: application/json' \
    --data-binary "@config/examples/federated_coordination_${plan}_v04.json" \
    > "$PARTITION_ROOT/federated-${plan}-v04.json"
done
```

실제 환경에서는 upstream participant selector가 Prometheus에서 생성한 versioned
snapshot과 Model Registry snapshot을 한 파일로 materialize하고 해당 경로를
`AIOPS_FEDERATED_CONTEXT_PATH`에 지정합니다. SL/PARTITIONED에 network link가 없으면
`context_enrichment.status=blocked`가 정상적인 안전 동작입니다.

### Reward Ranker Dataset, 학습, 평가

학습 기능을 사용할 때만 ML extra를 설치합니다. HMAC 키는 저장소 밖의 파일로 관리하고
실제 키 내용을 명령 출력, 문서, 브라우저 또는 Git에 노출하지 않습니다.

```bash
python -m pip install -e ".[ml]"

export PARTITION_ARTIFACT_ROOT="$PWD/runs/model-partition"
export PARTITION_DATASET="$PWD/runs/model-partition-learning/observed-dataset.jsonl"
export PARTITION_RANKER_REGISTRY="$PWD/runs/model-partition-rankers"
export PARTITION_SIGNING_KEY_FILE="$HOME/.config/aiops/partition-artifact.hmac"
```

서명된 observed Runtime outcome에서 Dataset을 만들고 Ridge Ranker를 학습·평가합니다.
predicted, synthetic, mock, dry-run 결과는 기본 Real Dataset에 포함하지 않습니다.

```bash
aiops-k8s-agents build-partition-ranking-dataset \
  --artifact-root "$PARTITION_ARTIFACT_ROOT" \
  --output "$PARTITION_DATASET" \
  --scope observed \
  --artifact-signing-key-file "$PARTITION_SIGNING_KEY_FILE"

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

먼저 Shadow로 AI 추천만 기록하고 Baseline 선택을 유지합니다. 평가 결과가
`guarded_eligible=true`일 때만 Learned Guarded 비교를 수행합니다.

```bash
aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --selection-mode shadow \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --ranker-model-version partition-ridge-observed-v1 \
  --artifact-root "$PARTITION_ARTIFACT_ROOT"

aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --selection-mode learned_guarded \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --ranker-model-version partition-ridge-observed-v1 \
  --artifact-root "$PARTITION_ARTIFACT_ROOT"
```

두 결과에서 Baseline 선택, AI 추천, 최종 선택, predicted reward, model version/hash,
Guard 상태와 fallback reason을 비교합니다. Runtime 이후 observed Evaluator reward는
별도 evidence이며 predicted reward와 같은 값으로 해석하지 않습니다.

### Bounded feedback 재계획

feedback은 persisted plan의 ID/version을 참조해야 합니다. 아래는 committed failure
example을 source/reason/timestamp가 있는 feedback envelope로 만들고 child plan을 생성합니다.

```bash
PLAN_ID=$(python -c 'import json; print(json.load(open("runs/model-partition-docs/inference-v1.json"))["plan"]["plan_id"])')

python - "$PLAN_ID" <<'PY' > "$PARTITION_ROOT/feedback.json"
import json
import sys

feedback = json.load(open("config/examples/model_partition_failure.json", encoding="utf-8"))
feedback.update({
    "source": "runtime-monitor",
    "reason": feedback.pop("details"),
    "received_at": "2026-08-20T00:00:00+00:00",
    "plan_id": sys.argv[1],
    "plan_version": 1,
})
print(json.dumps(feedback))
PY

aiops-k8s-agents feedback-model-partition \
  --plan-id "$PLAN_ID" \
  --feedback "$PARTITION_ROOT/feedback.json" \
  --policy config/model_partition_policy.json \
  --artifact-root "$PARTITION_ROOT"
```

이 재계획은 feedback과 충돌하는 후보/자원만 제외하고, policy의 최대 시도 횟수를
넘기면 `human_review_required=true`로 안전하게 종료합니다. 자동으로 participant를
늘리거나 hard constraint를 완화하지 않습니다.

### Legacy compatibility

기존 FederatedRoundPlan 계약은 그대로 유지됩니다. 두 command 모두 committed example을
사용하며 planning 외 infrastructure 변경을 하지 않습니다.

```bash
aiops-k8s-agents plan-model-partition \
  --input config/examples/model_partition_job.json \
  --policy config/model_partition_policy.json \
  --artifact-root "$PARTITION_ROOT" \
  > "$PARTITION_ROOT/legacy-v1.json"

python - <<'PY'
import json

report = json.load(open("runs/model-partition-docs/legacy-v1.json", encoding="utf-8"))
with open("runs/model-partition-docs/legacy-plan.json", "w", encoding="utf-8") as handle:
    json.dump(report["plan"], handle)
PY

aiops-k8s-agents replan-model-partition \
  --input config/examples/model_partition_job.json \
  --previous-plan "$PARTITION_ROOT/legacy-plan.json" \
  --failure config/examples/model_partition_failure.json \
  --policy config/model_partition_policy.json \
  --artifact-root "$PARTITION_ROOT"
```

### Control Plane API: plan, history, feedback

터미널 A에서 disposable local port로 Control Plane을 실행합니다. 운영 중인 기존
Control Plane 포트는 재사용하거나 종료하지 않습니다.

```bash
export PORT=18183
export AIOPS_BIND_ADDRESS=127.0.0.1
export PYTHONPATH="$PWD/src"
python -m aiops_k8s_agents.control_plane_web
```

터미널 B에서 committed V2 input을 API request envelope로 전송합니다.

```bash
BASE=http://127.0.0.1:18183

curl -sS "$BASE/api/model-partition/examples" | python -m json.tool

PLAN_ID=$(python -c 'import json; print(json.dumps({"request": json.load(open("config/examples/model_partition_inference_v2.json"))}))' \
  | curl -sS -X POST "$BASE/api/model-partition/plans" \
      -H 'Content-Type: application/json' --data-binary @- \
  | tee "$PARTITION_ROOT/api-inference-v1.json" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["plan"]["plan_id"])')

curl -sS "$BASE/api/model-partition/plans/$PLAN_ID/history" | python -m json.tool
```

Feedback uses the same committed failure example and the runtime-generated plan ID.

```bash
python - "$PLAN_ID" <<'PY' \
  | curl -sS -X POST "$BASE/api/model-partition/plans/$PLAN_ID/feedback" \
      -H 'Content-Type: application/json' --data-binary @- \
  | python -m json.tool
import json
import sys

feedback = json.load(open("config/examples/model_partition_failure.json", encoding="utf-8"))
feedback.update({
    "source": "runtime-monitor",
    "reason": feedback.pop("details"),
    "received_at": "2026-08-20T00:00:00+00:00",
    "plan_id": sys.argv[1],
    "plan_version": 1,
})
print(json.dumps(feedback))
PY
```
