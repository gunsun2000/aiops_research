#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/geonhae/aiops_research}"
RUNS="${RUNS:-3}"
SLEEP_SECONDS="${SLEEP_SECONDS:-15}"

cd "$PROJECT_DIR"

for run_index in $(seq 1 "$RUNS"); do
  echo "== AIOpsLab 4-agent auto-detection run ${run_index}/${RUNS} =="
  bash scripts/server_aiopslab_auto_detection.sh
  if [ "$run_index" -lt "$RUNS" ]; then
    sleep "$SLEEP_SECONDS"
  fi
done

aiops-k8s-agents summarize-aiopslab-runs \
  --runs-dir runs \
  --output-md runs/aiopslab_detection_summary.md \
  --output-csv runs/aiopslab_detection_summary.csv

echo "Markdown summary: $PROJECT_DIR/runs/aiopslab_detection_summary.md"
echo "CSV summary: $PROJECT_DIR/runs/aiopslab_detection_summary.csv"
