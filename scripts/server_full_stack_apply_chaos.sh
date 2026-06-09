#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

SCENARIO="${1:-${SCENARIO:-pod-kill}}"
ACTION="${ACTION:-apply}"
WAIT_SECONDS="${WAIT_SECONDS:-10}"

case "$SCENARIO" in
  pod-kill)
    MANIFEST="k8s/paymentservice-pod-kill.yaml"
    TARGET_DEPLOYMENT="paymentservice"
    ;;
  cpu-stress)
    MANIFEST="k8s/chaos/paymentservice-cpu-stress.yaml"
    TARGET_DEPLOYMENT="paymentservice"
    ;;
  memory-stress)
    MANIFEST="k8s/chaos/checkoutservice-memory-stress.yaml"
    TARGET_DEPLOYMENT="checkoutservice"
    ;;
  network-delay)
    MANIFEST="k8s/chaos/paymentservice-network-delay.yaml"
    TARGET_DEPLOYMENT="paymentservice"
    ;;
  *)
    echo "Unsupported scenario: ${SCENARIO}" >&2
    echo "Use one of: pod-kill, cpu-stress, memory-stress, network-delay" >&2
    exit 2
    ;;
esac

echo "== Scenario: ${SCENARIO} =="
echo "Manifest: ${MANIFEST}"
echo "Action: ${ACTION}"

if [[ "$ACTION" == "delete" ]]; then
  kubectl delete -f "$MANIFEST" --ignore-not-found
  exit 0
fi

kubectl get deployment "$TARGET_DEPLOYMENT" -n online-boutique
kubectl apply -f "$MANIFEST"
sleep "$WAIT_SECONDS"
kubectl get pods -n online-boutique -l "app=${TARGET_DEPLOYMENT}"

if [[ "${CLEANUP_AFTER:-0}" == "1" ]]; then
  kubectl delete -f "$MANIFEST" --ignore-not-found
fi
