#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/geonhae/aiops_research}"
cd "$PROJECT_DIR"

LATEST="${LATEST:-$(ls -dt runs/recovery-action-pilot/*/ | head -1)}"
INPUT="${INPUT:-${LATEST}outcomes.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-${LATEST}statistics}"

echo "== Recovery quantitative statistics =="
echo "input: ${INPUT}"
echo "output_dir: ${OUTPUT_DIR}"

aiops-k8s-agents summarize-recovery-statistics \
  --input "$INPUT" \
  --output-dir "$OUTPUT_DIR"

echo "Markdown: ${OUTPUT_DIR}/quantitative_summary.md"
echo "CSV: ${OUTPUT_DIR}/scenario_action_statistics.csv"
echo "SVG: ${OUTPUT_DIR}/mean_recovery_seconds_by_action.svg"
echo "PNG: ${OUTPUT_DIR}/mean_recovery_seconds_by_action.png"
echo "SVG: ${OUTPUT_DIR}/success_rate_by_action.svg"
echo "PNG: ${OUTPUT_DIR}/success_rate_by_action.png"
echo "SVG: ${OUTPUT_DIR}/reward_by_policy.svg"
echo "PNG: ${OUTPUT_DIR}/reward_by_policy.png"
