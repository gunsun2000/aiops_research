#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/geonhae/aiops_research}"
AIOPSLAB_ROOT="${AIOPSLAB_ROOT:-$HOME/geonhae/external/AIOpsLab}"
KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"
PROBLEM_ID="${PROBLEM_ID:-misconfig_app_hotel_res-detection-1}"
NAMESPACE="${NAMESPACE:-test-hotel-reservation}"
SERVICE="${SERVICE:-geo}"
METRICS_DURATION_MINUTES="${METRICS_DURATION_MINUTES:-10}"
MAX_STEPS="${MAX_STEPS:-8}"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG

cd "$PROJECT_DIR"

python scripts/server_aiopslab_auto_detection.py \
  --aiopslab-root "$AIOPSLAB_ROOT" \
  --problem-id "$PROBLEM_ID" \
  --namespace "$NAMESPACE" \
  --service "$SERVICE" \
  --metrics-duration-minutes "$METRICS_DURATION_MINUTES" \
  --max-steps "$MAX_STEPS" \
  --kubeconfig "$KUBECONFIG" \
  --save-result-dir runs
