#!/usr/bin/env bash

python -m analysis.prior_art.harvest_stage1_candidates \
  --output analysis/prior_art/results/stage1_candidate_harvest.json \
  "$@"
