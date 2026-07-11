#!/usr/bin/env python3
"""Build the private NPZ input bundle consumed by bootstrap_linear_stability.py.

This script never writes raw records to GitHub. It converts a local CSV or
Parquet table into a compact local NPZ with validated feature, target, and
subject arrays.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--subject-column", required=True)
    parser.add_argument("--target-columns", nargs="+", required=True)
    parser.add_argument(
        "--feature-regex",
        default=r"^(?:r_|reflectance_)?(?P<wavelength>\d{3}(?:\.\d+)?)$",
        help="Regex matched against feature column names; must include a named wavelength group.",
    )
    parser.add_argument(
        "--feature-columns-json",
        type=Path,
        help="Optional JSON list of explicit ordered feature columns. Overrides --feature-regex.",
    )
    return parser.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def resolve_features(frame: pd.DataFrame, args: argparse.Namespace) -> tuple[list[str], np.ndarray]:
    if args.feature_columns_json:
        names = json.loads(args.feature_columns_json.read_text(encoding="utf-8"))
        if not isinstance(names, list) or not names:
            raise ValueError("feature-columns-json must contain a non-empty JSON list")
        features = [str(name) for name in names]
        wavelengths = []
        pattern = re.compile(args.feature_regex)
        for name in features:
            match = pattern.match(name)
            if not match:
                raise ValueError(f"Feature column does not match feature-regex: {name}")
            wavelengths.append(float(match.group("wavelength")))
    else:
        pattern = re.compile(args.feature_regex)
        pairs: list[tuple[float, str]] = []
        for column in frame.columns:
            match = pattern.match(str(column))
            if match:
                pairs.append((float(match.group("wavelength")), str(column)))
        if not pairs:
            raise ValueError("No feature columns matched feature-regex")
        pairs.sort(key=lambda item: item[0])
        wavelengths = [item[0] for item in pairs]
        features = [item[1] for item in pairs]

    if len(set(features)) != len(features):
        raise ValueError("Feature columns must be unique")
    if len(set(wavelengths)) != len(wavelengths):
        raise ValueError("Feature wavelengths must be unique")
    missing = [name for name in features if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    return features, np.asarray(wavelengths, dtype=np.float64)


def main() -> None:
    args = parse_args()
    frame = read_table(args.input)
    required = [args.subject_column, *args.target_columns]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    feature_columns, wavelengths = resolve_features(frame, args)
    selected = frame[[args.subject_column, *feature_columns, *args.target_columns]].copy()
    null_counts = selected.isna().sum()
    if int(null_counts.sum()) > 0:
        details = null_counts[null_counts.gt(0)].to_dict()
        raise ValueError(f"Selected analysis columns contain missing values: {details}")

    subject_ids = selected[args.subject_column].astype(str).to_numpy()
    if (subject_ids == "").any():
        raise ValueError("Subject identifiers cannot be empty")
    X = selected[feature_columns].to_numpy(dtype=np.float64)
    Y = selected[args.target_columns].to_numpy(dtype=np.float64)
    if not np.isfinite(X).all() or not np.isfinite(Y).all():
        raise ValueError("Feature and target matrices must contain only finite values")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        X=X,
        Y=Y,
        subject_ids=subject_ids,
        wavelengths_nm=wavelengths,
        target_names=np.asarray(args.target_columns, dtype=object),
    )

    summary = {
        "output": str(args.output),
        "measurements": int(X.shape[0]),
        "subjects": int(len(np.unique(subject_ids))),
        "features": int(X.shape[1]),
        "targets": int(Y.shape[1]),
        "feature_columns": feature_columns,
        "wavelengths_nm": wavelengths.tolist(),
        "target_columns": list(args.target_columns),
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
