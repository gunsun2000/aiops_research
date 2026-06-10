#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

MONITORING_NS="${MONITORING_NS:-monitoring-full}"
APP_NS="${APP_NS:-online-boutique}"
ONLINE_BOUTIQUE_MANIFEST="${ONLINE_BOUTIQUE_MANIFEST:-https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml}"
RESET_ONLINE_BOUTIQUE="${RESET_ONLINE_BOUTIQUE:-0}"
ALLOW_PARTIAL_ROLLOUT="${ALLOW_PARTIAL_ROLLOUT:-0}"

echo "== Kubernetes context =="
kubectl config current-context
kubectl get nodes

echo
echo "== Install kube-prometheus-stack =="
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n "$MONITORING_NS" \
  --create-namespace \
  -f k8s/kube-prometheus-stack-values.yaml \
  --wait \
  --timeout 15m

echo
echo "== Deploy full Online Boutique =="
if [[ "$RESET_ONLINE_BOUTIQUE" == "1" ]]; then
  echo "RESET_ONLINE_BOUTIQUE=1: deleting namespace ${APP_NS} before redeploying."
  kubectl delete namespace "$APP_NS" --ignore-not-found
  kubectl wait --for=delete "namespace/${APP_NS}" --timeout=180s || true
fi
kubectl create namespace "$APP_NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n "$APP_NS" -f "$ONLINE_BOUTIQUE_MANIFEST"

echo
echo "== Wait for core Online Boutique deployments =="
rollout_failed=0
for deployment in frontend checkoutservice paymentservice cartservice productcatalogservice recommendationservice shippingservice currencyservice emailservice adservice; do
  if ! kubectl rollout status "deployment/${deployment}" -n "$APP_NS" --timeout=300s; then
    rollout_failed=1
    echo
    echo "== Rollout diagnostics: ${deployment} ==" >&2
    kubectl get deployment "$deployment" -n "$APP_NS" -o wide || true
    kubectl get pods -n "$APP_NS" -l "app=${deployment}" -o wide || true
    kubectl describe deployment "$deployment" -n "$APP_NS" || true
    kubectl logs -n "$APP_NS" -l "app=${deployment}" --all-containers --tail=80 || true
  fi
done

if [[ "$rollout_failed" == "1" ]]; then
  if [[ "$ALLOW_PARTIAL_ROLLOUT" == "1" ]]; then
    echo
    echo "One or more deployments failed, but ALLOW_PARTIAL_ROLLOUT=1 so setup continues."
  else
    echo
    echo "One or more deployments failed. Review diagnostics above." >&2
    echo "To rebuild only the experiment namespace, rerun with RESET_ONLINE_BOUTIQUE=1." >&2
    echo "To continue for debugging despite failed pods, rerun with ALLOW_PARTIAL_ROLLOUT=1." >&2
    exit 1
  fi
fi

echo
echo "== Full-stack status =="
kubectl get pods -n "$MONITORING_NS"
kubectl get pods -n "$APP_NS"

echo
echo "Full-stack setup complete."
echo "Prometheus port-forward example:"
echo "kubectl port-forward -n ${MONITORING_NS} service/kube-prometheus-stack-prometheus 9091:9090"
echo "Grafana port-forward example:"
echo "kubectl port-forward -n ${MONITORING_NS} service/kube-prometheus-stack-grafana 3000:80"
