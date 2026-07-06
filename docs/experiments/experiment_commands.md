# Experiment Commands

이 문서는 현재 연구 본체에서 유효한 실험 명령만 정리합니다.

## 1. 서버 기본 준비

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

kubectl config current-context
kubectl get nodes
kubectl get pods -n online-boutique
kubectl get pods -n monitoring-full
```

## 2. 코드 검증

```bash
python -m pytest
```

```bash
cd go/aiops-guard
go test ./...
cd ~/geonhae/aiops_research
```

## 3. Agent Registry

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

## 4. Mock smoke test

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

## 5. Autonomous mock test

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

## 6. Prometheus port-forward

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

network-delay metric:

```bash
curl -sSG "$PROM/api/v1/query" \
  --data-urlencode 'query=max(probe_duration_seconds{target="paymentservice"})'

export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
```

## 7. Recovery action pilot

12회 파일럿:

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=1 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

36회 본 실험:

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

결과 확인:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

echo "$LATEST"
wc -l "$LATEST/outcomes.jsonl"
cat "$LATEST/analysis/reward_policy_comparison.md"
```

실패 항목:

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

## 8. Quantitative statistics

```bash
bash scripts/server_recovery_statistics.sh
```

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

ls "$LATEST/statistics"
cat "$LATEST/statistics/quantitative_summary.md"
```

## 9. Final full-stack summary

```bash
CONFIRM_REAL_RUN=YES \
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
bash scripts/server_finalize_research.sh
```

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
