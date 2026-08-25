#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export ORCHESTRATOR_BIND_ADDRESS="${ORCHESTRATOR_BIND_ADDRESS:-127.0.0.1}"
export PORT="${PORT:-18200}"

python -m orchestrator_agent.web

