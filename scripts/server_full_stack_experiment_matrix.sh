#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

SCENARIOS="${SCENARIOS:-pod-kill cpu-stress memory-stress network-delay}"
ITERATIONS="${ITERATIONS:-3}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
MODE="${MODE:-dry-run}"
BASE_RUN_DIR="${BASE_RUN_DIR:-runs/full-stack-matrix}"
ALLOW_SCENARIO_FAILURES="${ALLOW_SCENARIO_FAILURES:-0}"
RESET_BETWEEN_SCENARIOS="${RESET_BETWEEN_SCENARIOS:-1}"

mkdir -p "$BASE_RUN_DIR"
matrix_failed=0
failed_scenarios=()

echo "== Full-stack experiment matrix =="
aiops-k8s-agents list-full-stack-experiments \
  --config config/full_stack_experiments.json \
  --save-result-dir "$BASE_RUN_DIR"

for scenario in $SCENARIOS; do
  echo
  echo "== Run scenario: ${scenario} =="
  scenario_failed=0

  if [[ "$RESET_BETWEEN_SCENARIOS" == "1" ]]; then
    if ! SCENARIO="$scenario" bash scripts/server_full_stack_reset.sh; then
      echo "Scenario ${scenario} failed during pre-run reset." >&2
      scenario_failed=1
    fi
  fi

  if [[ "$scenario_failed" == "0" ]] && ! ACTION=apply SCENARIO="$scenario" CLEANUP_AFTER=0 bash scripts/server_full_stack_apply_chaos.sh; then
    echo "Scenario ${scenario} failed while applying chaos." >&2
    scenario_failed=1
  fi

  if [[ "$scenario_failed" == "0" ]]; then
    if ! SCENARIO="$scenario" \
      ITERATIONS="$ITERATIONS" \
      INTERVAL_SECONDS="$INTERVAL_SECONDS" \
      MODE="$MODE" \
      RUN_DIR="${BASE_RUN_DIR}/${scenario}" \
      bash scripts/server_full_stack_feedback_loop.sh; then
      echo "Scenario ${scenario} failed during feedback loop." >&2
      scenario_failed=1
    fi
  fi

  if ! ACTION=delete SCENARIO="$scenario" bash scripts/server_full_stack_apply_chaos.sh; then
    echo "Scenario ${scenario} cleanup failed." >&2
    scenario_failed=1
  fi

  if [[ "$RESET_BETWEEN_SCENARIOS" == "1" ]]; then
    if ! SCENARIO="$scenario" bash scripts/server_full_stack_reset.sh; then
      echo "Scenario ${scenario} failed during post-run reset." >&2
      scenario_failed=1
    fi
  fi

  if [[ "$scenario_failed" == "1" ]]; then
    matrix_failed=1
    failed_scenarios+=("$scenario")
  fi
done

echo
if [[ "$matrix_failed" == "1" ]]; then
  echo "Full-stack experiment matrix completed with failed scenarios: ${failed_scenarios[*]}" >&2
  if [[ "$ALLOW_SCENARIO_FAILURES" != "1" ]]; then
    exit 1
  fi
fi

echo "Full-stack experiment matrix complete: ${BASE_RUN_DIR}"
