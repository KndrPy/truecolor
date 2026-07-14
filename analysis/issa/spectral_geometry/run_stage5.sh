#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

python -m analysis.issa.spectral_geometry.run_stage5   --canonical-file "${TRUECOLOR_ISSA_CANONICAL:-/mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet}"   --stage4-summary "${TRUECOLOR_STAGE4_SUMMARY:-analysis/issa/measurand/results/stage4_summary.json}"   --output-dir "${TRUECOLOR_STAGE5_OUTPUT:-analysis/issa/spectral_geometry/results}"

STATUS=$?
echo "STAGE5_EXIT_STATUS=$STATUS"
exit "$STATUS"
