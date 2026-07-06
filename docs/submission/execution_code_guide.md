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
