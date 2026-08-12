#!/usr/bin/env bash
set -euo pipefail

# One-command lifecycle entrypoint for the Ubuntu research console.
AIOPS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$AIOPS_REPO_ROOT"

if [[ -d "$HOME/bin" ]]; then
  PATH="$HOME/bin:$PATH"
  export PATH
fi

ACTION="${1:-restart}"
case "$ACTION" in
  start|restart|status|stop) ;;
  *)
    echo "usage: bash scripts/start_research_console.sh [start|restart|status|stop]" >&2
    exit 2
    ;;
esac

find_research_python() {
  if [[ -n "${AIOPS_RESEARCH_PYTHON:-}" && -x "$AIOPS_RESEARCH_PYTHON" ]]; then
    printf '%s\n' "$AIOPS_RESEARCH_PYTHON"
    return 0
  fi

  local candidate
  for candidate in \
    "$HOME/anaconda3/envs/aiops_research/bin/python" \
    "$HOME/miniconda3/envs/aiops_research/bin/python" \
    "${CONDA_PREFIX:-}/bin/python"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  command -v python3 || command -v python || return 1
}

AIOPS_RESEARCH_PYTHON="$(find_research_python)" || {
  echo "error: Python 3 was not found" >&2
  exit 1
}

if ! "$AIOPS_RESEARCH_PYTHON" -c \
  'import aiops_k8s_agents.control_plane_process, fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Installing the repository UI in the selected Python environment..."
  "$AIOPS_RESEARCH_PYTHON" -m pip install -e ".[ui]"
fi

if [[ -z "${KUBECONFIG:-}" ]]; then
  if [[ -f "$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml" ]]; then
    KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
  elif [[ -f "$HOME/.kube/config" ]]; then
    KUBECONFIG="$HOME/.kube/config"
  else
    KUBECONFIG=""
  fi
fi

if [[ -z "${AIOPSLAB_ROOT:-}" ]]; then
  for candidate in \
    "$AIOPS_REPO_ROOT/../external/AIOpsLab" \
    "$HOME/geonhae/external/AIOpsLab"; do
    if [[ -d "$candidate" ]]; then
      AIOPSLAB_ROOT="$candidate"
      break
    fi
  done
fi
AIOPSLAB_ROOT="${AIOPSLAB_ROOT:-}"

if [[ -z "${AIOPSLAB_PYTHON:-}" ]]; then
  for candidate in \
    "$HOME/anaconda3/envs/aiopslab/bin/python" \
    "$HOME/miniconda3/envs/aiopslab/bin/python"; do
    if [[ -x "$candidate" ]]; then
      AIOPSLAB_PYTHON="$candidate"
      break
    fi
  done
fi
AIOPSLAB_PYTHON="${AIOPSLAB_PYTHON:-}"

export AIOPS_REPO_ROOT
export KUBECONFIG
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9091}"
export AIOPS_AUTO_PORT_FORWARD="${AIOPS_AUTO_PORT_FORWARD:-auto}"
export AIOPSLAB_ROOT
export AIOPSLAB_PYTHON
export AIOPS_BIND_ADDRESS="${AIOPS_BIND_ADDRESS:-127.0.0.1}"
export PORT="${PORT:-18180}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "warning: kubectl was not found; Mock UI will start without cluster connections" >&2
elif [[ -z "$KUBECONFIG" ]]; then
  echo "warning: kubeconfig was not found; Kubernetes connections will remain unavailable" >&2
else
  if CHAOS_RESOURCES="$(kubectl api-resources --api-group=chaos-mesh.org --no-headers)"; then
    :
  else
    CHAOS_RESOURCES=""
  fi
  if [[ -z "$CHAOS_RESOURCES" || \
        "$CHAOS_RESOURCES" != *networkchaos* || \
        "$CHAOS_RESOURCES" != *podchaos* || \
        "$CHAOS_RESOURCES" != *stresschaos* ]]; then
    echo "warning: Chaos Mesh API resources were not found; Chaos experiments will remain unavailable" >&2
  fi
fi

if [[ -z "$AIOPSLAB_ROOT" || -z "$AIOPSLAB_PYTHON" ]]; then
  echo "warning: AIOpsLab runtime was not found; its benchmark will remain unavailable" >&2
fi

if [[ -z "${OPENAI_API_KEY:-}" && -z "${OPENAI_ADMIN_KEY:-}" ]]; then
  echo "info: AutoGen API key is not configured; deterministic mode remains available"
fi

"$AIOPS_RESEARCH_PYTHON" -m aiops_k8s_agents.control_plane_process "$ACTION"
