# ISSA local analysis recovery

This directory replaces fragile, stateful notebook execution with a deterministic local workflow. Raw measurements, subject identifiers, NPZ bundles, Parquet checkpoints, and generated results remain local and are excluded by `.gitignore`.

## 1. Environment

```bash
cd ~/truecolor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install numpy pandas pyarrow scikit-learn threadpoolctl pytest
```

## 2. Build a private analysis bundle

The source table must contain one row per ISSA measurement, a subject identifier, ordered reflectance columns, and the target columns. The default feature matcher accepts names such as `400`, `r_400`, or `reflectance_400`.

```bash
python analysis/issa/build_analysis_bundle.py \
  --input /mnt/d/truecolor-data/processed/issa/issa_training_measurements.parquet \
  --output data-local/issa/issa_training_bundle.npz \
  --subject-column subject_id \
  --target-columns L_star a_star b_star
```

Use the actual canonical local table and column names. The builder fails closed on missing values, duplicate wavelengths, inconsistent dimensions, or non-finite values. It also writes a local summary JSON next to the NPZ.

## 3. Run the admissible Ridge and Elastic-Net bootstrap

```bash
python analysis/issa/bootstrap_linear_stability.py \
  --bundle data-local/issa/issa_training_bundle.npz \
  --hyperparameters analysis/issa/selected_linear_hyperparameters.json \
  --output-dir results/issa_supervised_stability/interpretability \
  --repeats 100 \
  --seed 20260711 \
  --models ridge_l2 elastic_net \
  --thread-limit 1
```

The runner:

- resamples subjects with replacement and carries every measurement for each sampled subject;
- uses a repeat-specific `SeedSequence([seed, repeat])`;
- checkpoints coefficients, sampled-subject multiplicities, and diagnostics after every repeat;
- resumes only repeat-model combinations that are structurally complete;
- captures `ConvergenceWarning` and marks the fit `requires_refit`;
- limits BLAS/OpenMP thread pools to prevent oversubscription;
- writes Parquet files atomically through a temporary file and `os.replace`.

Expected coefficient rows per model and repeat are:

```text
3 targets × 31 wavelengths = 93 rows
```

For Ridge plus Elastic Net, each completed repeat must therefore add 186 coefficient rows.

## 4. Lasso repair experiment

The lost AMD run showed Lasso reaching `max_iter=20000` for all three completed repeats, while Elastic Net converged and Ridge was immediate. Lasso must remain separate from the admissible main run.

Test three repeats first:

```bash
python analysis/issa/bootstrap_linear_stability.py \
  --bundle data-local/issa/issa_training_bundle.npz \
  --hyperparameters analysis/issa/selected_linear_hyperparameters.json \
  --output-dir results/issa_supervised_stability/lasso_repair \
  --repeats 3 \
  --seed 20260711 \
  --models lasso_l1 \
  --lasso-max-iter 50000 \
  --lasso-tol 1e-5 \
  --thread-limit 1
```

Accept a repaired fit only when `convergence_warning` is false, `fit_status` is `admissible`, and `n_iter < max_iter`. Do not suppress or ignore convergence warnings.

## 5. Validate checkpoints

```bash
python analysis/issa/validate_bootstrap_outputs.py \
  --output-dir results/issa_supervised_stability/interpretability \
  --repeats 100 \
  --models ridge_l2 elastic_net \
  --targets 3 \
  --wavelengths 31
```

## 6. Preserve results outside the workstation

Generated scientific artifacts remain private and must not be committed to the public repository. Copy encrypted result bundles to durable private storage after each analysis stage. Commit only code, public aggregate summaries, and sanitized provenance.
