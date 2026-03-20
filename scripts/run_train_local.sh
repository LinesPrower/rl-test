#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT_DIR/myenv/bin/python"

"$PYTHON" "$ROOT_DIR/train_impala_scratch.py" \
  --iterations 2000 \
  --num-workers 8 \
  --num-envs-per-worker 1 \
  --train-batch-size 16000 \
  --checkpoint-every 25 \
  --checkpoint-dir "$ROOT_DIR/checkpoints/impala_round1_local" \
  "$@"

