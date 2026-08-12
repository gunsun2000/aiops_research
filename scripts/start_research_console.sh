#!/usr/bin/env bash
set -euo pipefail

# Start the research Control Plane after checking the external Ubuntu runtime.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v kubectl >/dev/null || {
  echo "error: kubectl is required" >&2
  exit 1
}
command -v aiops-control-plane >/dev/null || {
  echo "error: install this repository in the active Python environment first" >&2
  exit 1
}

if [[ -z "${KUBECONFIG:-}" ]]; then
  if [[ -f "$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml" ]]; then
    KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
  else
    KUBECONFIG="$HOME/.kube/config"
  fi
fi

AIOPSLAB_ROOT="${AIOPSLAB_ROOT:-}"
if [[ -z "$AIOPSLAB_ROOT" ]]; then
  for candidate in \
    "$ROOT/../external/AIOpsLab" \
    "$HOME/geonhae/external/AIOpsLab"; do
    if [[ -d "$candidate" ]]; then
      AIOPSLAB_ROOT="$candidate"
      break
    fi
  done
fi

AIOPSLAB_PYTHON="${AIOPSLAB_PYTHON:-}"
if [[ -z "$AIOPSLAB_PYTHON" ]]; then
  if [[ -x "$HOME/anaconda3/envs/aiopslab/bin/python" ]]; then
    AIOPSLAB_PYTHON="$HOME/anaconda3/envs/aiopslab/bin/python"
  else
    AIOPSLAB_PYTHON=""
  fi
fi

export KUBECONFIG
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9091}"
export AIOPS_AUTO_PORT_FORWARD="${AIOPS_AUTO_PORT_FORWARD:-auto}"
export AIOPSLAB_ROOT
export AIOPSLAB_PYTHON
export AIOPS_BIND_ADDRESS="${AIOPS_BIND_ADDRESS:-127.0.0.1}"
export PORT="${PORT:-18180}"

echo "== AIOps research runtime preflight =="
echo "repository: $ROOT"
echo "kubeconfig: $KUBECONFIG"
echo "control plane: http://${AIOPS_BIND_ADDRESS}:${PORT}"

kubectl config current-context
kubectl get nodes --no-headers
kubectl get namespace online-boutique monitoring-full >/dev/null
kubectl api-resources --api-group=chaos-mesh.org --no-headers | grep -q . || {
  echo "error: Chaos Mesh API resources were not found" >&2
  exit 1
}

if [[ -z "$AIOPSLAB_ROOT" || ! -d "$AIOPSLAB_ROOT" ]]; then
  echo "error: AIOPSLAB_ROOT must point to an external AIOpsLab checkout" >&2
  exit 1
fi
if [[ -z "$AIOPSLAB_PYTHON" || ! -x "$AIOPSLAB_PYTHON" ]]; then
  echo "error: AIOPSLAB_PYTHON must point to the AIOpsLab Python interpreter" >&2
  exit 1
fi
"$AIOPSLAB_PYTHON" -c 'import aiopslab, rich; print("AIOpsLab runtime: ready")'

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "AutoGen: credentials configured"
else
  echo "AutoGen: API key not configured (optional; deterministic mode remains available)"
fi

echo "Starting Control Plane. Prometheus port-forward will be managed automatically."
exec aiops-control-plane
