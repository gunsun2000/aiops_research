#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

SCENARIOS="${SCENARIOS:-pod-kill cpu-stress memory-stress network-delay}"
ITERATIONS="${ITERATIONS:-3}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
MODE="${MODE:-dry-run}"
BASE_RUN_DIR="${BASE_RUN_DIR:-runs/full-stack-matrix}"

mkdir -p "$BASE_RUN_DIR"

echo "== Full-stack experiment matrix =="
aiops-k8s-agents list-full-stack-experiments \
  --config config/full_stack_experiments.json \
  --save-result-dir "$BASE_RUN_DIR"

for scenario in $SCENARIOS; do
  echo
  echo "== Run scenario: ${scenario} =="
  ACTION=apply SCENARIO="$scenario" CLEANUP_AFTER=0 bash scripts/server_full_stack_apply_chaos.sh

  SCENARIO="$scenario" \
    ITERATIONS="$ITERATIONS" \
    INTERVAL_SECONDS="$INTERVAL_SECONDS" \
    MODE="$MODE" \
    RUN_DIR="${BASE_RUN_DIR}/${scenario}" \
    bash scripts/server_full_stack_feedback_loop.sh

  ACTION=delete SCENARIO="$scenario" bash scripts/server_full_stack_apply_chaos.sh
done

echo
echo "Full-stack experiment matrix complete: ${BASE_RUN_DIR}"
