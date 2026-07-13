#!/usr/bin/env bash

python -m analysis.governance.run_stage0 \
  --output-dir analysis/governance/results \
  "$@"
