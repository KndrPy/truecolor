# TrueColor Stage 4 — Measurand Stability

Status: READY TO RUN — NOT CLOSED.

Run:

```bash
python -m analysis.issa.measurand.run_stage4   --canonical-file /mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet   --stage3-summary analysis/issa/metrology/results/stage3_summary.json   --output-dir analysis/issa/measurand/results
```

Stage 4 reconstructs ITA, quantifies ITA numerical sensitivity, estimates erythema contamination using a*, measures body-site/instrument/origin/specular effects, and attempts protected/exposed and SCI/SCE pairing. It emits `CLOSED` only when all mandatory gates pass.
