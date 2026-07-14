#!/usr/bin/env python3
"""Fail-closed validation for ISSA bootstrap checkpoints."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--targets", type=int, required=True)
    parser.add_argument("--wavelengths", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coefficient_path = args.output_dir / "bootstrap_linear_coefficients.parquet"
    diagnostic_path = args.output_dir / "bootstrap_fit_diagnostics.parquet"
    sample_path = args.output_dir / "bootstrap_subject_samples.parquet"

    for path in (coefficient_path, diagnostic_path, sample_path):
        if not path.exists():
            raise FileNotFoundError(path)

    coefficients = pd.read_parquet(coefficient_path)
    diagnostics = pd.read_parquet(diagnostic_path)
    samples = pd.read_parquet(sample_path)

    expected_rows = args.targets * args.wavelengths
    issues: list[str] = []

    duplicate_keys = coefficients.duplicated(
        ["repeat", "model", "target", "wavelength_nm"], keep=False
    )
    if duplicate_keys.any():
        issues.append(f"Duplicate coefficient keys: {int(duplicate_keys.sum())}")

    diagnostic_duplicates = diagnostics.duplicated(["repeat", "model"], keep=False)
    if diagnostic_duplicates.any():
        issues.append(f"Duplicate diagnostic keys: {int(diagnostic_duplicates.sum())}")

    sample_duplicates = samples.duplicated(["repeat", "subject_id"], keep=False)
    if sample_duplicates.any():
        issues.append(f"Duplicate sample keys: {int(sample_duplicates.sum())}")

    for repeat in range(args.repeats):
        repeat_samples = samples[samples["repeat"].astype(int).eq(repeat)]
        if repeat_samples.empty:
            issues.append(f"Repeat {repeat}: no saved subject sample")
        for model in args.models:
            subset = coefficients[
                coefficients["repeat"].astype(int).eq(repeat)
                & coefficients["model"].eq(model)
            ]
            if len(subset) != expected_rows:
                issues.append(
                    f"Repeat {repeat}, model {model}: {len(subset)} rows; expected {expected_rows}"
                )
            diagnostic = diagnostics[
                diagnostics["repeat"].astype(int).eq(repeat)
                & diagnostics["model"].eq(model)
            ]
            if len(diagnostic) != 1:
                issues.append(
                    f"Repeat {repeat}, model {model}: {len(diagnostic)} diagnostic rows; expected 1"
                )
            elif diagnostic.iloc[0].get("fit_status") != "admissible":
                issues.append(
                    f"Repeat {repeat}, model {model}: fit_status={diagnostic.iloc[0].get('fit_status')}"
                )

    expected_total = args.repeats * len(args.models) * expected_rows
    if len(coefficients) != expected_total:
        issues.append(
            f"Total coefficient rows {len(coefficients)}; expected {expected_total}"
        )

    if issues:
        print("BOOTSTRAP VALIDATION FAILED")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)

    print("BOOTSTRAP VALIDATION PASSED")
    print(f"Repeats: {args.repeats}")
    print(f"Models: {', '.join(args.models)}")
    print(f"Coefficient rows: {len(coefficients)}")
    print(f"Sample rows: {len(samples)}")
    print(f"Diagnostic rows: {len(diagnostics)}")


if __name__ == "__main__":
    main()
