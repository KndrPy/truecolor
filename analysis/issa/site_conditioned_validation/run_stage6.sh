#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

python -m analysis.issa.site_conditioned_validation.run_stage6   --canonical-file "${TRUECOLOR_ISSA_CANONICAL:-/mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet}"   --stage5-summary "${TRUECOLOR_STAGE5_SUMMARY:-analysis/issa/spectral_geometry/results/stage5_summary.json}"   --output-dir "${TRUECOLOR_STAGE6_OUTPUT:-analysis/issa/site_conditioned_validation/results}"

STATUS=$?
echo "STAGE6_EXIT_STATUS=$STATUS"
exit "$STATUS"
