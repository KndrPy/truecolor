# TrueColor Stage 7 — Dominant-Axis Interpretation and Wavelength Attribution

Status: **READY TO RUN — NOT CLOSED**

Stage 7 characterizes the compact three-component, body-site-specific representation established in Stage 6. It uses subject-level bootstrap resampling within each body site, sign-aligns PCA loadings, reports p2.5, p50, p97.5, and p99 attribution statistics, measures cross-site loading agreement, and relates component scores to registered optical descriptors.

Biological identity is not assigned by assertion. Broadband reflectance, slope, curvature, red–green contrasts, and hemoglobin-sensitive indices are treated as empirical optical descriptors or proxies.

```bash
python -m analysis.issa.wavelength_attribution.run_stage7 \
  --canonical-file /mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet \
  --stage6-summary analysis/issa/site_conditioned_validation/results/stage6_summary.json \
  --output-dir analysis/issa/wavelength_attribution/results
```
