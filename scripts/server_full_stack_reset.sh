#!/usr/bin/env bash
set -euo pipefail

cd "${PROJECT_DIR:-$HOME/geonhae/aiops_research}"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

SCENARIO="${SCENARIO:-${1:-all}}"
APP_NS="${APP_NS:-online-boutique}"
BASE_REPLICAS="${BASE_REPLICAS:-1}"

reset_deployment() {
  local deployment="$1"
  kubectl scale deployment "$deployment" --replicas="$BASE_REPLICAS" -n "$APP_NS"
  kubectl rollout status deployment/"$deployment" -n "$APP_NS" --timeout=180s
}

cleanup_scenario() {
  ACTION=delete SCENARIO="$1" bash scripts/server_full_stack_apply_chaos.sh
}

case "$SCENARIO" in
  pod-kill|cpu-stress|network-delay)
    cleanup_scenario "$SCENARIO"
    reset_deployment paymentservice
    ;;
  memory-stress)
    cleanup_scenario "$SCENARIO"
    reset_deployment checkoutservice
    ;;
  all)
    for item in pod-kill cpu-stress memory-stress network-delay; do
      cleanup_scenario "$item"
    done
    reset_deployment paymentservice
    reset_deployment checkoutservice
    ;;
  *)
    echo "Unsupported scenario: $SCENARIO" >&2
    exit 2
    ;;
esac

kubectl get deployment paymentservice checkoutservice -n "$APP_NS"
