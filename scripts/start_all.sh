#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/start_backend.sh" &
BPID=$!
"$ROOT/scripts/start_frontend.sh" &
FPID=$!
trap 'kill $BPID $FPID 2>/dev/null || true' INT TERM
echo "Backend PID=$BPID  Frontend PID=$FPID"
wait
