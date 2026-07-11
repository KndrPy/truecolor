#!/usr/bin/env python3
"""Prepare the private ISSA analytical table and NPZ bundle from the source workbook.

Raw records and generated outputs stay local. The script validates the recovered
ISSA schema before writing any artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd

SHEET_NAME = "ISSA"
HEADER_ROW_ZERO_BASED = 11
EXPECTED_MEASUREMENTS = 15_256
EXPECTED_SUBJECTS = 2_107
WAVELENGTHS = list(range(400, 701, 10))
TARGET_COLUMNS = ["L*", "a*", "b*"]
METADATA_RENAME = {
    "A": "record_number",
    "B": "origin_code",
    "C": "subject_number",
    "D": "ethnicity_code",
    "E": "gender_code",
    "F": "age_group_code",
    "G": "body_location_code",
    "H": "instrument_code",
    "I": "spin_spex_code",
    "J": "start_wavelength_nm",
    "K": "end_wavelength_nm",
    "L": "wavelength_interval_nm",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(args.input)

    frame = pd.read_excel(
        args.input,
        sheet_name=SHEET_NAME,
        header=HEADER_ROW_ZERO_BASED,
        engine="openpyxl",
    )
    frame = frame.iloc[:, :69].copy()
    frame = frame.loc[frame["A"].notna()].copy()

    if len(frame) != EXPECTED_MEASUREMENTS:
        raise ValueError(f"Expected {EXPECTED_MEASUREMENTS} measurements, found {len(frame)}")

    required = [*METADATA_RENAME, *WAVELENGTHS, *TARGET_COLUMNS]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing recovered ISSA columns: {missing}")

    selected = frame[required].copy()
    selected.rename(columns=METADATA_RENAME, inplace=True)

    for column in ["origin_code", "subject_number", "record_number"]:
        selected[column] = pd.to_numeric(selected[column], errors="raise").astype("int64")

    selected["subject_id"] = (
        selected["origin_code"].astype(str)
        + "::"
        + selected["subject_number"].astype(str)
    )

    unique_subjects = selected["subject_id"].nunique(dropna=False)
    if unique_subjects != EXPECTED_SUBJECTS:
        raise ValueError(f"Expected {EXPECTED_SUBJECTS} subjects, found {unique_subjects}")

    analysis_columns = [
        "record_number",
        "origin_code",
        "subject_number",
        "subject_id",
        "ethnicity_code",
        "gender_code",
        "age_group_code",
        "body_location_code",
        "instrument_code",
        "spin_spex_code",
        "start_wavelength_nm",
        "end_wavelength_nm",
        "wavelength_interval_nm",
        *WAVELENGTHS,
        *TARGET_COLUMNS,
    ]
    selected = selected[analysis_columns].copy()

    numeric_columns = [*WAVELENGTHS, *TARGET_COLUMNS]
    selected[numeric_columns] = selected[numeric_columns].apply(pd.to_numeric, errors="raise")
    null_counts = selected[analysis_columns].isna().sum()
    if int(null_counts.sum()) > 0:
        raise ValueError(f"Null values in analysis table: {null_counts[null_counts.gt(0)].to_dict()}")

    X = selected[WAVELENGTHS].to_numpy(dtype=np.float64)
    Y = selected[TARGET_COLUMNS].to_numpy(dtype=np.float64)
    subject_ids = selected["subject_id"].astype(str).to_numpy()

    if not np.isfinite(X).all() or not np.isfinite(Y).all():
        raise ValueError("Non-finite values found in ISSA matrices")
    if X.shape != (EXPECTED_MEASUREMENTS, len(WAVELENGTHS)):
        raise ValueError(f"Unexpected X shape: {X.shape}")
    if Y.shape != (EXPECTED_MEASUREMENTS, len(TARGET_COLUMNS)):
        raise ValueError(f"Unexpected Y shape: {Y.shape}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = args.output_dir / "issa_analysis_table.parquet"
    bundle_path = args.output_dir / "issa_analysis_bundle.npz"
    summary_path = args.output_dir / "issa_analysis_summary.json"

    selected.to_parquet(parquet_path, index=False)

    with NamedTemporaryFile(dir=args.output_dir, suffix=".npz", delete=False) as handle:
        temporary_bundle = Path(handle.name)
    try:
        np.savez_compressed(
            temporary_bundle,
            X=X,
            Y=Y,
            subject_ids=subject_ids,
            wavelengths_nm=np.asarray(WAVELENGTHS, dtype=np.float64),
            target_names=np.asarray(TARGET_COLUMNS, dtype=object),
        )
        os.replace(temporary_bundle, bundle_path)
    finally:
        temporary_bundle.unlink(missing_ok=True)

    summary = {
        "source_workbook": str(args.input),
        "source_workbook_sha256": sha256_file(args.input),
        "sheet": SHEET_NAME,
        "excel_header_row": HEADER_ROW_ZERO_BASED + 1,
        "measurements": int(X.shape[0]),
        "subjects": int(unique_subjects),
        "features": int(X.shape[1]),
        "targets": int(Y.shape[1]),
        "subject_key": "origin_code::subject_number",
        "wavelengths_nm": WAVELENGTHS,
        "target_columns": TARGET_COLUMNS,
        "feature_min": float(X.min()),
        "feature_max": float(X.max()),
        "parquet_path": str(parquet_path),
        "parquet_sha256": sha256_file(parquet_path),
        "bundle_path": str(bundle_path),
        "bundle_sha256": sha256_file(bundle_path),
    }
    atomic_write_bytes(
        summary_path,
        (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
