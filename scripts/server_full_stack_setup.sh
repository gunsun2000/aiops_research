#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

MONITORING_NS="${MONITORING_NS:-monitoring-full}"
APP_NS="${APP_NS:-online-boutique}"
ONLINE_BOUTIQUE_MANIFEST="${ONLINE_BOUTIQUE_MANIFEST:-https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml}"

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
kubectl create namespace "$APP_NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n "$APP_NS" -f "$ONLINE_BOUTIQUE_MANIFEST"

echo
echo "== Wait for core Online Boutique deployments =="
for deployment in frontend checkoutservice paymentservice cartservice productcatalogservice recommendationservice shippingservice currencyservice emailservice adservice; do
  kubectl rollout status "deployment/${deployment}" -n "$APP_NS" --timeout=300s
done

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
