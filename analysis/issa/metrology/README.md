# TrueColor Stage 3 — ISSA Metrology and Provenance Closure

Status: **READY TO RUN — NOT CLOSED**

This stage audits the actual ISSA source and prepared split files before any
spectral geometry, observability, CRB, or predictive analysis.

## Default data root

`/mnt/d/truecolor-data`

Override with:

```bash
export TRUECOLOR_DATA_ROOT=/path/to/data
```

## Run

From the repository root:

```bash
python -m analysis.issa.metrology.run_stage3 \
  --data-root "${TRUECOLOR_DATA_ROOT:-/mnt/d/truecolor-data}" \
  --output-dir analysis/issa/metrology/results
```

The runner:

1. inventories candidate ISSA files;
2. identifies tabular sources and split files;
3. infers wavelength and metadata columns;
4. validates the 400–700 nm / 10 nm grid;
5. audits subject/composite identity and split leakage;
6. detects exact and near-duplicate spectra;
7. audits missingness and physical range violations;
8. summarizes instrument, origin, body-site, and SCI/SCE distributions;
9. estimates variance components and an empirical metrology floor where repeated comparable measurements exist;
10. emits `STAGE_3_CLOSED.yaml` only if all hard gates pass.

## Required packages

```bash
python -m pip install pandas numpy scipy scikit-learn pyarrow pyyaml openpyxl
```

## Closure rule

Stage 3 is closed only when:

- canonical row count is reconciled;
- 31 wavelengths are present at 400–700 nm in 10 nm steps;
- subject/component split leakage is zero;
- all source files have immutable hashes;
- provenance and identity ambiguities are explicitly classified;
- physically inadmissible rows are excluded by deterministic rules;
- pooling restrictions are declared from the instrument/origin audit;
- the closure report records every failed, passed, or narrowed gate.
