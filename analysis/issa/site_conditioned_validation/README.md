# TrueColor Stage 6 — Site-Conditioned Spectral Representation and Validation

Status: **READY TO RUN — NOT CLOSED**

Stage 6 performs subject-disjoint validation of three spectral representations:

1. **Shared global basis** — one PCA basis and one global mean.
2. **Shared basis with site-specific centering** — one PCA basis fit after removing training-site means.
3. **Site-specific bases** — one PCA basis per body site.

The stage evaluates held-out-subject reconstruction at 1, 2, 3, 5, and 10 components and reports:

- fold-level and aggregate RMSE;
- body-site-specific performance;
- relative improvement over the shared global basis;
- whether site centering materially improves generalization;
- whether site-specific bases materially improve beyond site centering;
- component-count saturation;
- out-of-distribution handling for unseen sites;
- fold leakage checks.

The canonical analysis unit remains:

`body_location_code`-conditioned spectrum

A global subject-level skin-tone scalar remains prohibited.

## Run

```bash
python -m analysis.issa.site_conditioned_validation.run_stage6   --canonical-file /mnt/d/truecolor-data/derived/issa/issa_analysis_table.parquet   --stage5-summary analysis/issa/spectral_geometry/results/stage5_summary.json   --output-dir analysis/issa/site_conditioned_validation/results
```
