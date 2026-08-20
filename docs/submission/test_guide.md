# 시험 가이드

이 문서는 현재 연구 본체를 검증하기 위한 시험 항목을 정리합니다.

## 1. 단위 테스트

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pytest
```

검증 내용:

- 4-Agent 판단 로직
- Action/Reward 정책
- Validator 안전 검증
- Executor mock/dry-run/real 명령 생성
- Autonomous mock/test loop
- Recovery action runner
- 정량 분석 로직

## 2. Go Guard 테스트

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
cd ~/geonhae/aiops_research
```

검증 내용:

- Go 기반 최종 action 검증
- namespace/deployment allowlist
- replica limit
- 위험 명령 차단

## 3. Mock 실행 시험

```bash
aiops-k8s-agents run \
  --mode mock \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

성공 기준:

- `"valid": true`
- 실제 Kubernetes resource 변경 없음
- `metadata`에 4-Agent decision, action, reward가 포함됨

## 4. Autonomous mock 시험

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

성공 기준:

- `"valid": true`
- `"metadata.autonomous": "closed_loop"`
- FakeEvidenceProvider 기반 evidence summary 출력

주의:

```text
Autonomous evidence flow는 mock/test 환경에서 FakeEvidenceProvider 기반으로 구현되어 있다.
KubernetesEvidenceProvider는 deployment/pod snapshot 중심의 제한적 provider다.
Prometheus metric, log enrichment, full real-cluster evidence fusion은 후속 확장이다.
```

## 5. 웹 영속 Job 시험

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
export PORT=18080
aiops-control-plane
```

브라우저에서 `Mock`, `CPU Stress`, `1회`를 선택하고 `실험 실행`을 누릅니다.

성공 기준:

- 실험 ID가 `exp-...` 형식으로 표시됨
- 7단계 타임라인과 이벤트 수가 실시간 갱신됨
- 완료 후 Agent 판단, 최종 Action, Recovery와 Reward가 표시됨
- 새로고침 후 동일 Job과 저장 이벤트가 복원됨
- `runs/control-plane/experiment-jobs.sqlite3`가 생성됨

자동화된 웹/API 계약 시험:

```bash
python -m pytest \
  tests/test_experiment_jobs.py \
  tests/test_experiment_job_runner.py \
  tests/test_control_plane_web.py \
  tests/test_control_plane_ui.py
```

취소 시험은 실행 중 `취소`를 한 번 누르고, 최종 상태가 `cancelled` 또는 안전한
terminal 상태인지 확인합니다. 서버 재시작 시험에서는 진행 중 Job이 자동 재실행되지
않고 `interrupted`로 기록되는지 확인합니다.

## 6. Prometheus 연결 시험

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

성공 기준:

- `Prometheus Server is Ready.`
- Prometheus query response에 `"status":"success"` 포함

## 7. Real recovery action 36회 시험

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

성공 기준:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
wc -l "$LATEST/outcomes.jsonl"
```

정상 기준:

```text
36 .../outcomes.jsonl
```

실패 항목 확인:

```bash
python - "$LATEST/outcomes.jsonl" <<'PY'
import json, sys

for line in open(sys.argv[1], encoding="utf-8"):
    row = json.loads(line)
    if not row.get("measurement_valid"):
        print(row.get("treatment_id"), row.get("error"))
PY
```

## 8. 정량 분석 시험

```bash
bash scripts/server_recovery_statistics.sh
```

성공 기준:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
ls "$LATEST/statistics"
cat "$LATEST/statistics/quantitative_summary.md"
```

다음 파일이 생성되어야 합니다.

- `quantitative_summary.md`
- `quantitative_summary.json`
- `scenario_action_statistics.csv`
- `policy_reward_statistics.csv`
- `mean_recovery_seconds_by_action.png`
- `success_rate_by_action.png`
- `reward_by_policy.png`

## 9. AIOpsLab benchmark 시험

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab

bash scripts/server_aiopslab_auto_detection.sh
```

반복 시험:

```bash
bash scripts/server_aiopslab_repeat_detection.sh
bash scripts/server_aiopslab_summarize_runs.sh
```

## 10. Model Partition Orchestrator V2 시험

Model Partition 결과는 Scheduling 또는 AI runtime 실행 결과가 아닙니다. 기본 evaluator는
predicted evidence와 reward를 기록하며, observed 표기는 source와 timestamp가 모두 있는
관측 evidence가 제공된 경우에만 허용됩니다. `scheduler_ref: null`은 external Scheduler가
연결되지 않았다는 뜻입니다.

### 실험 matrix

| 실험 | 입력/명령 | 확인 기준 |
| --- | --- | --- |
| Deterministic repeatability | 같은 V2 input과 policy로 두 번 계획 | candidate 순서, 선택, deterministic signature가 동일 |
| Strategy comparison | `model_partition_inference_v2.json`, `model_partition_training_v2.json` | type별 strategy, objective, graph/communication rule과 예측 metric이 구분됨 |
| Infeasible rejection | memory/network/SLA 제약을 위반한 V2 input | hard-rejection reason이 남고 infeasible candidate는 선택되지 않음 |
| Forecast comparison | forecast 포함/제거 V2 input | warnings와 confidence가 advisory forecast 상태를 반영 |
| Scheduling feedback replan | persisted V2 plan + `model_partition_failure.json` 기반 feedback | child plan의 version 증가, parent link, bounded exclusion |
| Exhaustion to human review | policy max replan 횟수 이후 feedback | `replan_attempts_exhausted`와 `human_review_required=true` |

집중 contract suite:

```bash
python -m pytest \
  tests/test_partition_coordination.py \
  tests/test_partition_context.py \
  tests/test_partition_strategies.py \
  tests/test_partition_feedback.py \
  tests/test_partition_repository.py \
  tests/test_partition_service.py \
  tests/test_partition_validator.py \
  tests/test_partition_evaluator.py \
  tests/test_model_partition_cli.py \
  tests/test_model_partition_api.py \
  tests/test_control_plane_ui.py -q
```

### CLI deterministic 재현

다음은 committed inference input으로 artifact를 두 번 생성합니다. ID와 timestamp를
제외한 deterministic signature, selected candidate, strategy/policy version을 비교합니다.

```bash
python -m pip install -e .

mkdir -p runs/model-partition-repeat-one runs/model-partition-repeat-two

for RUN in one two; do
  aiops-k8s-agents plan-model-partition-v2 \
    --input config/examples/model_partition_inference_v2.json \
    --policy config/model_partition_policy.json \
    --artifact-root "runs/model-partition-repeat-$RUN" \
    > "runs/model-partition-repeat-$RUN/report.json"
done

python - <<'PY'
import json

first = json.load(open("runs/model-partition-repeat-one/report.json", encoding="utf-8"))["plan"]
second = json.load(open("runs/model-partition-repeat-two/report.json", encoding="utf-8"))["plan"]
for key in ("deterministic_signature", "strategy_version"):
    assert first[key] == second[key], key
assert first["selected_candidate"] == second["selected_candidate"]
print("deterministic partition plan verified")
PY
```

### Web workspace QA

Control Plane을 disposable port에서 실행하고 `#orchestration`을 확인합니다.

```bash
export PORT=18183
export AIOPS_BIND_ADDRESS=127.0.0.1
export PYTHONPATH="$PWD/src"
python -m aiops_k8s_agents.control_plane_web
```

Desktop와 390px mobile viewport에서 다음을 확인합니다.

1. Initial Intake는 비어 있고 `Inference 샘플` 또는 `Training 샘플` 뒤에만 계획 생성이 활성화된다.
2. Candidate Analysis는 valid/rejected, predicted metric, memory, communication, score, graph를 겹침 없이 표시한다.
3. Handoff & Feedback은 validator, predicted reward/confidence, Snapshot hash, version history와
   `External Scheduling Agent 없음`을 함께 표시한다.
4. `실행 전 예측`과 `실제 Runtime 결과가 아닙니다`가 보이며 GPU/runtime/scheduler 실행을 주장하지 않는다.
