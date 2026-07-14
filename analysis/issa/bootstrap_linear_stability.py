#!/usr/bin/env python3
"""Deterministic, resumable subject-cluster bootstrap for ISSA linear models.

Private arrays remain local. The input NPZ must contain:
  X              float matrix [measurements, wavelengths]
  Y              float matrix [measurements, targets]
  subject_ids    string/object vector [measurements]
  wavelengths_nm numeric vector [wavelengths]
  target_names   string/object vector [targets]

The runner writes one atomic checkpoint after every completed repeat. A repeat is
considered complete only when every requested model has exactly
n_targets * n_wavelengths coefficient rows and a matching diagnostic row.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Set numerical-library limits before importing NumPy/scikit-learn.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("BLIS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import MultiTaskElasticNet, MultiTaskLasso, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


@dataclass(frozen=True)
class Bundle:
    X: np.ndarray
    Y: np.ndarray
    subject_ids: np.ndarray
    wavelengths_nm: np.ndarray
    target_names: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--hyperparameters", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260711)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=("ridge_l2", "elastic_net", "lasso_l1"),
        default=("ridge_l2", "elastic_net"),
    )
    parser.add_argument("--thread-limit", type=int, default=1)
    parser.add_argument("--elastic-max-iter", type=int, default=30_000)
    parser.add_argument("--elastic-tol", type=float, default=1e-6)
    parser.add_argument("--lasso-max-iter", type=int, default=50_000)
    parser.add_argument("--lasso-tol", type=float, default=1e-5)
    return parser.parse_args()


def load_bundle(path: Path) -> Bundle:
    if not path.exists():
        raise FileNotFoundError(path)
    with np.load(path, allow_pickle=True) as payload:
        required = {"X", "Y", "subject_ids", "wavelengths_nm", "target_names"}
        missing = required.difference(payload.files)
        if missing:
            raise ValueError(f"Bundle is missing keys: {sorted(missing)}")
        bundle = Bundle(
            X=np.asarray(payload["X"], dtype=np.float64),
            Y=np.asarray(payload["Y"], dtype=np.float64),
            subject_ids=np.asarray(payload["subject_ids"]).astype(str),
            wavelengths_nm=np.asarray(payload["wavelengths_nm"], dtype=np.float64),
            target_names=np.asarray(payload["target_names"]).astype(str),
        )
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: Bundle) -> None:
    if bundle.X.ndim != 2 or bundle.Y.ndim != 2:
        raise ValueError("X and Y must both be two-dimensional")
    n_rows = bundle.X.shape[0]
    if bundle.Y.shape[0] != n_rows or len(bundle.subject_ids) != n_rows:
        raise ValueError("X, Y, and subject_ids must have identical row counts")
    if bundle.X.shape[1] != len(bundle.wavelengths_nm):
        raise ValueError("X columns must match wavelengths_nm")
    if bundle.Y.shape[1] != len(bundle.target_names):
        raise ValueError("Y columns must match target_names")
    if n_rows == 0 or len(np.unique(bundle.subject_ids)) < 2:
        raise ValueError("Bundle must contain measurements from at least two subjects")
    if not np.isfinite(bundle.X).all() or not np.isfinite(bundle.Y).all():
        raise ValueError("X and Y must contain only finite values")
    if len(np.unique(bundle.wavelengths_nm)) != len(bundle.wavelengths_nm):
        raise ValueError("wavelengths_nm must be unique")


def load_hyperparameters(path: Path) -> dict[str, float]:
    if not path.exists():
        raise FileNotFoundError(path)
    values = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "ridge_alpha",
        "elastic_net_alpha",
        "elastic_net_l1_ratio",
        "lasso_alpha",
    }
    missing = required.difference(values)
    if missing:
        raise ValueError(f"Hyperparameter file is missing: {sorted(missing)}")
    return {key: float(values[key]) for key in required}


def atomic_parquet(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, destination)


def load_frame(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=columns)


def build_model(name: str, hp: dict[str, float], args: argparse.Namespace, repeat: int) -> Pipeline:
    if name == "ridge_l2":
        estimator: Any = Ridge(alpha=hp["ridge_alpha"])
    elif name == "elastic_net":
        estimator = MultiTaskElasticNet(
            alpha=hp["elastic_net_alpha"],
            l1_ratio=hp["elastic_net_l1_ratio"],
            max_iter=args.elastic_max_iter,
            tol=args.elastic_tol,
            random_state=args.seed + repeat,
            selection="cyclic",
        )
    elif name == "lasso_l1":
        estimator = MultiTaskLasso(
            alpha=hp["lasso_alpha"],
            max_iter=args.lasso_max_iter,
            tol=args.lasso_tol,
            random_state=args.seed + repeat,
            selection="cyclic",
        )
    else:
        raise ValueError(name)
    return Pipeline([("scaler", StandardScaler()), ("regressor", estimator)])


def scalar_iteration_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return int(np.max(value))
    return int(value)


def complete_repeat_ids(
    coefficients: pd.DataFrame,
    diagnostics: pd.DataFrame,
    models: tuple[str, ...],
    rows_per_model: int,
) -> set[int]:
    completed: set[int] = set()
    if coefficients.empty or diagnostics.empty:
        return completed
    for repeat in sorted(coefficients["repeat"].astype(int).unique()):
        valid = True
        for model in models:
            row_count = len(
                coefficients[
                    coefficients["repeat"].astype(int).eq(repeat)
                    & coefficients["model"].eq(model)
                ]
            )
            diagnostic_count = len(
                diagnostics[
                    diagnostics["repeat"].astype(int).eq(repeat)
                    & diagnostics["model"].eq(model)
                ]
            )
            if row_count != rows_per_model or diagnostic_count != 1:
                valid = False
                break
        if valid:
            completed.add(repeat)
    return completed


def main() -> None:
    args = parse_args()
    if args.repeats <= 0 or args.thread_limit <= 0:
        raise ValueError("repeats and thread-limit must be positive")

    bundle = load_bundle(args.bundle)
    hp = load_hyperparameters(args.hyperparameters)
    models = tuple(dict.fromkeys(args.models))

    coefficient_path = args.output_dir / "bootstrap_linear_coefficients.parquet"
    sample_path = args.output_dir / "bootstrap_subject_samples.parquet"
    diagnostic_path = args.output_dir / "bootstrap_fit_diagnostics.parquet"
    run_manifest_path = args.output_dir / "bootstrap_run_manifest.json"

    coefficients = load_frame(
        coefficient_path,
        ["repeat", "model", "target", "wavelength_nm", "coefficient_standardized"],
    )
    samples = load_frame(
        sample_path,
        ["repeat", "subject_id", "bootstrap_multiplicity", "source_measurement_count"],
    )
    diagnostics = load_frame(
        diagnostic_path,
        [
            "repeat", "model", "fit_seconds", "n_iter", "sampled_measurements",
            "unique_sampled_subjects", "converged", "fit_status",
            "convergence_warning", "max_iter", "tolerance",
        ],
    )

    unique_subjects = np.unique(bundle.subject_ids)
    subject_to_indices = {
        subject: np.flatnonzero(bundle.subject_ids == subject) for subject in unique_subjects
    }
    rows_per_model = bundle.Y.shape[1] * bundle.X.shape[1]
    completed = complete_repeat_ids(coefficients, diagnostics, models, rows_per_model)

    manifest = {
        "bundle_path": str(args.bundle.resolve()),
        "hyperparameters_path": str(args.hyperparameters.resolve()),
        "repeats": args.repeats,
        "seed": args.seed,
        "models": list(models),
        "thread_limit": args.thread_limit,
        "n_measurements": int(bundle.X.shape[0]),
        "n_subjects": int(len(unique_subjects)),
        "n_wavelengths": int(bundle.X.shape[1]),
        "n_targets": int(bundle.Y.shape[1]),
        "target_names": bundle.target_names.tolist(),
        "wavelengths_nm": bundle.wavelengths_nm.tolist(),
        "hyperparameters": hp,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Completed repeats loaded: {sorted(completed)}", flush=True)
    print(f"Remaining repeats: {args.repeats - len(completed)}", flush=True)

    for repeat in range(args.repeats):
        if repeat in completed:
            continue
        started = time.perf_counter()
        rng = np.random.default_rng(np.random.SeedSequence([args.seed, repeat]))
        sampled_subjects = rng.choice(unique_subjects, size=len(unique_subjects), replace=True)
        sampled_indices = np.concatenate([subject_to_indices[s] for s in sampled_subjects])
        X_bootstrap = bundle.X[sampled_indices]
        Y_bootstrap = bundle.Y[sampled_indices]
        multiplicities = pd.Series(sampled_subjects).value_counts()

        repeat_coefficients: list[dict[str, Any]] = []
        repeat_diagnostics: list[dict[str, Any]] = []
        for model_name in models:
            model = build_model(model_name, hp, args, repeat)
            model_started = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                with threadpool_limits(limits=args.thread_limit):
                    model.fit(X_bootstrap, Y_bootstrap)
            fit_seconds = time.perf_counter() - model_started
            warned = any(issubclass(item.category, ConvergenceWarning) for item in caught)
            regressor = model.named_steps["regressor"]
            n_iter = scalar_iteration_count(getattr(regressor, "n_iter_", None))
            max_iter = getattr(regressor, "max_iter", None)
            tolerance = getattr(regressor, "tol", None)
            converged = not warned and (n_iter is None or max_iter is None or n_iter < max_iter)

            repeat_diagnostics.append(
                {
                    "repeat": repeat,
                    "model": model_name,
                    "fit_seconds": fit_seconds,
                    "n_iter": n_iter,
                    "sampled_measurements": int(len(sampled_indices)),
                    "unique_sampled_subjects": int(len(multiplicities)),
                    "converged": bool(converged),
                    "fit_status": "admissible" if converged else "requires_refit",
                    "convergence_warning": bool(warned),
                    "max_iter": max_iter,
                    "tolerance": tolerance,
                }
            )
            for target_index, target in enumerate(bundle.target_names):
                for feature_index, wavelength in enumerate(bundle.wavelengths_nm):
                    repeat_coefficients.append(
                        {
                            "repeat": repeat,
                            "model": model_name,
                            "target": str(target),
                            "wavelength_nm": float(wavelength),
                            "coefficient_standardized": float(
                                regressor.coef_[target_index, feature_index]
                            ),
                        }
                    )

        expected_rows = len(models) * rows_per_model
        if len(repeat_coefficients) != expected_rows:
            raise RuntimeError(
                f"Repeat {repeat} generated {len(repeat_coefficients)} rows; expected {expected_rows}"
            )

        repeat_mask = coefficients["repeat"].astype(int).eq(repeat) if not coefficients.empty else None
        if repeat_mask is not None:
            coefficients = coefficients[~(repeat_mask & coefficients["model"].isin(models))].copy()
        if not diagnostics.empty:
            diagnostics = diagnostics[
                ~(diagnostics["repeat"].astype(int).eq(repeat) & diagnostics["model"].isin(models))
            ].copy()
        if not samples.empty:
            samples = samples[~samples["repeat"].astype(int).eq(repeat)].copy()

        sample_rows = [
            {
                "repeat": repeat,
                "subject_id": subject,
                "bootstrap_multiplicity": int(count),
                "source_measurement_count": int(len(subject_to_indices[subject])),
            }
            for subject, count in multiplicities.items()
        ]
        coefficients = pd.concat([coefficients, pd.DataFrame(repeat_coefficients)], ignore_index=True)
        diagnostics = pd.concat([diagnostics, pd.DataFrame(repeat_diagnostics)], ignore_index=True)
        samples = pd.concat([samples, pd.DataFrame(sample_rows)], ignore_index=True)

        coefficients = coefficients.drop_duplicates(
            ["repeat", "model", "target", "wavelength_nm"], keep="last"
        ).sort_values(["repeat", "model", "target", "wavelength_nm"]).reset_index(drop=True)
        diagnostics = diagnostics.drop_duplicates(
            ["repeat", "model"], keep="last"
        ).sort_values(["repeat", "model"]).reset_index(drop=True)
        samples = samples.drop_duplicates(
            ["repeat", "subject_id"], keep="last"
        ).sort_values(["repeat", "subject_id"]).reset_index(drop=True)

        atomic_parquet(coefficients, coefficient_path)
        atomic_parquet(diagnostics, diagnostic_path)
        atomic_parquet(samples, sample_path)
        print(
            f"Completed repeat {repeat + 1}/{args.repeats} | "
            f"seconds={time.perf_counter() - started:.1f} | rows={len(coefficients)} | "
            f"diagnostics={repeat_diagnostics}",
            flush=True,
        )


if __name__ == "__main__":
    main()
