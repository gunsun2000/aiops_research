#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

MONITORING_NS="${MONITORING_NS:-monitoring-full}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-kube-prometheus-stack-prometheus}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9091}"
APP_NS="${APP_NS:-online-boutique}"
SCENARIO="${SCENARIO:-cpu-stress}"
ITERATIONS="${ITERATIONS:-3}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
MODE="${MODE:-dry-run}"
RUN_DIR="${RUN_DIR:-runs/full-stack}"

case "$SCENARIO" in
  cpu-stress)
    SERVICE="${SERVICE:-paymentservice}"
    METRIC="${METRIC:-cpu}"
    THRESHOLD="${THRESHOLD:-0.5}"
    QUERY="${QUERY:-sum(rate(container_cpu_usage_seconds_total{namespace=\"online-boutique\",pod=~\"paymentservice-.*\",container!=\"\",image!=\"\"}[2m])) * 100}"
    ;;
  memory-stress)
    SERVICE="${SERVICE:-checkoutservice}"
    METRIC="${METRIC:-memory}"
    THRESHOLD="${THRESHOLD:-128}"
    QUERY="${QUERY:-sum(container_memory_working_set_bytes{namespace=\"online-boutique\",pod=~\"checkoutservice-.*\",container!=\"\",image!=\"\"}) / 1024 / 1024}"
    ;;
  pod-kill)
    SERVICE="${SERVICE:-paymentservice}"
    METRIC="${METRIC:-availability}"
    THRESHOLD="${THRESHOLD:-2}"
    QUERY="${QUERY:-kube_deployment_status_replicas_available{namespace=\"online-boutique\",deployment=\"paymentservice\"}}"
    ;;
  network-delay)
    SERVICE="${SERVICE:-paymentservice}"
    METRIC="${METRIC:-latency}"
    THRESHOLD="${THRESHOLD:-0.5}"
    QUERY="${QUERY:-up}"
    ;;
  *)
    echo "Unsupported scenario: ${SCENARIO}" >&2
    exit 2
    ;;
esac

mkdir -p "$RUN_DIR"

kubectl port-forward \
  -n "$MONITORING_NS" \
  "service/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_PORT}:9090" \
  > "/tmp/geonhae-full-prometheus-${PROMETHEUS_PORT}.log" 2>&1 &
PORT_FORWARD_PID=$!

cleanup() {
  kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 5

ALLOWED_DEPLOYMENTS=(
  adservice
  cartservice
  checkoutservice
  currencyservice
  emailservice
  frontend
  loadgenerator
  paymentservice
  productcatalogservice
  recommendationservice
  redis-cart
  shippingservice
)

ALLOWED_ARGS=()
for deployment in "${ALLOWED_DEPLOYMENTS[@]}"; do
  ALLOWED_ARGS+=(--allowed-deployment "$deployment")
done

AUTOGEN_FLAGS=()
if [[ "${USE_AUTOGEN:-0}" == "1" ]]; then
  AUTOGEN_FLAGS+=(--autogen --show-transcript)
fi

echo "== Full-stack feedback loop =="
echo "scenario=${SCENARIO}"
echo "metric=${METRIC}"
echo "service=${SERVICE}"
echo "query=${QUERY}"
echo "threshold=${THRESHOLD}"

aiops-k8s-agents feedback-loop \
  --mode "$MODE" \
  --prometheus-url "http://127.0.0.1:${PROMETHEUS_PORT}" \
  --query "$QUERY" \
  --metric "$METRIC" \
  --threshold "$THRESHOLD" \
  --default-namespace "$APP_NS" \
  --default-service "$SERVICE" \
  --allowed-namespace "$APP_NS" \
  "${ALLOWED_ARGS[@]}" \
  --iterations "$ITERATIONS" \
  --interval-seconds "$INTERVAL_SECONDS" \
  --save-result-dir "$RUN_DIR" \
  "${AUTOGEN_FLAGS[@]}"
