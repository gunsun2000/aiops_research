#!/usr/bin/env bash
set -euo pipefail

LABEL="command"
INTERVAL_SECONDS="${PROGRESS_INTERVAL_SECONDS:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="${2:?--label requires a value}"
      shift 2
      ;;
    --interval-seconds)
      INTERVAL_SECONDS="${2:?--interval-seconds requires a value}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -eq 0 ]]; then
  echo "Usage: bash scripts/run_with_progress.sh --label LABEL -- command [args...]" >&2
  exit 2
fi

start_epoch="$(date +%s)"
spinner='|/-\'
"$@" &
child_pid=$!

format_elapsed() {
  local now elapsed hours minutes seconds
  now="$(date +%s)"
  elapsed=$((now - start_epoch))
  hours=$((elapsed / 3600))
  minutes=$(((elapsed % 3600) / 60))
  seconds=$((elapsed % 60))
  printf "%02d:%02d:%02d" "$hours" "$minutes" "$seconds"
}

index=0
while kill -0 "$child_pid" 2>/dev/null; do
  char="${spinner:index%${#spinner}:1}"
  printf '\r[%s] running %s elapsed %s | still working...' \
    "$LABEL" "$char" "$(format_elapsed)" >&2
  sleep "$INTERVAL_SECONDS"
  index=$((index + 1))
done

set +e
wait "$child_pid"
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  printf '\r[%s] done | elapsed %s | exit=%d                     \n' \
    "$LABEL" "$(format_elapsed)" "$status" >&2
else
  printf '\r[%s] failed | elapsed %s | exit=%d                   \n' \
    "$LABEL" "$(format_elapsed)" "$status" >&2
fi

exit "$status"
