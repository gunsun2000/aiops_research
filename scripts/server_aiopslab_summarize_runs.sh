#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/geonhae/aiops_research}"
RUNS_DIR="${RUNS_DIR:-runs}"

cd "$PROJECT_DIR"

aiops-k8s-agents summarize-aiopslab-runs \
  --runs-dir "$RUNS_DIR" \
  --output-md "$RUNS_DIR/aiopslab_detection_summary.md" \
  --output-csv "$RUNS_DIR/aiopslab_detection_summary.csv"

echo "Markdown summary: $PROJECT_DIR/$RUNS_DIR/aiopslab_detection_summary.md"
echo "CSV summary: $PROJECT_DIR/$RUNS_DIR/aiopslab_detection_summary.csv"
