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
        candidate = f"{prefix}{wavelength}"
        if candidate in df.columns:
            resolved.append((wavelength, candidate))
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
        scale = "percent" if raw_max > float(cfg["reflectance"]["percent_detection_threshold"]) else "fraction"
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


def eigen_metrics(eigenvalues, variance_targets):
    ev = np.asarray(eigenvalues, dtype=float)
    ev = ev[np.isfinite(ev)]
    ev = np.clip(ev, 0.0, None)
    total = float(ev.sum())
    if total <= 0:
        return {
            "participation_ratio": None,
            "shannon_effective_rank": None,
            "components_for_targets": {str(t): None for t in variance_targets},
        }
    p = ev / total
    nonzero = p[p > 0]
    participation = float(1.0 / np.sum(p ** 2))
    shannon = float(np.exp(-np.sum(nonzero * np.log(nonzero))))
    cumulative = np.cumsum(p)
    counts = {}
    for target in variance_targets:
        counts[str(target)] = int(np.searchsorted(cumulative, float(target), side="left") + 1)
    return {
        "participation_ratio": participation,
        "shannon_effective_rank": shannon,
        "components_for_targets": counts,
    }


def fit_geometry(X, variance_targets, max_components):
    n_components = min(int(max_components), X.shape[0], X.shape[1])
    pca = PCA(n_components=n_components, svd_solver="full")
    pca.fit(X)
    metrics = eigen_metrics(pca.explained_variance_, variance_targets)
    return pca, metrics


def derivative_metrics(X, wavelengths):
    arr = X.to_numpy(float)
    wl = np.asarray(wavelengths, dtype=float)
    first = np.diff(arr, axis=1) / np.diff(wl)[None, :]
    second = np.diff(first, axis=1) / np.diff(wl[:-1])[None, :]
    return pd.DataFrame({
        "spectral_range": np.nanmax(arr, axis=1) - np.nanmin(arr, axis=1),
        "first_derivative_rms": np.sqrt(np.nanmean(first ** 2, axis=1)),
        "second_derivative_rms": np.sqrt(np.nanmean(second ** 2, axis=1)),
    })


def subject_balanced_geometry(
    analysis,
    X_adm,
    subject_col,
    body_col,
    variance_targets,
    maximum_components,
):
    work = pd.DataFrame({
        "subject_id": analysis[subject_col].astype("string"),
        "body_site": analysis[body_col].astype("string"),
    }, index=analysis.index)

    work = pd.concat(
        [work, X_adm],
        axis=1,
    )

    spectral_columns = list(X_adm.columns)

    subject_site = (
        work.groupby(
            ["subject_id", "body_site"],
            as_index=False,
            dropna=False,
        )[spectral_columns]
        .mean()
    )

    site_means = subject_site.groupby(
        "body_site"
    )[spectral_columns].transform("mean")

    within_centered = (
        subject_site[spectral_columns]
        - site_means
    )

    pca, metrics = fit_geometry(
        within_centered,
        variance_targets,
        maximum_components,
    )

    rows = []

    for site, group in subject_site.groupby(
        "body_site",
        dropna=False,
    ):
        Xi = group[spectral_columns]
        Xi_centered = Xi - Xi.mean(axis=0)

        _, site_metrics = fit_geometry(
            Xi_centered,
            variance_targets,
            maximum_components,
        )

        row = {
            "body_site": str(site),
            "subject_site_rows": int(len(group)),
            "participation_ratio": (
                site_metrics["participation_ratio"]
            ),
            "shannon_effective_rank": (
                site_metrics["shannon_effective_rank"]
            ),
        }

        for target, count in (
            site_metrics[
                "components_for_targets"
            ].items()
        ):
            row[
                f"components_for_{target}"
            ] = count

        rows.append(row)

    return (
        subject_site,
        pd.DataFrame(rows),
        pca,
        metrics,
    )


def principal_angle_similarity(components_a, components_b, k):
    k = min(k, components_a.shape[0], components_b.shape[0])
    if k < 1:
        return None
    A = components_a[:k].T
    B = components_b[:k].T
    singular = np.linalg.svd(A.T @ B, compute_uv=False)
    singular = np.clip(singular, 0.0, 1.0)
    angles = np.degrees(np.arccos(singular))
    return {
        "k": int(k),
        "mean_angle_degrees": float(np.mean(angles)),
        "max_angle_degrees": float(np.max(angles)),
        "mean_cosine": float(np.mean(singular)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-file", type=Path, required=True)
    parser.add_argument("--stage4-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(__file__).with_name("config.yaml").read_text(encoding="utf-8"))
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    stage4 = json.loads(args.stage4_summary.read_text(encoding="utf-8"))
    allowed = set(cfg["closure"]["require_stage4_scope_status"])
    if stage4.get("status") not in allowed:
        raise RuntimeError(f"Stage 4 status not admissible: {stage4.get('status')}")
    if cfg["closure"]["require_body_site_restriction"] and not stage4.get("body_site_restriction_required"):
        raise RuntimeError("Stage 4 body-site restriction is required but absent.")

    df = pd.read_parquet(args.canonical_file)
    subject_col = find_col(df.columns, cfg["columns"]["subject"])
    body_col = find_col(df.columns, cfg["columns"]["body_site"])
    origin_col = find_col(df.columns, cfg["columns"]["origin"])
    instrument_col = find_col(df.columns, cfg["columns"]["instrument"])
    specular_col = find_col(df.columns, cfg["columns"]["specular"])

    expected_wavelengths, resolved, missing_wavelengths = resolve_wavelength_columns(df, cfg)
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

    missing_required = []
    if subject_col is None:
        missing_required.append("subject")
    if body_col is None:
        missing_required.append("body_site")
    if missing_wavelengths:
        missing_required.append("wavelengths")

    if missing_required:
        summary = {
            "stage": 5,
            "status": "OPEN_FAILED_GATES",
            "missing_required": missing_required,
            "missing_wavelengths": missing_wavelengths,
            "gates": {"required_inputs_resolved": False},
        }
        (out / "stage5_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
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
    analysis["_row_index"] = analysis.index
    analysis["_body_site"] = analysis[body_col].astype("string")
    analysis["_subject"] = analysis[subject_col].astype("string")

    min_rows = int(cfg["geometry"]["minimum_site_rows"])
    min_subjects = int(cfg["geometry"]["minimum_site_subjects"])
    site_inventory = (
        analysis.groupby("_body_site", dropna=False)
        .agg(rows=("_row_index", "size"), subjects=("_subject", "nunique"))
        .reset_index()
        .rename(columns={"_body_site": "body_site"})
    )
    site_inventory["eligible"] = (
        (site_inventory["rows"] >= min_rows)
        & (site_inventory["subjects"] >= min_subjects)
    )
    write_table(site_inventory, out / "body_site_inventory")

    eligible_sites = set(site_inventory.loc[site_inventory["eligible"], "body_site"].astype(str))
    eligible_mask = analysis["_body_site"].astype(str).isin(eligible_sites)
    eligible_rows = int(eligible_mask.sum())
    eligible_fraction = float(eligible_rows / len(analysis)) if len(analysis) else 0.0

    X_eligible = X_adm.loc[analysis.index[eligible_mask]]
    site_labels = analysis.loc[eligible_mask, "_body_site"].astype(str)

    # Diagnostic pooled geometry.
    pooled_centered = X_eligible - X_eligible.mean(axis=0)
    pooled_pca, pooled_metrics = fit_geometry(
        pooled_centered,
        cfg["geometry"]["variance_targets"],
        cfg["geometry"]["maximum_components"],
    )

    # Primary geometry: center within each body site.
    site_means = X_eligible.groupby(site_labels).transform("mean")
    within_centered = X_eligible - site_means
    within_pca, within_metrics = fit_geometry(
        within_centered,
        cfg["geometry"]["variance_targets"],
        cfg["geometry"]["maximum_components"],
    )

    # Between-site variance decomposition.
    grand_mean = X_eligible.mean(axis=0).to_numpy(float)
    total_ss = float(np.sum((X_eligible.to_numpy(float) - grand_mean) ** 2))
    within_ss = float(np.sum(within_centered.to_numpy(float) ** 2))
    between_ss = max(total_ss - within_ss, 0.0)
    site_variance_fraction = between_ss / total_ss if total_ss > 0 else None

    eigen_rows = []
    for geometry_name, pca in [("pooled_diagnostic", pooled_pca), ("within_site_primary", within_pca)]:
        for i, (ev, ratio) in enumerate(zip(pca.explained_variance_, pca.explained_variance_ratio_), 1):
            eigen_rows.append({
                "geometry": geometry_name,
                "component": i,
                "eigenvalue": float(ev),
                "explained_variance_ratio": float(ratio),
                "cumulative_explained_variance": float(np.sum(pca.explained_variance_ratio_[:i])),
            })

    site_metric_rows = []
    site_models = {}
    site_scores_parts = []
    reconstruction_rows = []
    derivative_parts = []

    for site in sorted(eligible_sites):
        idx = analysis.index[analysis["_body_site"].astype(str) == site]
        Xi = X_adm.loc[idx]
        Xi_centered = Xi - Xi.mean(axis=0)
        pca, metrics = fit_geometry(
            Xi_centered,
            cfg["geometry"]["variance_targets"],
            cfg["geometry"]["maximum_components"],
        )
        site_models[site] = pca

        row = {
            "body_site": site,
            "rows": int(len(Xi)),
            "subjects": int(analysis.loc[idx, "_subject"].nunique()),
            "participation_ratio": metrics["participation_ratio"],
            "shannon_effective_rank": metrics["shannon_effective_rank"],
        }
        for target, count in metrics["components_for_targets"].items():
            row[f"components_for_{target}"] = count
        site_metric_rows.append(row)

        for i, (ev, ratio) in enumerate(zip(pca.explained_variance_, pca.explained_variance_ratio_), 1):
            eigen_rows.append({
                "geometry": f"body_site_{site}",
                "component": i,
                "eigenvalue": float(ev),
                "explained_variance_ratio": float(ratio),
                "cumulative_explained_variance": float(np.sum(pca.explained_variance_ratio_[:i])),
            })

        max_score_components = min(10, pca.n_components_)
        scores = pca.transform(Xi_centered)[:, :max_score_components]
        score_df = pd.DataFrame(
            scores,
            columns=[f"PC{i}" for i in range(1, max_score_components + 1)],
            index=idx,
        )
        score_df.insert(0, "body_site", site)
        score_df.insert(0, "subject_id", analysis.loc[idx, "_subject"].to_numpy())
        score_df.insert(0, "row_index", idx)
        site_scores_parts.append(score_df)

        for k in cfg["geometry"]["reconstruction_components"]:
            kk = min(int(k), pca.n_components_)
            transformed = pca.transform(Xi_centered)
            reconstructed = transformed[:, :kk] @ pca.components_[:kk, :]
            rmse = np.sqrt(np.mean((Xi_centered.to_numpy(float) - reconstructed) ** 2, axis=1))
            reconstruction_rows.append(pd.DataFrame({
                "row_index": idx,
                "body_site": site,
                "components": kk,
                "reconstruction_rmse": rmse,
            }))

        dm = derivative_metrics(Xi, wavelengths)
        dm.insert(0, "body_site", site)
        dm.insert(0, "row_index", idx)
        derivative_parts.append(dm)

    write_table(pd.DataFrame(eigen_rows), out / "eigenvalue_spectra")
    write_table(pd.DataFrame(site_metric_rows), out / "site_effective_dimension")
    write_table(pd.concat(site_scores_parts, ignore_index=True), out / "site_conditioned_pca_scores")
    write_table(pd.concat(reconstruction_rows, ignore_index=True), out / "site_reconstruction_error")
    write_table(pd.concat(derivative_parts, ignore_index=True), out / "spectral_derivative_metrics")

    angle_rows = []
    sites = sorted(site_models)
    k_angles = int(cfg["geometry"]["subspace_components"])
    for i, site_a in enumerate(sites):
        for site_b in sites[i + 1:]:
            metric = principal_angle_similarity(
                site_models[site_a].components_,
                site_models[site_b].components_,
                k_angles,
            )
            if metric is not None:
                angle_rows.append({
                    "body_site_a": site_a,
                    "body_site_b": site_b,
                    **metric,
                })
    angle_df = pd.DataFrame(angle_rows)
    write_table(
        angle_df,
        out / "cross_site_subspace_angles",
    )

    (
        subject_site,
        subject_balanced_site_metrics,
        subject_balanced_pca,
        subject_balanced_metrics,
    ) = subject_balanced_geometry(
        analysis.loc[eligible_mask],
        X_eligible,
        subject_col,
        body_col,
        cfg["geometry"]["variance_targets"],
        cfg["geometry"]["maximum_components"],
    )

    write_table(
        subject_balanced_site_metrics,
        out / "subject_balanced_site_geometry",
    )

    subject_balanced_summary = {
        "subject_site_rows": int(
            len(subject_site)
        ),
        "unique_subjects": int(
            subject_site[
                "subject_id"
            ].nunique()
        ),
        "body_sites": int(
            subject_site[
                "body_site"
            ].nunique()
        ),
        "participation_ratio": (
            subject_balanced_metrics[
                "participation_ratio"
            ]
        ),
        "shannon_effective_rank": (
            subject_balanced_metrics[
                "shannon_effective_rank"
            ]
        ),
        "components_for_targets": (
            subject_balanced_metrics[
                "components_for_targets"
            ]
        ),
    }

    subject_balanced_summary = to_native(
        subject_balanced_summary
    )

    (
        out
        / "subject_balanced_geometry_summary.json"
    ).write_text(
        json.dumps(
            subject_balanced_summary,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    expected_rows = int(cfg["expected"]["canonical_rows"])
    expected_sites = int(cfg["expected"]["body_site_levels"])
    gates = {
        "stage4_scope_status_admissible": stage4.get("status") in allowed,
        "stage4_body_site_restriction_inherited": stage4.get("body_site_restriction_required") is True,
        "canonical_row_count_match": len(df) == expected_rows,
        "required_columns_resolved": not missing_required,
        "wavelength_grid_exact": wavelengths == expected_wavelengths,
        "reflectance_scale_resolved": scale_meta["source_scale"] in {"percent", "fraction"},
        "nonzero_admissible_rows": int(admissible.sum()) > 0,
        "body_site_level_count_match": int(analysis["_body_site"].nunique(dropna=True)) == expected_sites,
        "eligible_site_count_nontrivial": len(eligible_sites) >= 2,
        "eligible_row_fraction_sufficient": eligible_fraction >= float(cfg["geometry"]["minimum_eligible_row_fraction"]),
        "within_site_geometry_computed": within_metrics["participation_ratio"] is not None,
        "per_site_geometry_computed": len(site_metric_rows) == len(eligible_sites),
        "cross_site_subspace_computed": len(angle_df) > 0,
        "subject_balanced_geometry_computed": (
            subject_balanced_metrics[
                "participation_ratio"
            ]
            is not None
        ),
        "subject_balanced_dimension_stable": (
            subject_balanced_metrics[
                "participation_ratio"
            ]
            <= 2.5
            and subject_balanced_metrics[
                "components_for_targets"
            ]["0.9"]
            <= 3
            and subject_balanced_metrics[
                "components_for_targets"
            ]["0.95"]
            <= 5
            and subject_balanced_metrics[
                "components_for_targets"
            ]["0.99"]
            <= 10
        ),
    }

    status = "CLOSED_WITH_SCOPE_LIMITATION" if all(gates.values()) else "OPEN_FAILED_GATES"

    summary = {
        "stage": 5,
        "name": "spectral_geometry_and_effective_information_dimension",
        "status": status,
        "canonical_path": str(args.canonical_file),
        "canonical_sha256": sha256_file(args.canonical_file),
        "canonical_rows": len(df),
        "admissible_rows": int(admissible.sum()),
        "inadmissible_rows": int((~admissible).sum()),
        "reflectance_scale": scale_meta,
        "body_site_column": body_col,
        "body_site_levels": int(analysis["_body_site"].nunique(dropna=True)),
        "eligible_body_sites": sorted(eligible_sites),
        "eligible_rows": eligible_rows,
        "eligible_row_fraction": eligible_fraction,
        "pooled_diagnostic_participation_ratio": pooled_metrics["participation_ratio"],
        "pooled_diagnostic_shannon_effective_rank": pooled_metrics["shannon_effective_rank"],
        "pooled_diagnostic_components_for_targets": pooled_metrics["components_for_targets"],
        "within_site_participation_ratio": within_metrics["participation_ratio"],
        "within_site_shannon_effective_rank": within_metrics["shannon_effective_rank"],
        "within_site_components_for_targets": within_metrics["components_for_targets"],
        "subject_balanced_participation_ratio": (
            subject_balanced_metrics[
                "participation_ratio"
            ]
        ),
        "subject_balanced_shannon_effective_rank": (
            subject_balanced_metrics[
                "shannon_effective_rank"
            ]
        ),
        "subject_balanced_components_for_targets": (
            subject_balanced_metrics[
                "components_for_targets"
            ]
        ),
        "subject_balanced_subject_site_rows": int(
            len(subject_site)
        ),
        "between_site_spectral_variance_fraction": site_variance_fraction,
        "analysis_unit": "body_location_code_conditioned_spectrum",
        "global_subject_tone_scalar_admissible": False,
        "inherited_scope_limitations": stage4.get("unresolved_scope_dimensions", []),
        "gates": gates,
        "hard_failed_gates": [k for k, v in gates.items() if not v],
        "next_stage": {
            "id": 6,
            "name": "site_conditioned_spectral_representation_and_validation",
            "inherited_restrictions": stage4.get("next_stage", {}).get("inherited_restrictions", []),
        } if all(gates.values()) else None,
    }
    summary = to_native(summary)

    (out / "stage5_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out / "STAGE_5_CLOSED.yaml").write_text(
        yaml.safe_dump(summary, sort_keys=False),
        encoding="utf-8",
    )

    report = [
        "# ISSA Stage 5 Spectral Geometry Report",
        "",
        f"Status: **{status}**",
        "",
        f"- Canonical rows: {len(df)}",
        f"- Admissible rows: {int(admissible.sum())}",
        f"- Body-site levels: {summary['body_site_levels']}",
        f"- Eligible body sites: {len(eligible_sites)}",
        f"- Eligible row fraction: {eligible_fraction:.6f}",
        f"- Pooled diagnostic participation ratio: {summary['pooled_diagnostic_participation_ratio']}",
        f"- Within-site participation ratio: {summary['within_site_participation_ratio']}",
        f"- Within-site Shannon effective rank: {summary['within_site_shannon_effective_rank']}",
        f"- Between-site spectral variance fraction: {summary['between_site_spectral_variance_fraction']}",
        "",
        "## Adjudication",
        "",
        "- Primary geometry is computed after centering within body location.",
        "- Pooled geometry is retained only as a diagnostic reference.",
        "- A global subject-level skin-tone scalar remains prohibited.",
        "- Cross-instrument, SCI/SCE, and protected/exposed equivalence remain unestablished.",
    ]
    (out / "spectral_geometry_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    manifest = []
    for path in sorted(out.iterdir()):
        if path.is_file():
            manifest.append({
                "file": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            })
    pd.DataFrame(manifest).to_csv(out / "sha256_manifest.csv", index=False)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if status == "CLOSED_WITH_SCOPE_LIMITATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
