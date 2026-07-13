from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(
    "analysis/prior_art/results/"
    "stage1_candidate_harvest.json"
)

DEFAULT_OUTPUT_JSON = Path(
    "analysis/prior_art/results/"
    "stage1_candidate_triage.json"
)

DEFAULT_OUTPUT_CSV = Path(
    "analysis/prior_art/results/"
    "stage1_domain_shortlist.csv"
)


DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "skin_tissue_optical_forward_models": (
        "skin",
        "reflectance",
        "optical",
        "forward model",
        "monte carlo",
        "multilayer",
        "melanin",
        "hemoglobin",
        "scattering",
    ),
    "skin_reflectance_inverse_models": (
        "skin",
        "reflectance",
        "inverse",
        "chromophore",
        "parameter estimation",
        "melanin",
        "hemoglobin",
        "inverse rendering",
    ),
    "melanin_hemoglobin_and_scattering_identifiability": (
        "melanin",
        "hemoglobin",
        "scattering",
        "identifiability",
        "collinearity",
        "chromophore",
        "parameter estimation",
    ),
    "spectral_reflectance_geometry_and_dimension": (
        "skin",
        "spectral",
        "reflectance",
        "principal component",
        "intrinsic dimension",
        "subspace",
        "body site",
    ),
    "camera_spectral_sensitivity_and_observation_operators": (
        "camera",
        "spectral sensitivity",
        "sensor response",
        "illuminant",
        "observation model",
        "rgb",
        "skin reflectance",
    ),
    "camera_metamerism_and_spectral_reconstruction": (
        "metamer",
        "metamerism",
        "spectral reconstruction",
        "spectral recovery",
        "rgb",
        "camera",
        "skin",
    ),
    "multispectral_band_selection_and_measurement_design": (
        "multispectral",
        "hyperspectral",
        "band selection",
        "wavelength selection",
        "measurement design",
        "optimal wavelength",
        "skin",
    ),
    "fisher_information_and_cramer_rao_skin_imaging": (
        "fisher information",
        "cramer rao",
        "cramér-rao",
        "information bound",
        "identifiability",
        "skin",
        "spectroscopy",
    ),
    "skin_colorimetry_ita_and_color_measurement": (
        "individual typology angle",
        "ita",
        "colorimeter",
        "spectrophotometer",
        "skin color",
        "color measurement",
        "body site",
    ),
    "capture_variability_white_balance_and_illumination": (
        "white balance",
        "illumination",
        "lighting",
        "exposure",
        "color constancy",
        "capture variability",
        "camera",
        "dermatology",
    ),
    "dermatology_ai_fairness_and_skin_tone": (
        "dermatology",
        "artificial intelligence",
        "deep learning",
        "fairness",
        "skin tone",
        "skin type",
        "disparity",
        "classification",
    ),
    "dermatology_dataset_duplicates_labels_and_quality": (
        "dermatology",
        "dataset",
        "duplicate",
        "deduplication",
        "label noise",
        "annotation",
        "quality",
        "fitzpatrick17k",
    ),
    "clinical_external_validation_and_domain_shift": (
        "external validation",
        "domain shift",
        "clinical",
        "dermatology",
        "pathology",
        "patient disjoint",
        "generalization",
        "dataset shift",
    ),
    "physics_informed_clinical_image_analysis": (
        "physics informed",
        "optical physics",
        "image formation",
        "measurement physics",
        "clinical imaging",
        "dermatology",
        "contrast",
    ),
}


PRIMARY_TYPE_TERMS = (
    "journal-article",
    "research article",
    "clinical trial",
    "validation study",
    "comparative study",
    "conference paper",
    "proceedings-article",
)


SECONDARY_TYPE_TERMS = (
    "review",
    "systematic review",
    "meta-analysis",
    "editorial",
    "comment",
    "letter",
    "news",
    "book review",
    "correction",
    "retraction",
)


TITLE_EXCLUSION_TERMS = (
    "erratum",
    "corrigendum",
    "correction to",
    "retraction",
    "editorial",
    "letter to the editor",
)


def normalized(value: Any) -> str:
    return " ".join(
        str(value or "").lower().split()
    )


def term_hits(
    text: str,
    terms: tuple[str, ...],
) -> list[str]:
    return sorted({
        term
        for term in terms
        if term in text
    })


def publication_type_score(
    value: Any,
) -> tuple[float, list[str]]:
    text = normalized(value)
    score = 0.0
    reasons: list[str] = []

    for term in PRIMARY_TYPE_TERMS:
        if term in text:
            score += 2.0
            reasons.append(
                f"primary_type:{term}"
            )
            break

    for term in SECONDARY_TYPE_TERMS:
        if term in text:
            score -= 4.0
            reasons.append(
                f"secondary_type:{term}"
            )
            break

    return score, reasons


def candidate_domain_score(
    candidate: dict[str, Any],
    domain: str,
) -> tuple[float, list[str]]:
    title = normalized(
        candidate.get("title")
    )
    venue = normalized(
        candidate.get("venue")
    )
    publication_type = normalized(
        candidate.get("publication_type")
    )

    combined = " ".join([
        title,
        venue,
        publication_type,
    ])

    score = 0.0
    reasons: list[str] = []

    hits = term_hits(
        combined,
        DOMAIN_TERMS[domain],
    )

    score += min(len(hits), 8) * 1.5

    if hits:
        reasons.append(
            "domain_terms:" + "|".join(hits)
        )

    title_hits = term_hits(
        title,
        DOMAIN_TERMS[domain],
    )

    score += min(len(title_hits), 6) * 1.0

    if candidate.get("doi"):
        score += 2.0
        reasons.append("doi_present")

    if candidate.get("pmid"):
        score += 2.0
        reasons.append("pmid_present")

    if candidate.get("abstract_available"):
        score += 1.0
        reasons.append("abstract_available")

    type_score, type_reasons = (
        publication_type_score(
            candidate.get("publication_type")
        )
    )

    score += type_score
    reasons.extend(type_reasons)

    citation_count = int(
        candidate.get("citation_count") or 0
    )

    if citation_count > 0:
        score += min(
            math.log10(citation_count + 1),
            3.0,
        )
        reasons.append(
            f"citation_count:{citation_count}"
        )

    year_value = candidate.get("year")

    try:
        year = int(year_value)
    except (TypeError, ValueError):
        year = None

    if year is not None:
        if year >= 2020:
            score += 1.0
            reasons.append("recent_2020_plus")
        elif year < 1990:
            score -= 0.5
            reasons.append("pre_1990")

    excluded_title_terms = term_hits(
        title,
        TITLE_EXCLUSION_TERMS,
    )

    if excluded_title_terms:
        score -= 10.0
        reasons.append(
            "title_exclusion:"
            + "|".join(excluded_title_terms)
        )

    if not title:
        score -= 20.0
        reasons.append("missing_title")

    if len(title) < 15:
        score -= 3.0
        reasons.append("very_short_title")

    return round(score, 6), reasons


def stable_candidate_key(
    candidate: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        candidate.get("canonical_key", ""),
        normalized(candidate.get("title")),
        str(candidate.get("year") or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )

    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )

    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
    )

    parser.add_argument(
        "--per-domain",
        type=int,
        default=20,
    )

    args = parser.parse_args()

    if args.per_domain < 1:
        raise ValueError(
            "--per-domain must be positive"
        )

    payload = json.loads(
        args.input.read_text(encoding="utf-8")
    )

    candidates = payload["candidates"]

    ranked_by_domain: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for candidate in candidates:
        for domain in candidate["domains"]:
            if domain not in DOMAIN_TERMS:
                raise ValueError(
                    f"Unknown domain: {domain}"
                )

            score, reasons = (
                candidate_domain_score(
                    candidate,
                    domain,
                )
            )

            ranked_by_domain[domain].append({
                "domain": domain,
                "score": score,
                "reasons": reasons,
                "candidate": candidate,
            })

    selected_rows: list[
        dict[str, Any]
    ] = []

    selected_keys: set[str] = set()
    selected_domain_counts = Counter()

    for domain in sorted(DOMAIN_TERMS):
        rows = ranked_by_domain[domain]

        rows.sort(
            key=lambda row: (
                -row["score"],
                stable_candidate_key(
                    row["candidate"]
                ),
            )
        )

        for domain_rank, row in enumerate(
            rows[: args.per_domain],
            start=1,
        ):
            candidate = row["candidate"]
            key = candidate["canonical_key"]

            selected_domain_counts[domain] += 1
            selected_keys.add(key)

            selected_rows.append({
                "domain": domain,
                "domain_rank": domain_rank,
                "triage_score": row["score"],
                "triage_reasons": row["reasons"],
                "canonical_key": key,
                "title": candidate.get(
                    "title",
                    "",
                ),
                "authors": candidate.get(
                    "authors",
                    [],
                ),
                "year": candidate.get(
                    "year",
                ),
                "doi": candidate.get(
                    "doi",
                ),
                "pmid": candidate.get(
                    "pmid",
                ),
                "venue": candidate.get(
                    "venue",
                ),
                "publication_type": candidate.get(
                    "publication_type",
                ),
                "citation_count": candidate.get(
                    "citation_count",
                ),
                "url": candidate.get(
                    "url",
                ),
                "all_candidate_domains": (
                    candidate.get(
                        "domains",
                        [],
                    )
                ),
                "query_family_ids": (
                    candidate.get(
                        "query_family_ids",
                        [],
                    )
                ),
            })

    selected_rows.sort(
        key=lambda row: (
            row["domain"],
            row["domain_rank"],
            row["canonical_key"],
        )
    )

    triage = {
        "stage": 1,
        "triage_version": "1.0.0",
        "input_candidate_count": len(
            candidates
        ),
        "per_domain_target": (
            args.per_domain
        ),
        "domain_slot_count": len(
            selected_rows
        ),
        "unique_shortlist_count": len(
            selected_keys
        ),
        "domain_counts": dict(
            sorted(
                selected_domain_counts.items()
            )
        ),
        "admission_status": (
            "SCREENING_ONLY_NOT_ADMITTED"
        ),
        "rows": selected_rows,
    }

    args.output_json.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output_json.write_text(
        json.dumps(
            triage,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    csv_fields = [
        "domain",
        "domain_rank",
        "triage_score",
        "canonical_key",
        "title",
        "year",
        "authors",
        "doi",
        "pmid",
        "venue",
        "publication_type",
        "citation_count",
        "url",
        "triage_reasons",
        "primary_source_verified",
        "publication_status_verified",
        "include_exclude",
        "exclusion_reason",
        "claims_addressed",
        "full_text_reviewed",
        "screening_notes",
    ]

    with args.output_csv.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=csv_fields,
            lineterminator="\n",
        )

        writer.writeheader()

        for row in selected_rows:
            writer.writerow({
                "domain": row["domain"],
                "domain_rank": (
                    row["domain_rank"]
                ),
                "triage_score": (
                    row["triage_score"]
                ),
                "canonical_key": (
                    row["canonical_key"]
                ),
                "title": row["title"],
                "year": row["year"] or "",
                "authors": " | ".join(
                    row["authors"]
                ),
                "doi": row["doi"] or "",
                "pmid": row["pmid"] or "",
                "venue": row["venue"] or "",
                "publication_type": (
                    row["publication_type"]
                    or ""
                ),
                "citation_count": (
                    row["citation_count"]
                    or ""
                ),
                "url": row["url"] or "",
                "triage_reasons": " | ".join(
                    row["triage_reasons"]
                ),
                "primary_source_verified": "",
                "publication_status_verified": "",
                "include_exclude": "",
                "exclusion_reason": "",
                "claims_addressed": "",
                "full_text_reviewed": "",
                "screening_notes": "",
            })

    print(
        f"INPUT_CANDIDATES={len(candidates)}"
    )
    print(
        f"DOMAIN_SLOTS={len(selected_rows)}"
    )
    print(
        f"UNIQUE_SHORTLIST="
        f"{len(selected_keys)}"
    )
    print(
        f"PER_DOMAIN_TARGET="
        f"{args.per_domain}"
    )
    print(
        f"TRIAGE_JSON={args.output_json}"
    )
    print(
        f"SHORTLIST_CSV={args.output_csv}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
