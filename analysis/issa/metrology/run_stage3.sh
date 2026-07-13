#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DATA_ROOT="${TRUECOLOR_DATA_ROOT:-/mnt/d/truecolor-data}"
OUTPUT_DIR="${TRUECOLOR_STAGE3_OUTPUT:-$ROOT/analysis/issa/metrology/results}"

cd "$ROOT"

python -m analysis.issa.metrology.run_stage3 \
  --data-root "$DATA_ROOT" \
  --output-dir "$OUTPUT_DIR"

echo "Stage 3 outputs: $OUTPUT_DIR"
