from __future__ import annotations

import argparse
from pathlib import Path
from collections import defaultdict
import itertools
import json
import math
import os
import sys
import traceback

import numpy as np
import pandas as pd
import yaml
from scipy.spatial.distance import cdist
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from .utils import (
    sha256_file,
    normalize_name,
    infer_wavelength_nm,
    find_first_column,
    safe_write_table,
    read_table,
    canonical_subject_key,
)


def load_config() -> dict:
    config_path = Path(__file__).with_name("config.yaml")
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def discover_files(data_root: Path, cfg: dict) -> pd.DataFrame:
    rows = []
    include_ext = set(cfg["discovery"]["include_extensions"])
    filename_tokens = [x.lower() for x in cfg["discovery"]["filename_tokens"]]
    exclude_tokens = [x.lower() for x in cfg["discovery"]["exclude_path_tokens"]]

    for path in data_root.rglob("*"):
        if not path.is_file():
            continue
        low = str(path).lower()
        if any(tok in low for tok in exclude_tokens):
            continue
        if path.suffix.lower() not in include_ext:
            continue
        token_score = sum(tok in path.name.lower() for tok in filename_tokens)
        try:
            stat = path.stat()
            digest = sha256_file(path)
            hash_error = ""
        except Exception as exc:
            stat = None
            digest = ""
            hash_error = repr(exc)
        rows.append(
            {
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix.lower(),
                "token_score": token_score,
                "size_bytes": stat.st_size if stat else None,
                "mtime_ns": stat.st_mtime_ns if stat else None,
                "sha256": digest,
                "hash_error": hash_error,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["path","name","suffix","token_score","size_bytes","mtime_ns","sha256","hash_error"])
    return pd.DataFrame(rows).sort_values(["token_score", "size_bytes"], ascending=[False, False]).reset_index(drop=True)


def inspect_schema(path: Path) -> tuple[pd.DataFrame | None, dict]:
    meta = {"path": str(path), "read_ok": False, "error": ""}
    try:
        df = read_table(path)
        meta.update(
            {
                "read_ok": True,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names_json": json.dumps([str(c) for c in df.columns]),
            }
        )
        return df, meta
    except Exception as exc:
        meta["error"] = repr(exc)
        return None, meta


def detect_columns(df: pd.DataFrame, cfg: dict) -> dict:
    cols = list(df.columns)
    wl = {}
    for c in cols:
        nm = infer_wavelength_nm(c)
        if nm is not None:
            wl[nm] = str(c)

    ccfg = cfg["columns"]
    out = {
        "subject_col": find_first_column(cols, ccfg["subject_candidates"]),
        "origin_col": find_first_column(cols, ccfg["origin_candidates"]),
        "instrument_col": find_first_column(cols, ccfg["instrument_candidates"]),
        "body_site_col": find_first_column(cols, ccfg["body_site_candidates"]),
        "specular_col": find_first_column(cols, ccfg["specular_candidates"]),
        "split_col": find_first_column(cols, ccfg["split_candidates"]),
        "lab_L_col": find_first_column(cols, ccfg["lab_candidates"]["L"]),
        "lab_a_col": find_first_column(cols, ccfg["lab_candidates"]["a"]),
        "lab_b_col": find_first_column(cols, ccfg["lab_candidates"]["b"]),
        "wavelength_map": wl,
    }
    return out


def score_candidate(path: Path, df: pd.DataFrame, det: dict, cfg: dict) -> dict:
    exp = cfg["expected"]
    expected_grid = list(range(exp["wavelength_start_nm"], exp["wavelength_end_nm"] + 1, exp["wavelength_step_nm"]))
    found = sorted(det["wavelength_map"])
    overlap = len(set(found) & set(expected_grid))
    return {
        "path": str(path),
        "rows": len(df),
        "columns": len(df.columns),
        "wavelength_count": len(found),
        "expected_wavelength_overlap": overlap,
        "has_subject": det["subject_col"] is not None,
        "has_origin": det["origin_col"] is not None,
        "has_instrument": det["instrument_col"] is not None,
        "has_body_site": det["body_site_col"] is not None,
        "has_specular": det["specular_col"] is not None,
        "has_split": det["split_col"] is not None,
        "has_lab": all(det[k] is not None for k in ["lab_L_col","lab_a_col","lab_b_col"]),
        "candidate_score": overlap * 10
            + int(det["subject_col"] is not None) * 5
            + int(det["origin_col"] is not None) * 3
            + int(det["instrument_col"] is not None) * 3
            + int(det["body_site_col"] is not None) * 2
            + int(det["specular_col"] is not None) * 2
            + int(all(det[k] is not None for k in ["lab_L_col","lab_a_col","lab_b_col"])) * 5
            - abs(len(df) - exp["canonical_rows"]) / max(exp["canonical_rows"], 1),
    }


def wavelength_integrity(df: pd.DataFrame, det: dict, cfg: dict) -> tuple[pd.DataFrame, dict]:
    exp = cfg["expected"]
    expected = list(range(exp["wavelength_start_nm"], exp["wavelength_end_nm"] + 1, exp["wavelength_step_nm"]))
    found = sorted(det["wavelength_map"])
    rows = []
    for nm in sorted(set(expected) | set(found)):
        rows.append(
            {
                "wavelength_nm": nm,
                "expected": nm in expected,
                "found": nm in found,
                "column": det["wavelength_map"].get(nm),
                "missing_fraction": (
                    pd.to_numeric(df[det["wavelength_map"][nm]], errors="coerce").isna().mean()
                    if nm in found else None
                ),
            }
        )
    summary = {
        "expected_grid": expected,
        "found_grid": found,
        "exact_match": found == expected,
        "expected_count": len(expected),
        "found_count": len(found),
    }
    return pd.DataFrame(rows), summary


def normalize_reflectance_matrix(
    X_raw: pd.DataFrame,
    cfg: dict,
) -> tuple[pd.DataFrame, dict]:
    """
    Resolve the stored ISSA reflectance scale and return fractional reflectance.

    Accepted source representations:
      - fraction: 0.0 to approximately 1.0
      - percent:  0.0 to approximately 100.0

    The canonical source table is never modified.
    """
    q = cfg["quality"]
    finite = X_raw.stack()

    if finite.empty:
        return X_raw.copy(), {
            "reflectance_scale": "unresolved",
            "normalization_factor": None,
            "normalization_applied": False,
            "raw_min": None,
            "raw_median": None,
            "raw_max": None,
        }

    raw_min = float(finite.min())
    raw_median = float(finite.median())
    raw_max = float(finite.max())

    requested = str(q.get("reflectance_scale", "auto")).lower()

    if requested == "fraction":
        scale = "fraction"
        factor = 1.0
    elif requested == "percent":
        scale = "percent"
        factor = 0.01
    elif requested == "auto":
        fraction_max = float(
            q.get("reflectance_fraction_max_detection", 1.5)
        )
        percent_max = float(
            q.get("reflectance_percent_max_detection", 150.0)
        )
        percent_median_threshold = float(
            q.get("reflectance_percent_median_threshold", 1.0)
        )

        if raw_max <= fraction_max:
            scale = "fraction"
            factor = 1.0
        elif (
            raw_max <= percent_max
            and raw_median > percent_median_threshold
        ):
            scale = "percent"
            factor = 0.01
        else:
            scale = "unresolved"
            factor = 1.0
    else:
        raise ValueError(
            "quality.reflectance_scale must be auto, fraction, or percent"
        )

    X_normalized = X_raw * factor

    return X_normalized, {
        "reflectance_scale": scale,
        "normalization_factor": factor,
        "normalization_applied": factor != 1.0,
        "raw_min": raw_min,
        "raw_median": raw_median,
        "raw_max": raw_max,
        "normalized_min": float(X_normalized.stack().min()),
        "normalized_median": float(X_normalized.stack().median()),
        "normalized_max": float(X_normalized.stack().max()),
    }


def quality_audit(
    df: pd.DataFrame,
    det: dict,
    cfg: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    q = cfg["quality"]
    wl_cols = [
        det["wavelength_map"][nm]
        for nm in sorted(det["wavelength_map"])
    ]

    X_raw = df[wl_cols].apply(pd.to_numeric, errors="coerce")
    X, scale_meta = normalize_reflectance_matrix(X_raw, cfg)

    reflectance_min = float(q["reflectance_min_normalized"])
    reflectance_max = float(q["reflectance_max_normalized"])

    flags = pd.DataFrame(index=df.index)
    flags["row_index"] = df.index
    flags["missing_band_count"] = X.isna().sum(axis=1)
    flags["all_bands_missing"] = X.isna().all(axis=1)
    flags["below_min_count"] = (X < reflectance_min).sum(axis=1)
    flags["above_max_count"] = (X > reflectance_max).sum(axis=1)
    flags["constant_spectrum"] = X.nunique(axis=1, dropna=True) <= 1
    flags["min_reflectance"] = X.min(axis=1, skipna=True)
    flags["max_reflectance"] = X.max(axis=1, skipna=True)
    flags["mean_reflectance"] = X.mean(axis=1, skipna=True)
    flags["std_reflectance"] = X.std(axis=1, skipna=True)
    diffs = X.diff(axis=1)
    flags["max_abs_adjacent_jump"] = diffs.abs().max(axis=1, skipna=True)
    flags["admissible_basic"] = (
        (flags["missing_band_count"] == 0)
        & (flags["below_min_count"] == 0)
        & (flags["above_max_count"] == 0)
        & (~flags["constant_spectrum"])
    )

    per_band = []
    for nm, col in sorted(det["wavelength_map"].items()):
        s_raw = pd.to_numeric(df[col], errors="coerce")
        s = s_raw * float(scale_meta["normalization_factor"])

        per_band.append(
            {
                "wavelength_nm": nm,
                "column": col,
                "reflectance_scale": scale_meta["reflectance_scale"],
                "normalization_factor": scale_meta["normalization_factor"],
                "n": len(s),
                "missing_n": int(s.isna().sum()),
                "missing_fraction": float(s.isna().mean()),
                "below_min_n": int((s < reflectance_min).sum()),
                "above_max_n": int((s > reflectance_max).sum()),
                "raw_min": (
                    float(s_raw.min())
                    if s_raw.notna().any()
                    else None
                ),
                "raw_mean": (
                    float(s_raw.mean())
                    if s_raw.notna().any()
                    else None
                ),
                "raw_max": (
                    float(s_raw.max())
                    if s_raw.notna().any()
                    else None
                ),
                "min": (
                    float(s.min())
                    if s.notna().any()
                    else None
                ),
                "mean": (
                    float(s.mean())
                    if s.notna().any()
                    else None
                ),
                "std": (
                    float(s.std())
                    if s.notna().any()
                    else None
                ),
                "max": (
                    float(s.max())
                    if s.notna().any()
                    else None
                ),
            }
        )

    return (
        flags.reset_index(drop=True),
        pd.DataFrame(per_band),
        scale_meta,
    )


def exact_duplicates(df: pd.DataFrame, det: dict, cfg: dict) -> pd.DataFrame:
    decimals = cfg["quality"]["exact_duplicate_round_decimals"]
    wl_cols = [det["wavelength_map"][nm] for nm in sorted(det["wavelength_map"])]
    X = df[wl_cols].apply(pd.to_numeric, errors="coerce").round(decimals)
    hashes = pd.util.hash_pandas_object(X, index=False).astype("uint64")
    dup_mask = hashes.duplicated(keep=False)
    if not dup_mask.any():
        return pd.DataFrame(columns=["duplicate_group","row_index","spectrum_hash"])
    tmp = pd.DataFrame({"row_index": df.index[dup_mask], "spectrum_hash": hashes[dup_mask].astype(str).values})
    tmp["duplicate_group"] = pd.factorize(tmp["spectrum_hash"])[0] + 1
    return tmp[["duplicate_group","row_index","spectrum_hash"]].sort_values(["duplicate_group","row_index"])


def near_duplicates(df: pd.DataFrame, det: dict, cfg: dict) -> pd.DataFrame:
    q = cfg["quality"]
    wl_cols = [det["wavelength_map"][nm] for nm in sorted(det["wavelength_map"])]
    X_raw = df[wl_cols].apply(pd.to_numeric, errors="coerce")
    X, _scale_meta = normalize_reflectance_matrix(X_raw, cfg)
    valid = X.notna().all(axis=1)
    Xv = X.loc[valid].to_numpy(dtype=float)
    idx = X.loc[valid].index.to_numpy()

    if len(Xv) == 0:
        return pd.DataFrame(columns=["row_i","row_j","cosine_similarity","rmse"])

    max_rows = int(q.get("max_near_duplicate_rows", 25000))
    if len(Xv) > max_rows:
        rng = np.random.default_rng(q["random_state"])
        take = np.sort(rng.choice(len(Xv), size=max_rows, replace=False))
        Xv = Xv[take]
        idx = idx[take]

    norms = np.linalg.norm(Xv, axis=1, keepdims=True)
    norms[norms == 0] = 1
    Xn = Xv / norms

    nn = NearestNeighbors(
        n_neighbors=min(q["near_duplicate_max_neighbors"] + 1, len(Xn)),
        metric="cosine",
        algorithm="brute",
    )
    nn.fit(Xn)
    distances, neighbors = nn.kneighbors(Xn)

    pairs = {}
    for i in range(len(Xn)):
        for k in range(1, neighbors.shape[1]):
            j = int(neighbors[i, k])
            a, b = sorted((int(idx[i]), int(idx[j])))
            if a == b:
                continue
            cos = 1.0 - float(distances[i, k])
            rmse = float(np.sqrt(np.mean((Xv[i] - Xv[j]) ** 2)))
            if cos >= q["near_duplicate_cosine_threshold"] and rmse <= q["near_duplicate_rmse_threshold"]:
                pairs[(a,b)] = {"row_i":a,"row_j":b,"cosine_similarity":cos,"rmse":rmse}
    return pd.DataFrame(list(pairs.values())).sort_values(["row_i","row_j"]) if pairs else pd.DataFrame(columns=["row_i","row_j","cosine_similarity","rmse"])


def split_integrity(df: pd.DataFrame, det: dict, path: Path) -> tuple[pd.DataFrame, dict]:
    split_col = det["split_col"]
    subject_key = canonical_subject_key(df, det["subject_col"], det["origin_col"])

    if split_col is None:
        name = path.name.lower()
        inferred = None
        if "train" in name:
            inferred = "train"
        elif "valid" in name or re_search(name, r"\bval\b"):
            inferred = "validation"
        elif "test" in name:
            inferred = "test"
        split = pd.Series([inferred] * len(df), index=df.index, dtype="string")
    else:
        split = df[split_col].astype("string").str.lower().str.strip()

    tmp = pd.DataFrame({"row_index":df.index,"subject_key":subject_key,"split":split})
    valid = tmp.dropna(subset=["subject_key","split"])
    membership = valid.groupby("subject_key")["split"].agg(lambda s: sorted(set(s))).reset_index()
    membership["split_count"] = membership["split"].map(len)
    leakage = membership[membership["split_count"] > 1].copy()
    summary = {
        "split_column": split_col,
        "split_counts": tmp["split"].value_counts(dropna=False).to_dict(),
        "subject_keys": int(valid["subject_key"].nunique()),
        "leaking_subject_keys": int(len(leakage)),
    }
    return leakage, summary


def re_search(text: str, pattern: str) -> bool:
    import re
    return re.search(pattern, text) is not None


def distributions(df: pd.DataFrame, det: dict) -> dict[str,pd.DataFrame]:
    result = {}
    mapping = {
        "origin_distribution": det["origin_col"],
        "instrument_distribution": det["instrument_col"],
        "body_site_distribution": det["body_site_col"],
        "sci_sce_distribution": det["specular_col"],
    }
    for name, col in mapping.items():
        if col is None:
            result[name] = pd.DataFrame(columns=["value","n","fraction"])
            continue
        vc = df[col].astype("string").fillna("<NA>").value_counts(dropna=False)
        result[name] = pd.DataFrame({"value":vc.index.astype(str),"n":vc.values})
        result[name]["fraction"] = result[name]["n"] / max(len(df),1)
    return result


def identity_classification(df: pd.DataFrame, det: dict) -> pd.DataFrame:
    subject_key = canonical_subject_key(df, det["subject_col"], det["origin_col"])
    tmp = pd.DataFrame({"row_index":df.index,"subject_key":subject_key})
    if det["subject_col"] is not None:
        raw = df[det["subject_col"]].astype("string").str.strip()
    else:
        raw = pd.Series([pd.NA]*len(df), index=df.index, dtype="string")
    tmp["raw_subject_id"] = raw

    def classify(x):
        if pd.isna(x):
            return "missing"
        s = str(x).lower()
        if any(tok in s for tok in ["avg","average","mean","composite","pooled","group"]):
            return "probable_composite"
        return "probable_individual"

    tmp["identity_class"] = tmp["raw_subject_id"].map(classify)
    counts = tmp.groupby(["subject_key","identity_class"], dropna=False).size().reset_index(name="measurement_count")
    return counts


def missingness_analysis(df: pd.DataFrame, det: dict) -> pd.DataFrame:
    wl_cols = [det["wavelength_map"][nm] for nm in sorted(det["wavelength_map"])]
    X = df[wl_cols].apply(pd.to_numeric, errors="coerce")
    row_missing = X.isna().any(axis=1)
    rows = [{"variable":"overall_any_spectral_missing","level":"ALL","n":len(df),"missing_n":int(row_missing.sum()),"missing_fraction":float(row_missing.mean())}]

    for label, col in [
        ("origin",det["origin_col"]),
        ("instrument",det["instrument_col"]),
        ("body_site",det["body_site_col"]),
        ("sci_sce",det["specular_col"]),
    ]:
        if col is None:
            continue
        groups = df[col].astype("string").fillna("<NA>")
        tmp = pd.DataFrame({"group":groups,"missing":row_missing})
        for level, g in tmp.groupby("group", dropna=False):
            rows.append({
                "variable":label,
                "level":str(level),
                "n":len(g),
                "missing_n":int(g["missing"].sum()),
                "missing_fraction":float(g["missing"].mean()),
            })

    if all(det[k] is not None for k in ["lab_L_col","lab_b_col"]):
        L = pd.to_numeric(df[det["lab_L_col"]], errors="coerce")
        b = pd.to_numeric(df[det["lab_b_col"]], errors="coerce")
        ita = np.degrees(np.arctan2(L - 50.0, b))
        bins = pd.qcut(ita, q=5, duplicates="drop")
        tmp = pd.DataFrame({"group":bins.astype("string"),"missing":row_missing})
        for level, g in tmp.groupby("group", dropna=False):
            rows.append({
                "variable":"ITA_quintile",
                "level":str(level),
                "n":len(g),
                "missing_n":int(g["missing"].sum()),
                "missing_fraction":float(g["missing"].mean()),
            })
    return pd.DataFrame(rows)


def variance_components_and_floor(
    df: pd.DataFrame,
    det: dict,
    cfg: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    wl_cols = [det["wavelength_map"][nm] for nm in sorted(det["wavelength_map"])]
    subject_key = canonical_subject_key(df, det["subject_col"], det["origin_col"])
    meta_cols = [c for c in [det["instrument_col"],det["body_site_col"],det["specular_col"]] if c is not None]

    base = pd.DataFrame({"subject_key":subject_key})
    for c in meta_cols:
        base[c] = df[c].astype("string")
    X_raw = df[wl_cols].apply(pd.to_numeric, errors="coerce")
    X, _scale_meta = normalize_reflectance_matrix(X_raw, cfg)
    base["spectrum_mean"] = X.mean(axis=1)
    base["spectrum_norm"] = np.sqrt((X**2).sum(axis=1))

    component_rows = []
    for col in meta_cols:
        gmeans = base.groupby(col, dropna=False)[["spectrum_mean","spectrum_norm"]].mean()
        component_rows.append({
            "factor":col,
            "levels":int(gmeans.shape[0]),
            "between_level_variance_spectrum_mean":float(gmeans["spectrum_mean"].var(ddof=1)) if len(gmeans)>1 else None,
            "between_level_variance_spectrum_norm":float(gmeans["spectrum_norm"].var(ddof=1)) if len(gmeans)>1 else None,
        })

    # empirical repeatability floor: same subject + same available measurement conditions
    key_cols = ["subject_key"] + meta_cols
    repeated_groups = base.groupby(key_cols, dropna=False).filter(lambda g: len(g) >= 2).index
    floor_rows = []
    if len(repeated_groups):
        sub_raw = df.loc[repeated_groups, wl_cols].apply(
            pd.to_numeric,
            errors="coerce",
        )
        sub, _scale_meta = normalize_reflectance_matrix(sub_raw, cfg)
        keys = base.loc[repeated_groups, key_cols]
        joined = pd.concat([keys, sub], axis=1)
        for key, g in joined.groupby(key_cols, dropna=False):
            if len(g) < 2:
                continue
            arr = g[wl_cols].to_numpy(float)
            center = np.nanmean(arr, axis=0)
            rmses = np.sqrt(np.nanmean((arr - center) ** 2, axis=1))
            floor_rows.append({
                "group_key":json.dumps([str(x) for x in (key if isinstance(key, tuple) else (key,))]),
                "n":len(g),
                "within_group_rmse_mean":float(np.nanmean(rmses)),
                "within_group_rmse_max":float(np.nanmax(rmses)),
            })
    return pd.DataFrame(component_rows), pd.DataFrame(floor_rows)


def generate_report(summary: dict) -> str:
    gates = summary["gates"]
    lines = [
        "# ISSA Stage 3 Metrology and Provenance Report",
        "",
        f"Status: **{summary['status']}**",
        "",
        "## Canonical source",
        f"- Path: `{summary.get('canonical_path','')}`",
        f"- Rows: {summary.get('canonical_rows')}",
        f"- Columns: {summary.get('canonical_columns')}",
        "",
        "## Hard gates",
    ]
    for gate, value in gates.items():
        lines.append(f"- {gate}: **{'PASS' if value else 'FAIL'}**")
    lines.extend([
        "",
        "## Key findings",
        f"- Wavelength exact match: {summary.get('wavelength_exact_match')}",
        f"- Reflectance source scale: {summary.get('reflectance_scale')}",
        f"- Normalization factor: {summary.get('normalization_factor')}",
        f"- Admissible rows: {summary.get('admissible_rows')}",
        f"- Admissible fraction: {summary.get('admissible_fraction')}",
        f"- Unique subject keys: {summary.get('unique_subject_keys')}",
        f"- Expected subject/composite IDs: {summary.get('expected_subject_or_composite_ids')}",
        f"- Split leakage subject keys: {summary.get('split_leakage_subject_keys')}",
        f"- Basic inadmissible rows: {summary.get('basic_inadmissible_rows')}",
        f"- Exact duplicate rows: {summary.get('exact_duplicate_rows')}",
        f"- Near-duplicate pairs: {summary.get('near_duplicate_pairs')}",
        "",
        "## Interpretation discipline",
        "- Pooling across instruments, origins, body sites, or SCI/SCE conventions is not permitted unless the emitted distributions and variance analyses support it.",
        "- The empirical repeatability floor is descriptive unless genuinely repeated comparable measurements exist.",
        "- Composite identities remain provisional unless their provenance is resolved from source documentation.",
        "- A closed Stage 3 certifies data admissibility and provenance rules; it does not certify the later physics claims.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--canonical-file", type=Path, default=None)
    args = parser.parse_args()

    cfg = load_config()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    source_inventory = discover_files(args.data_root, cfg)
    safe_write_table(source_inventory, out/"source_inventory")

    schema_rows = []
    candidate_rows = []
    loaded = {}
    detected = {}

    for rec in source_inventory.to_dict("records"):
        path = Path(rec["path"])
        df, meta = inspect_schema(path)
        schema_rows.append(meta)
        if df is None:
            continue
        det = detect_columns(df, cfg)
        loaded[str(path)] = df
        detected[str(path)] = det
        candidate_rows.append(score_candidate(path, df, det, cfg))

    schema_inventory = pd.DataFrame(schema_rows)
    candidate_inventory = pd.DataFrame(candidate_rows)
    safe_write_table(schema_inventory, out/"schema_inventory")
    safe_write_table(candidate_inventory, out/"candidate_inventory")

    if args.canonical_file:
        canonical_path = args.canonical_file.resolve()
        if str(canonical_path) not in loaded:
            df = read_table(canonical_path)
            det = detect_columns(df, cfg)
        else:
            df = loaded[str(canonical_path)]
            det = detected[str(canonical_path)]
    else:
        if candidate_inventory.empty:
            raise RuntimeError("No readable ISSA candidate tables found.")
        canonical_rec = candidate_inventory.sort_values("candidate_score", ascending=False).iloc[0]
        canonical_path = Path(canonical_rec["path"])
        df = loaded[str(canonical_path)]
        det = detected[str(canonical_path)]

    provenance = pd.DataFrame([{
        "canonical_path":str(canonical_path),
        "sha256":sha256_file(canonical_path),
        "rows":len(df),
        "columns":len(df.columns),
        "subject_col":det["subject_col"],
        "origin_col":det["origin_col"],
        "instrument_col":det["instrument_col"],
        "body_site_col":det["body_site_col"],
        "specular_col":det["specular_col"],
        "split_col":det["split_col"],
        "lab_L_col":det["lab_L_col"],
        "lab_a_col":det["lab_a_col"],
        "lab_b_col":det["lab_b_col"],
        "wavelength_count":len(det["wavelength_map"]),
    }])
    safe_write_table(provenance, out/"provenance_inventory")

    wl_df, wl_summary = wavelength_integrity(df, det, cfg)
    safe_write_table(wl_df, out/"wavelength_integrity")

    identity_df = identity_classification(df, det)
    safe_write_table(identity_df, out/"subject_composite_classification")

    quality_flags, band_quality, scale_meta = quality_audit(
        df,
        det,
        cfg,
    )
    safe_write_table(
        quality_flags,
        out/"spectral_quality_flags",
    )
    safe_write_table(
        band_quality,
        out/"band_quality_summary",
    )

    pd.DataFrame([scale_meta]).to_csv(
        out/"reflectance_scale_resolution.csv",
        index=False,
    )
    try:
        pd.DataFrame([scale_meta]).to_parquet(
            out/"reflectance_scale_resolution.parquet",
            index=False,
        )
    except Exception:
        pass

    exact = exact_duplicates(df, det, cfg)
    safe_write_table(exact, out/"exact_duplicate_groups")

    near = near_duplicates(df, det, cfg)
    safe_write_table(near, out/"near_duplicate_groups")

    leakage, split_summary = split_integrity(df, det, canonical_path)
    safe_write_table(leakage, out/"split_integrity")

    missingness = missingness_analysis(df, det)
    safe_write_table(missingness, out/"missingness_analysis")

    for name, table in distributions(df, det).items():
        safe_write_table(table, out/name)

    variance_components, instrument_floor = variance_components_and_floor(
        df,
        det,
        cfg,
    )
    safe_write_table(variance_components, out/"variance_components")
    safe_write_table(instrument_floor, out/"instrument_floor")

    subject_key = canonical_subject_key(df, det["subject_col"], det["origin_col"])
    admissible = quality_flags.copy()
    admissible["subject_key"] = subject_key.astype("string").values
    admissible["admissible"] = admissible["admissible_basic"] & admissible["subject_key"].notna()
    safe_write_table(admissible, out/"admissible_measurements")

    exp = cfg["expected"]
    unique_subjects = int(subject_key.dropna().nunique())

    admissible_rows = int(
        quality_flags["admissible_basic"].sum()
    )
    basic_inadmissible_rows = int(
        (~quality_flags["admissible_basic"]).sum()
    )
    admissible_fraction = (
        admissible_rows / len(df)
        if len(df)
        else 0.0
    )

    minimum_admissible_fraction = float(
        cfg["quality"].get(
            "minimum_admissible_fraction",
            0.95,
        )
    )

    gates = {
        "source_hash_present": bool(sha256_file(canonical_path)),
        "canonical_row_count_match": (
            len(df) == exp["canonical_rows"]
        ),
        "wavelength_grid_exact": wl_summary["exact_match"],
        "subject_key_present": det["subject_col"] is not None,
        "subject_count_reconciled": (
            unique_subjects
            == exp["subject_or_composite_ids"]
        ),
        "split_leakage_zero": (
            split_summary["leaking_subject_keys"] == 0
        ),
        "reflectance_scale_resolved": (
            scale_meta["reflectance_scale"]
            in {"fraction", "percent"}
        ),
        "nonzero_admissible_rows": admissible_rows > 0,
        "all_rows_not_rejected": (
            basic_inadmissible_rows < len(df)
        ),
        "admissible_fraction_nontrivial": (
            admissible_fraction
            >= minimum_admissible_fraction
        ),
    }

    hard_gate_map = {
        "canonical_row_count_match": not cfg["closure"]["allow_row_count_mismatch"],
        "wavelength_grid_exact": not cfg["closure"]["allow_wavelength_mismatch"],
        "split_leakage_zero": not cfg["closure"]["allow_split_leakage"],
        "source_hash_present": not cfg["closure"]["allow_unhashed_sources"],
        "subject_key_present": (
            not cfg["closure"]["allow_missing_subject_key"]
        ),
        "reflectance_scale_resolved": True,
        "nonzero_admissible_rows": True,
        "all_rows_not_rejected": True,
        "admissible_fraction_nontrivial": True,
    }
    hard_fail = [name for name, required in hard_gate_map.items() if required and not gates[name]]
    status = "CLOSED" if not hard_fail else "OPEN_FAILED_GATES"

    summary = {
        "stage":3,
        "name":"issa_metrology_and_provenance_closure",
        "status":status,
        "canonical_path":str(canonical_path),
        "canonical_sha256":sha256_file(canonical_path),
        "canonical_rows":len(df),
        "canonical_columns":len(df.columns),
        "wavelength_exact_match":wl_summary["exact_match"],
        "unique_subject_keys":unique_subjects,
        "expected_subject_or_composite_ids":exp["subject_or_composite_ids"],
        "split_leakage_subject_keys":split_summary["leaking_subject_keys"],
        "reflectance_scale": scale_meta["reflectance_scale"],
        "normalization_applied": scale_meta["normalization_applied"],
        "normalization_factor": scale_meta["normalization_factor"],
        "raw_reflectance_min": scale_meta["raw_min"],
        "raw_reflectance_median": scale_meta["raw_median"],
        "raw_reflectance_max": scale_meta["raw_max"],
        "normalized_reflectance_min": scale_meta["normalized_min"],
        "normalized_reflectance_median": scale_meta["normalized_median"],
        "normalized_reflectance_max": scale_meta["normalized_max"],
        "admissible_rows": admissible_rows,
        "basic_inadmissible_rows": basic_inadmissible_rows,
        "admissible_fraction": admissible_fraction,
        "minimum_admissible_fraction": minimum_admissible_fraction,
        "exact_duplicate_rows":int(len(exact)),
        "near_duplicate_pairs":int(len(near)),
        "hard_failed_gates":hard_fail,
        "gates":gates,
        "next_stage":{"id":4,"name":"measurand_stability_and_biological_nuisance_decomposition"} if status=="CLOSED" else None,
    }

    (out/"stage3_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (out/"metrology_report.md").write_text(generate_report(summary), encoding="utf-8")
    (out/"STAGE_3_CLOSED.yaml").write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")

    # manifest after all outputs
    manifest = []
    for path in sorted(out.iterdir()):
        if path.is_file():
            manifest.append({"file":path.name,"sha256":sha256_file(path),"bytes":path.stat().st_size})
    pd.DataFrame(manifest).to_csv(out/"sha256_manifest.csv", index=False)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if status == "CLOSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
