#!/usr/bin/env bash

python -m analysis.prior_art.run_stage1 \
  --output-dir analysis/prior_art/results \
  "$@"
