#!/usr/bin/env bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"
python -m analysis.issa.wavelength_attribution.run_stage7   --canonical-file "${TRUECOLOR_ISSA_CANONICAL:-/mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet}"   --stage6-summary "${TRUECOLOR_STAGE6_SUMMARY:-analysis/issa/site_conditioned_validation/results/stage6_summary.json}"   --output-dir "${TRUECOLOR_STAGE7_OUTPUT:-analysis/issa/wavelength_attribution/results}"
STATUS=$?
echo "STAGE7_EXIT_STATUS=$STATUS"
exit "$STATUS"
