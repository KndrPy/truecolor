# TrueColor Stage 5 — Spectral Geometry and Effective Information Dimension

Status: **READY TO RUN — NOT CLOSED**

Stage 5 quantifies the geometry of 400–700 nm reflectance spectra while inheriting the Stage 4 restriction that spectra must be conditioned or stratified by `body_location_code`.

It computes:

- pooled spectral covariance only as a diagnostic reference;
- within-body-site centered covariance;
- per-site eigenvalue spectra;
- participation-ratio effective dimension;
- Shannon effective rank;
- component counts required for 90%, 95%, and 99% explained variance;
- spectral roughness and first/second derivative energy;
- between-site versus total spectral variance;
- site-conditioned PCA scores and reconstruction errors;
- cross-site subspace similarity using principal angles.

The stage does **not** reinstate a global subject-level skin-tone scalar.

## Run

```bash
python -m analysis.issa.spectral_geometry.run_stage5   --canonical-file /mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet   --stage4-summary analysis/issa/measurand/results/stage4_summary.json   --output-dir analysis/issa/spectral_geometry/results
```

A zero exit status means the registered Stage 5 gates passed. Closure may still carry inherited scope limitations.
