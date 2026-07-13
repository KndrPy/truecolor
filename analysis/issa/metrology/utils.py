from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import re
from typing import Iterable, Any

import numpy as np
import pandas as pd


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def normalize_name(name: Any) -> str:
    s = str(name).strip().lower()
    s = s.replace("λ", "lambda")
    s = re.sub(r"[\s\-\./\\]+", "_", s)
    s = re.sub(r"[^a-z0-9_*]+", "", s)
    return s.strip("_")


def infer_wavelength_nm(column: Any) -> int | None:
    raw = str(column).strip().lower()
    nums = re.findall(r"(?<!\d)(\d{3})(?!\d)", raw)
    if not nums:
        return None
    vals = [int(x) for x in nums]
    vals = [x for x in vals if 300 <= x <= 1100]
    return vals[0] if len(vals) == 1 else None


def find_first_column(columns: Iterable[Any], candidates: Iterable[str]) -> str | None:
    normalized = {normalize_name(c): str(c) for c in columns}
    for cand in candidates:
        key = normalize_name(cand)
        if key in normalized:
            return normalized[key]
    return None


def safe_write_table(df: pd.DataFrame, path_without_suffix: Path) -> list[Path]:
    written: list[Path] = []
    csv_path = path_without_suffix.with_suffix(".csv")
    df.to_csv(csv_path, index=False)
    written.append(csv_path)
    try:
        parquet_path = path_without_suffix.with_suffix(".parquet")
        df.to_parquet(parquet_path, index=False)
        written.append(parquet_path)
    except Exception:
        pass
    return written


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", low_memory=False)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".feather":
        return pd.read_feather(path)
    raise ValueError(f"Unsupported table type: {path}")


def json_dumps_safe(value: Any) -> str:
    def default(obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        if isinstance(obj, Path):
            return str(obj)
        if pd.isna(obj):
            return None
        return str(obj)
    return json.dumps(value, default=default, sort_keys=True)


def canonical_subject_key(df: pd.DataFrame, subject_col: str | None, origin_col: str | None) -> pd.Series:
    if subject_col is None:
        return pd.Series([pd.NA] * len(df), index=df.index, dtype="string")
    subject = df[subject_col].astype("string").str.strip()
    if origin_col is None:
        return subject
    origin = df[origin_col].astype("string").str.strip()
    return origin.fillna("<NA>") + "::" + subject.fillna("<NA>")
