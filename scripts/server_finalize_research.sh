#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/geonhae/aiops_research}"
cd "$PROJECT_DIR"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

if [[ "${CONFIRM_REAL_RUN:-}" != "YES" ]]; then
  echo "Real execution is locked. Re-run with CONFIRM_REAL_RUN=YES." >&2
  exit 2
fi

context="$(kubectl config current-context)"
if [[ "$context" != kind-* && "${ALLOW_NON_KIND_REAL:-0}" != "1" ]]; then
  echo "Refusing real execution on non-kind context: $context" >&2
  echo "Use the private kind cluster or explicitly set ALLOW_NON_KIND_REAL=1." >&2
  exit 2
fi

RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="${RUN_DIR:-runs/final-real/$RUN_ID}"
ITERATIONS="${ITERATIONS:-3}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"

mkdir -p "$RUN_DIR"

cleanup() {
  SCENARIO=all bash scripts/server_full_stack_reset.sh || true
}
trap cleanup EXIT

echo "== Final real experiment =="
echo "context=$context"
echo "controller=$([[ ${USE_AUTOGEN:-0} == 1 ]] && echo autogen || echo deterministic)"
echo "iterations=$ITERATIONS"
echo "run_dir=$RUN_DIR"

kubectl get nodes -o wide > "$RUN_DIR/cluster_nodes_before.txt"
kubectl get deployment paymentservice checkoutservice -n online-boutique \
  > "$RUN_DIR/deployments_before.txt"

SCENARIO=all bash scripts/server_full_stack_reset.sh

BASE_RUN_DIR="$RUN_DIR" \
ITERATIONS="$ITERATIONS" \
INTERVAL_SECONDS="$INTERVAL_SECONDS" \
MODE=real \
bash scripts/server_full_stack_experiment_matrix.sh

aiops-k8s-agents summarize-full-stack-runs \
  --runs-dir "$RUN_DIR" \
  --output-md "$RUN_DIR/final_summary.md" \
  --output-csv "$RUN_DIR/final_summary.csv"

kubectl get deployment paymentservice checkoutservice -n online-boutique \
  > "$RUN_DIR/deployments_after.txt"

cleanup
trap - EXIT

echo "Final experiment complete."
echo "Markdown: $RUN_DIR/final_summary.md"
echo "CSV: $RUN_DIR/final_summary.csv"
