#!/usr/bin/env bash

python -m analysis.prior_art.build_stage1_corpus \
  --output-dir analysis/prior_art/results \
  "$@"
