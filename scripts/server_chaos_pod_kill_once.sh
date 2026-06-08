#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

echo "== Before chaos =="
kubectl get deployment paymentservice -n online-boutique
kubectl get pods -n online-boutique -l app=paymentservice

echo
echo "== Inject PodChaos =="
kubectl apply -f k8s/paymentservice-pod-kill.yaml

echo
echo "== After chaos injection =="
sleep 5
kubectl get pods -n online-boutique -l app=paymentservice

echo
echo "== Wait for rollout recovery =="
kubectl rollout status deployment/paymentservice -n online-boutique --timeout=120s
kubectl get deployment paymentservice -n online-boutique

echo
echo "== Cleanup PodChaos =="
kubectl delete -f k8s/paymentservice-pod-kill.yaml
