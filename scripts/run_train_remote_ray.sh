#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <ray-address> [extra train args]"
  echo "Example: $0 ray://10.0.0.12:10001 --num-workers 64 --num-gpus 1"
  exit 1
fi

RAY_ADDRESS="$1"
shift

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT_DIR/myenv/bin/python"

"$PYTHON" "$ROOT_DIR/train_impala_scratch.py" \
  --ray-address "$RAY_ADDRESS" \
  --checkpoint-dir "$ROOT_DIR/checkpoints/impala_round1_remote" \
  "$@"

