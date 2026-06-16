#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

MODE="${MODE:-real}"
GUARD_BACKEND="${GUARD_BACKEND:-go}"
REPETITIONS="${REPETITIONS:-1}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9091}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="${RUN_DIR:-runs/recovery-action-pilot/${RUN_ID}}"
OUTCOMES="${RUN_DIR}/outcomes.jsonl"
ANALYSIS_DIR="${RUN_DIR}/analysis"

if [[ -z "${NETWORK_LATENCY_QUERY:-}" ]]; then
  echo "NETWORK_LATENCY_QUERY is required for real network-delay evidence." >&2
  echo "Set it to a Prometheus p95 latency query from the deployed Online Boutique telemetry." >&2
  exit 2
fi

mkdir -p "$RUN_DIR"

echo "== Recovery action experiment =="
echo "mode: ${MODE}"
echo "guard_backend: ${GUARD_BACKEND}"
echo "repetitions: ${REPETITIONS}"
echo "matrix: 4 real faults x 3 bounded actions x ${REPETITIONS}"
echo "output: ${OUTCOMES}"

set +e
aiops-k8s-agents run-recovery-experiments \
  --config config/recovery_action_experiments.json \
  --mode "$MODE" \
  --guard-backend "$GUARD_BACKEND" \
  --repetitions "$REPETITIONS" \
  --prometheus-url "$PROMETHEUS_URL" \
  --output "$OUTCOMES"
experiment_status=$?
set -e

if [[ -s "$OUTCOMES" ]]; then
  aiops-k8s-agents score-recovery-experiments \
    --input "$OUTCOMES" \
    --output-dir "$ANALYSIS_DIR"
fi

echo "Experiment records: ${OUTCOMES}"
echo "Reward analysis: ${ANALYSIS_DIR}"
exit "$experiment_status"
