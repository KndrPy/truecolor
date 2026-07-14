from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.decomposition import PCA
from sklearn.model_selection import GroupKFold


def norm_name(value):
    value = str(value).strip().lower()
    value = re.sub(r"[\s\-\./\\]+", "_", value)
    return re.sub(r"[^a-z0-9_*]+", "", value).strip("_")


def find_col(columns, candidates):
    mapping = {norm_name(c): str(c) for c in columns}
    for candidate in candidates:
        key = norm_name(candidate)
        if key in mapping:
            return mapping[key]
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def to_native(value):
    if isinstance(value, dict):
        return {str(k): to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_native(v) for v in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def write_table(df, base):
    df.to_csv(base.with_suffix(".csv"), index=False)
    try:
        df.to_parquet(base.with_suffix(".parquet"), index=False)
    except Exception:
        pass


def resolve_wavelength_columns(df, cfg):
    start = int(cfg["expected"]["wavelength_start_nm"])
    end = int(cfg["expected"]["wavelength_end_nm"])
    step = int(cfg["expected"]["wavelength_step_nm"])
    expected = list(range(start, end + step, step))
    prefix = cfg["reflectance"]["prefix"]

    resolved = []
    missing = []

    for wavelength in expected:
        column = f"{prefix}{wavelength}"
        if column in df.columns:
            resolved.append((wavelength, column))
        else:
            missing.append(wavelength)

    return expected, resolved, missing


def normalize_reflectance(X_raw, cfg):
    values = X_raw.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]

    if finite.size == 0:
        raise RuntimeError("No finite reflectance values.")

    raw_min = float(np.min(finite))
    raw_median = float(np.median(finite))
    raw_max = float(np.max(finite))

    mode = str(cfg["reflectance"]["scale"]).lower()

    if mode == "auto":
        scale = (
            "percent"
            if raw_max > float(
                cfg["reflectance"]["percent_detection_threshold"]
            )
            else "fraction"
        )
    elif mode in {"percent", "fraction"}:
        scale = mode
    else:
        raise RuntimeError(f"Unsupported reflectance scale: {mode}")

    factor = 0.01 if scale == "percent" else 1.0
    X = X_raw.astype(float) * factor

    return X, {
        "source_scale": scale,
        "normalization_factor": factor,
        "raw_min": raw_min,
        "raw_median": raw_median,
        "raw_max": raw_max,
        "normalized_min": float(np.nanmin(X.to_numpy(float))),
        "normalized_median": float(np.nanmedian(X.to_numpy(float))),
        "normalized_max": float(np.nanmax(X.to_numpy(float))),
    }


def fit_pca(X, n_components):
    n = min(int(n_components), X.shape[0], X.shape[1])
    model = PCA(n_components=n, svd_solver="full")
    model.fit(X)
    return model


def reconstruct(model, X_centered, n_components):
    k = min(int(n_components), model.components_.shape[0])
    scores = X_centered @ model.components_[:k].T
    return scores @ model.components_[:k]


def row_rmse(actual, reconstructed):
    return np.sqrt(np.mean((actual - reconstructed) ** 2, axis=1))


def aggregate_metrics(results):
    rows = []

    group_cols = ["representation", "components"]

    for keys, group in results.groupby(group_cols, dropna=False):
        representation, components = keys
        rows.append({
            "representation": representation,
            "components": int(components),
            "rows": int(len(group)),
            "subjects": int(group["subject_id"].nunique()),
            "folds": int(group["fold"].nunique()),
            "mean_rmse": float(group["rmse"].mean()),
            "median_rmse": float(group["rmse"].median()),
            "p90_rmse": float(group["rmse"].quantile(0.90)),
            "p95_rmse": float(group["rmse"].quantile(0.95)),
            "p975_rmse": float(group["rmse"].quantile(0.975)),
            "p99_rmse": float(group["rmse"].quantile(0.99)),
            "max_rmse": float(group["rmse"].max()),
            "fold_mean_std": float(
                group.groupby("fold")["rmse"].mean().std(ddof=0)
            ),
        })

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-file", type=Path, required=True)
    parser.add_argument("--stage5-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    cfg = yaml.safe_load(
        Path(__file__).with_name("config.yaml").read_text(encoding="utf-8")
    )

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    stage5 = json.loads(args.stage5_summary.read_text(encoding="utf-8"))
    allowed = set(cfg["closure"]["admissible_stage5_status"])

    if stage5.get("status") not in allowed:
        raise RuntimeError(
            f"Stage 5 status not admissible: {stage5.get('status')}"
        )

    if (
        cfg["closure"]["require_stage5_body_site_conditioning"]
        and stage5.get("analysis_unit")
        != "body_location_code_conditioned_spectrum"
    ):
        raise RuntimeError("Stage 5 body-site conditioning was not inherited.")

    df = pd.read_parquet(args.canonical_file)

    subject_col = find_col(df.columns, cfg["columns"]["subject"])
    body_col = find_col(df.columns, cfg["columns"]["body_site"])
    origin_col = find_col(df.columns, cfg["columns"]["origin"])
    instrument_col = find_col(df.columns, cfg["columns"]["instrument"])
    specular_col = find_col(df.columns, cfg["columns"]["specular"])

    expected_wavelengths, resolved, missing_wavelengths = (
        resolve_wavelength_columns(df, cfg)
    )

    missing_required = []
    if subject_col is None:
        missing_required.append("subject")
    if body_col is None:
        missing_required.append("body_site")
    if missing_wavelengths:
        missing_required.append("wavelengths")

    resolved_columns = {
        "subject": subject_col,
        "body_site": body_col,
        "origin": origin_col,
        "instrument": instrument_col,
        "specular": specular_col,
        "reflectance_columns": [column for _, column in resolved],
    }

    (out / "resolved_columns.json").write_text(
        json.dumps(resolved_columns, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if missing_required:
        summary = {
            "stage": 6,
            "name": "site_conditioned_spectral_representation_and_validation",
            "status": "OPEN_FAILED_GATES",
            "missing_required": missing_required,
            "missing_wavelengths": missing_wavelengths,
            "gates": {"required_inputs_resolved": False},
        }
        (out / "stage6_summary.json").write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2))
        return 2

    wavelengths = [w for w, _ in resolved]
    spectral_columns = [c for _, c in resolved]

    X_raw = df[spectral_columns].apply(pd.to_numeric, errors="coerce")
    X, scale_meta = normalize_reflectance(X_raw, cfg)

    physical_min = float(cfg["reflectance"]["physical_min"])
    physical_max = float(cfg["reflectance"]["physical_max"])

    complete = X.notna().all(axis=1)
    physical = ((X >= physical_min) & (X <= physical_max)).all(axis=1)
    admissible = complete & physical

    analysis = df.loc[admissible].copy()
    X_adm = X.loc[admissible].copy()

    analysis["_subject"] = analysis[subject_col].astype("string")
    analysis["_site"] = analysis[body_col].astype("string")
    analysis["_row_index"] = analysis.index

    groups = analysis["_subject"].to_numpy()
    unique_subjects = np.unique(groups)

    folds = int(cfg["validation"]["folds"])
    if len(unique_subjects) < folds:
        raise RuntimeError("Not enough subjects for requested folds.")

    splitter = GroupKFold(n_splits=folds)

    components = [
        int(k) for k in cfg["validation"]["components"]
    ]

    min_train_rows = int(
        cfg["validation"]["minimum_train_rows_per_site"]
    )
    min_test_rows = int(
        cfg["validation"]["minimum_test_rows_per_site"]
    )
    min_train_subjects = int(
        cfg["validation"]["minimum_train_subjects_per_site"]
    )

    fold_rows = []
    leakage_rows = []
    site_support_rows = []

    max_components = max(components)

    for fold, (train_pos, test_pos) in enumerate(
        splitter.split(analysis, groups=groups),
        start=1,
    ):
        train_index = analysis.index[train_pos]
        test_index = analysis.index[test_pos]

        train_subjects = set(
            analysis.loc[train_index, "_subject"].astype(str)
        )
        test_subjects = set(
            analysis.loc[test_index, "_subject"].astype(str)
        )
        overlap = train_subjects & test_subjects

        leakage_rows.append({
            "fold": fold,
            "train_subjects": len(train_subjects),
            "test_subjects": len(test_subjects),
            "overlap_subjects": len(overlap),
        })

        X_train = X_adm.loc[train_index].to_numpy(float)
        X_test = X_adm.loc[test_index].to_numpy(float)

        site_train = analysis.loc[train_index, "_site"].astype(str)
        site_test = analysis.loc[test_index, "_site"].astype(str)
        subject_test = analysis.loc[test_index, "_subject"].astype(str)

        global_mean = X_train.mean(axis=0)
        global_train_centered = X_train - global_mean
        global_model = fit_pca(
            global_train_centered,
            max_components,
        )

        train_frame = pd.DataFrame(
            X_train,
            index=train_index,
            columns=spectral_columns,
        )
        train_frame["_site"] = site_train.to_numpy()

        site_means = (
            train_frame.groupby("_site")[spectral_columns]
            .mean()
        )

        train_site_mean_matrix = np.vstack([
            site_means.loc[site].to_numpy(float)
            for site in site_train
        ])
        site_centered_train = X_train - train_site_mean_matrix

        shared_site_centered_model = fit_pca(
            site_centered_train,
            max_components,
        )

        site_models = {}
        train_site_counts = {}

        for site, site_idx in analysis.loc[train_index].groupby("_site").groups.items():
            site_idx = pd.Index(site_idx)
            site_subjects = analysis.loc[site_idx, "_subject"].nunique()
            site_rows = len(site_idx)

            train_site_counts[str(site)] = {
                "rows": int(site_rows),
                "subjects": int(site_subjects),
            }

            if (
                site_rows >= min_train_rows
                and site_subjects >= min_train_subjects
            ):
                Xi = X_adm.loc[site_idx].to_numpy(float)
                mean_i = Xi.mean(axis=0)
                model_i = fit_pca(
                    Xi - mean_i,
                    max_components,
                )
                site_models[str(site)] = {
                    "mean": mean_i,
                    "model": model_i,
                }

        for site in sorted(set(site_test)):
            test_site_mask = site_test == site
            site_positions = np.flatnonzero(test_site_mask.to_numpy())
            test_rows = len(site_positions)

            site_support_rows.append({
                "fold": fold,
                "body_site": site,
                "train_rows": train_site_counts.get(site, {}).get("rows", 0),
                "train_subjects": train_site_counts.get(site, {}).get("subjects", 0),
                "test_rows": int(test_rows),
                "site_specific_model_available": site in site_models,
                "test_support_sufficient": test_rows >= min_test_rows,
            })

            Xi_test = X_test[site_positions]
            row_indices = test_index[site_positions]
            subject_ids = subject_test.iloc[site_positions].to_numpy()

            for k in components:
                # Representation 1: shared global basis.
                centered = Xi_test - global_mean
                reconstructed_centered = reconstruct(
                    global_model,
                    centered,
                    k,
                )
                reconstructed = reconstructed_centered + global_mean
                rmse = row_rmse(Xi_test, reconstructed)

                for row_index, subject_id, error in zip(
                    row_indices,
                    subject_ids,
                    rmse,
                ):
                    fold_rows.append({
                        "fold": fold,
                        "row_index": int(row_index),
                        "subject_id": str(subject_id),
                        "body_site": str(site),
                        "representation": "shared_global",
                        "components": k,
                        "rmse": float(error),
                        "fallback_used": False,
                    })

                # Representation 2: shared basis, site-specific centering.
                if site in site_means.index:
                    site_mean = site_means.loc[site].to_numpy(float)
                    centered = Xi_test - site_mean
                    reconstructed_centered = reconstruct(
                        shared_site_centered_model,
                        centered,
                        k,
                    )
                    reconstructed = reconstructed_centered + site_mean
                    fallback = False
                else:
                    centered = Xi_test - global_mean
                    reconstructed_centered = reconstruct(
                        shared_site_centered_model,
                        centered,
                        k,
                    )
                    reconstructed = reconstructed_centered + global_mean
                    fallback = True

                rmse = row_rmse(Xi_test, reconstructed)

                for row_index, subject_id, error in zip(
                    row_indices,
                    subject_ids,
                    rmse,
                ):
                    fold_rows.append({
                        "fold": fold,
                        "row_index": int(row_index),
                        "subject_id": str(subject_id),
                        "body_site": str(site),
                        "representation": "shared_basis_site_centered",
                        "components": k,
                        "rmse": float(error),
                        "fallback_used": fallback,
                    })

                # Representation 3: site-specific basis.
                if site in site_models:
                    model_info = site_models[site]
                    site_mean = model_info["mean"]
                    model_i = model_info["model"]
                    centered = Xi_test - site_mean
                    reconstructed_centered = reconstruct(
                        model_i,
                        centered,
                        k,
                    )
                    reconstructed = reconstructed_centered + site_mean
                    fallback = False
                else:
                    centered = Xi_test - global_mean
                    reconstructed_centered = reconstruct(
                        global_model,
                        centered,
                        k,
                    )
                    reconstructed = reconstructed_centered + global_mean
                    fallback = True

                rmse = row_rmse(Xi_test, reconstructed)

                for row_index, subject_id, error in zip(
                    row_indices,
                    subject_ids,
                    rmse,
                ):
                    fold_rows.append({
                        "fold": fold,
                        "row_index": int(row_index),
                        "subject_id": str(subject_id),
                        "body_site": str(site),
                        "representation": "site_specific_basis",
                        "components": k,
                        "rmse": float(error),
                        "fallback_used": fallback,
                    })

    row_results = pd.DataFrame(fold_rows)
    leakage = pd.DataFrame(leakage_rows)
    site_support = pd.DataFrame(site_support_rows)

    aggregate = aggregate_metrics(row_results)

    site_aggregate = (
        row_results.groupby(
            ["body_site", "representation", "components"],
            as_index=False,
        )
        .agg(
            rows=("rmse", "size"),
            subjects=("subject_id", "nunique"),
            mean_rmse=("rmse", "mean"),
            median_rmse=("rmse", "median"),
            p95_rmse=("rmse", lambda s: s.quantile(0.95)),
            p975_rmse=("rmse", lambda s: s.quantile(0.975)),
            p99_rmse=("rmse", lambda s: s.quantile(0.99)),
            max_rmse=("rmse", "max"),
            fallback_fraction=("fallback_used", "mean"),
        )
    )

    write_table(row_results, out / "fold_reconstruction_errors")
    write_table(aggregate, out / "aggregate_representation_performance")
    write_table(site_aggregate, out / "site_representation_performance")
    write_table(leakage, out / "subject_leakage_audit")
    write_table(site_support, out / "site_fold_support")

    comparison_rows = []

    for k in components:
        subset = aggregate[aggregate["components"] == k].set_index(
            "representation"
        )

        if not {
            "shared_global",
            "shared_basis_site_centered",
            "site_specific_basis",
        }.issubset(subset.index):
            continue

        global_rmse = float(subset.loc["shared_global", "mean_rmse"])
        centered_rmse = float(
            subset.loc["shared_basis_site_centered", "mean_rmse"]
        )
        specific_rmse = float(
            subset.loc["site_specific_basis", "mean_rmse"]
        )

        comparison_rows.append({
            "components": k,
            "shared_global_mean_rmse": global_rmse,
            "shared_site_centered_mean_rmse": centered_rmse,
            "site_specific_mean_rmse": specific_rmse,
            "site_centering_relative_improvement": (
                (global_rmse - centered_rmse) / global_rmse
                if global_rmse > 0 else None
            ),
            "site_specific_relative_improvement_over_centered": (
                (centered_rmse - specific_rmse) / centered_rmse
                if centered_rmse > 0 else None
            ),
        })

    comparison = pd.DataFrame(comparison_rows)
    write_table(comparison, out / "representation_comparison")

    compact_k = 3

    compact_comparison = comparison.loc[
        comparison["components"] == compact_k
    ]

    if compact_comparison.empty:
        raise RuntimeError(
            "Registered compact component count missing."
        )

    preferred_row = compact_comparison.iloc[0]

    centered_improvement = float(
        preferred_row["site_centering_relative_improvement"]
    )
    specific_improvement = float(
        preferred_row[
            "site_specific_relative_improvement_over_centered"
        ]
    )

    centered_material = centered_improvement >= float(
        cfg["validation"][
            "site_centering_material_improvement_fraction"
        ]
    )
    specific_material = specific_improvement >= float(
        cfg["validation"][
            "site_specific_material_improvement_fraction"
        ]
    )

    best_representation = (
        "site_specific_basis"
        if specific_material
        else "shared_basis_site_centered"
        if centered_material
        else "shared_global"
    )

    preferred_metric = aggregate[
        (aggregate["representation"] == best_representation)
        & (aggregate["components"] == compact_k)
    ].iloc[0]

    best_evaluated_metric = (
        aggregate[
            aggregate["representation"]
            == best_representation
        ]
        .sort_values(
            ["mean_rmse", "components"],
            ascending=[True, True],
        )
        .iloc[0]
    )


    normalized_max = float(scale_meta["normalized_max"])
    normalized_min = float(scale_meta["normalized_min"])
    reflectance_range = normalized_max - normalized_min

    preferred_mean_rmse = float(
        preferred_metric["mean_rmse"]
    )
    preferred_p95_rmse = float(
        preferred_metric["p95_rmse"]
    )
    preferred_p975_rmse = float(
        preferred_metric["p975_rmse"]
    )
    preferred_p99_rmse = float(
        preferred_metric["p99_rmse"]
    )
    preferred_max_rmse = float(
        preferred_metric["max_rmse"]
    )

    relative_rmse = (
        preferred_mean_rmse / reflectance_range
        if reflectance_range > 0
        else None
    )

    p95_rmse_fraction = (
        preferred_p95_rmse / reflectance_range
        if reflectance_range > 0
        else None
    )

    p975_rmse_fraction = (
        preferred_p975_rmse / reflectance_range
        if reflectance_range > 0
        else None
    )

    p99_rmse_fraction = (
        preferred_p99_rmse / reflectance_range
        if reflectance_range > 0
        else None
    )

    max_rmse_fraction = (
        preferred_max_rmse / reflectance_range
        if reflectance_range > 0
        else None
    )

    relative_fold_std = (
        float(preferred_metric["fold_mean_std"])
        / float(preferred_metric["mean_rmse"])
        if float(preferred_metric["mean_rmse"]) > 0
        else None
    )

    all_test_rows_covered = (
        row_results[
            (row_results["representation"] == best_representation)
            & (row_results["components"] == compact_k)
        ]["row_index"].nunique()
        == len(analysis)
    )

    no_subject_leakage = int(leakage["overlap_subjects"].sum()) == 0

    gates = {
        "stage5_status_admissible": stage5.get("status") in allowed,
        "stage5_body_site_conditioning_inherited": (
            stage5.get("analysis_unit")
            == "body_location_code_conditioned_spectrum"
        ),
        "canonical_row_count_match": (
            len(df) == int(cfg["expected"]["canonical_rows"])
        ),
        "subject_count_match": (
            analysis["_subject"].nunique()
            == int(cfg["expected"]["subject_ids"])
        ),
        "body_site_level_count_match": (
            analysis["_site"].nunique()
            == int(cfg["expected"]["body_site_levels"])
        ),
        "wavelength_grid_exact": wavelengths == expected_wavelengths,
        "reflectance_scale_resolved": (
            scale_meta["source_scale"] in {"percent", "fraction"}
        ),
        "nonzero_admissible_rows": len(analysis) > 0,
        "subject_disjoint_folds": no_subject_leakage,
        "all_test_rows_covered": all_test_rows_covered,
        "all_representations_evaluated": (
            row_results["representation"].nunique() == 3
        ),
        "all_component_counts_evaluated": (
            sorted(row_results["components"].unique().tolist())
            == sorted(components)
        ),
        "preferred_representation_rmse_bounded": (
            relative_rmse
            <= float(
                cfg["validation"][
                    "maximum_rmse_fraction_of_reflectance_range"
                ]
            )
        ),
        "fold_stability_acceptable": (
            relative_fold_std
            <= float(
                cfg["validation"]["maximum_relative_fold_std"]
            )
        ),
        "tail_metrics_computed": all(
            np.isfinite(value)
            for value in [
                preferred_p95_rmse,
                preferred_p975_rmse,
                preferred_p99_rmse,
                preferred_max_rmse,
                p95_rmse_fraction,
                p975_rmse_fraction,
                p99_rmse_fraction,
                max_rmse_fraction,
            ]
        ),
        "tail_quantiles_monotonic": (
            preferred_mean_rmse
            <= preferred_p95_rmse
            <= preferred_p975_rmse
            <= preferred_p99_rmse
            <= preferred_max_rmse
        ),
    }

    status = (
        "CLOSED_WITH_SCOPE_LIMITATION"
        if all(gates.values())
        else "OPEN_FAILED_GATES"
    )

    summary = {
        "stage": 6,
        "name": "site_conditioned_spectral_representation_and_validation",
        "status": status,
        "canonical_path": str(args.canonical_file),
        "canonical_sha256": sha256_file(args.canonical_file),
        "canonical_rows": len(df),
        "admissible_rows": len(analysis),
        "subject_count": int(analysis["_subject"].nunique()),
        "body_site_levels": int(analysis["_site"].nunique()),
        "wavelength_count": len(wavelengths),
        "reflectance_scale": scale_meta,
        "folds": folds,
        "components_evaluated": components,
        "component_selection_policy": (
            "registered_compact_representation"
        ),
        "registered_compact_component_count": compact_k,
        "best_evaluated_component_count": int(
            best_evaluated_metric["components"]
        ),
        "best_evaluated_mean_rmse": float(
            best_evaluated_metric["mean_rmse"]
        ),
        "site_centering_relative_improvement_at_3_components": (
            centered_improvement
        ),
        "site_specific_relative_improvement_over_centered_at_3_components": (
            specific_improvement
        ),
        "site_centering_material": bool(centered_material),
        "site_specific_basis_material": bool(specific_material),
        "preferred_representation": best_representation,
        "preferred_mean_rmse": preferred_mean_rmse,
        "preferred_p95_rmse": preferred_p95_rmse,
        "preferred_p975_rmse": preferred_p975_rmse,
        "preferred_p99_rmse": preferred_p99_rmse,
        "preferred_max_rmse": preferred_max_rmse,
        "preferred_fold_mean_std": float(
            preferred_metric["fold_mean_std"]
        ),
        "preferred_rmse_fraction_of_reflectance_range": (
            relative_rmse
        ),
        "preferred_p95_rmse_fraction_of_reflectance_range": (
            p95_rmse_fraction
        ),
        "preferred_p975_rmse_fraction_of_reflectance_range": (
            p975_rmse_fraction
        ),
        "preferred_p99_rmse_fraction_of_reflectance_range": (
            p99_rmse_fraction
        ),
        "preferred_max_rmse_fraction_of_reflectance_range": (
            max_rmse_fraction
        ),
        "preferred_p95_to_mean_ratio": (
            preferred_p95_rmse / preferred_mean_rmse
            if preferred_mean_rmse > 0
            else None
        ),
        "preferred_p975_to_mean_ratio": (
            preferred_p975_rmse / preferred_mean_rmse
            if preferred_mean_rmse > 0
            else None
        ),
        "preferred_p99_to_mean_ratio": (
            preferred_p99_rmse / preferred_mean_rmse
            if preferred_mean_rmse > 0
            else None
        ),
        "preferred_relative_fold_std": relative_fold_std,
        "subject_leakage_count": int(
            leakage["overlap_subjects"].sum()
        ),
        "global_subject_tone_scalar_admissible": False,
        "analysis_unit": "body_location_code_conditioned_spectrum",
        "inherited_scope_limitations": (
            stage5.get("inherited_scope_limitations", [])
        ),
        "gates": gates,
        "hard_failed_gates": [
            key for key, value in gates.items() if not value
        ],
        "next_stage": {
            "id": 7,
            "name": "dominant_axis_interpretation_and_wavelength_attribution",
            "inherited_restrictions": (
                stage5.get("next_stage", {})
                .get("inherited_restrictions", [])
            ),
        } if all(gates.values()) else None,
    }

    summary = to_native(summary)

    (out / "stage6_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    (out / "STAGE_6_CLOSED.yaml").write_text(
        yaml.safe_dump(summary, sort_keys=False),
        encoding="utf-8",
    )

    report = [
        "# ISSA Stage 6 Site-Conditioned Representation Validation",
        "",
        f"Status: **{status}**",
        "",
        f"- Folds: {folds}",
        f"- Subjects: {summary['subject_count']}",
        f"- Admissible rows: {summary['admissible_rows']}",
        f"- Preferred representation family: {best_representation}",
        f"- Registered compact components: {compact_k}",
        f"- Best evaluated RMSE components: {summary['best_evaluated_component_count']}",
        f"- Best evaluated mean RMSE: {summary['best_evaluated_mean_rmse']}",
        f"- Preferred mean RMSE: {summary['preferred_mean_rmse']}",
        f"- Preferred p95 RMSE: {summary['preferred_p95_rmse']}",
        f"- Preferred p97.5 RMSE: {summary['preferred_p975_rmse']}",
        f"- Preferred p99 RMSE: {summary['preferred_p99_rmse']}",
        f"- Preferred maximum RMSE: {summary['preferred_max_rmse']}",
        f"- Preferred p99/mean ratio: {summary['preferred_p99_to_mean_ratio']}",
        f"- Site-centering relative improvement: {centered_improvement}",
        f"- Site-specific relative improvement over centering: {specific_improvement}",
        f"- Subject leakage count: {summary['subject_leakage_count']}",
        "",
        "## Adjudication",
        "",
        "- Validation is subject-disjoint.",
        "- Representation selection is based on held-out reconstruction.",
        "- Body-site conditioning remains mandatory.",
        "- The dominant axis remains biologically uninterpreted.",
        "- A global subject-level skin-tone scalar remains prohibited.",
    ]

    (out / "site_conditioned_validation_report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    manifest = []
    for path in sorted(out.iterdir()):
        if path.is_file():
            manifest.append({
                "file": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            })

    pd.DataFrame(manifest).to_csv(
        out / "sha256_manifest.csv",
        index=False,
    )

    print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if status == "CLOSED_WITH_SCOPE_LIMITATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
