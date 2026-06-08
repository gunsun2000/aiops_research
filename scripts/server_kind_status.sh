#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

echo "KUBECONFIG=$KUBECONFIG"
echo
echo "== Nodes =="
kubectl get nodes

echo
echo "== paymentservice deployment =="
kubectl get deployment paymentservice -n online-boutique || true

echo
echo "== paymentservice pods =="
kubectl get pods -n online-boutique -l app=paymentservice || true

echo
echo "== Prometheus =="
kubectl get pods -n monitoring || true

echo
echo "== Chaos Mesh =="
kubectl get pods -n chaos-mesh || true
