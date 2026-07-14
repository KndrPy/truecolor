#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"
python -m analysis.issa.measurand.run_stage4   --canonical-file "${TRUECOLOR_ISSA_CANONICAL:-/mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet}"   --stage3-summary "${TRUECOLOR_STAGE3_SUMMARY:-analysis/issa/metrology/results/stage3_summary.json}"   --output-dir "${TRUECOLOR_STAGE4_OUTPUT:-analysis/issa/measurand/results}"
STATUS=$?
echo "STAGE4_EXIT_STATUS=$STATUS"
exit "$STATUS"
