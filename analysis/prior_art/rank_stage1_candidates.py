from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("analysis/prior_art")

DEFAULT_INPUT = (
    ROOT
    / "evidence/discovery/"
    "stage1_candidate_harvest.snapshot.json"
)

DEFAULT_POLICY = (
    ROOT
    / "policy/"
    "stage1_candidate_ranking_policy.yaml"
)

DEFAULT_QUERY_REGISTRY = (
    ROOT
    / "registry/search_query_registry.yaml"
)

DEFAULT_OUTPUT_DIR = (
    ROOT / "evidence/ranking"
)


def normalized(value: Any) -> str:
    return " ".join(
        str(value or "").lower().split()
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON mapping: {path}"
        )

    return value


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected YAML mapping: {path}"
        )

    return value


def integer_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def optional_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None

    return year


def term_hits(
    text: str,
    terms: list[str],
) -> list[str]:
    return sorted({
        term
        for term in terms
        if normalized(term) in text
    })


def score_candidate_domain(
    candidate: dict[str, Any],
    domain: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    weights = policy["score_weights"]

    title = normalized(candidate.get("title"))
    venue = normalized(candidate.get("venue"))
    publication_type = normalized(
        candidate.get("publication_type")
    )

    combined = " ".join([
        title,
        venue,
        publication_type,
    ])

    terms = [
        normalized(term)
        for term in policy["domain_terms"][domain]
    ]

    domain_hits = term_hits(
        combined,
        terms,
    )

    title_hits = term_hits(
        title,
        terms,
    )

    components: list[dict[str, Any]] = []

    def add_component(
        name: str,
        value: float,
        evidence: Any,
    ) -> None:
        components.append({
            "component": name,
            "value": round(
                float(value),
                6,
            ),
            "evidence": evidence,
        })

    domain_hit_count = min(
        len(domain_hits),
        int(weights["domain_term_hit_cap"]),
    )

    add_component(
        "domain_term_hits",
        (
            domain_hit_count
            * float(weights["domain_term_hit"])
        ),
        domain_hits,
    )

    title_hit_count = min(
        len(title_hits),
        int(weights["title_term_bonus_cap"]),
    )

    add_component(
        "title_term_hits",
        (
            title_hit_count
            * float(weights["title_term_bonus"])
        ),
        title_hits,
    )

    add_component(
        "doi_present",
        (
            float(weights["doi_present"])
            if candidate.get("doi")
            else 0.0
        ),
        bool(candidate.get("doi")),
    )

    add_component(
        "pmid_present",
        (
            float(weights["pmid_present"])
            if candidate.get("pmid")
            else 0.0
        ),
        bool(candidate.get("pmid")),
    )

    add_component(
        "abstract_available",
        (
            float(weights["abstract_available"])
            if candidate.get("abstract_available")
            else 0.0
        ),
        bool(
            candidate.get("abstract_available")
        ),
    )

    primary_hits = term_hits(
        publication_type,
        [
            normalized(term)
            for term in policy[
                "primary_publication_type_terms"
            ]
        ],
    )

    secondary_hits = term_hits(
        publication_type,
        [
            normalized(term)
            for term in policy[
                "secondary_publication_type_terms"
            ]
        ],
    )

    add_component(
        "primary_publication_type",
        (
            float(
                weights[
                    "primary_publication_type"
                ]
            )
            if primary_hits
            else 0.0
        ),
        primary_hits,
    )

    add_component(
        "secondary_publication_type",
        (
            float(
                weights[
                    "secondary_publication_type"
                ]
            )
            if secondary_hits
            else 0.0
        ),
        secondary_hits,
    )

    citation_count = integer_or_zero(
        candidate.get("citation_count")
    )

    citation_score = min(
        math.log10(citation_count + 1),
        float(weights["citation_log10_cap"]),
    )

    add_component(
        "citation_log10",
        citation_score,
        citation_count,
    )

    year = optional_year(
        candidate.get("year")
    )

    add_component(
        "publication_year_2020_or_later",
        (
            float(
                weights[
                    "publication_year_2020_or_later"
                ]
            )
            if year is not None and year >= 2020
            else 0.0
        ),
        year,
    )

    add_component(
        "publication_year_before_1990",
        (
            float(
                weights[
                    "publication_year_before_1990"
                ]
            )
            if year is not None and year < 1990
            else 0.0
        ),
        year,
    )

    exclusion_hits = term_hits(
        title,
        [
            normalized(term)
            for term in policy[
                "title_exclusion_terms"
            ]
        ],
    )

    add_component(
        "title_exclusion_term",
        (
            float(weights["title_exclusion_term"])
            if exclusion_hits
            else 0.0
        ),
        exclusion_hits,
    )

    add_component(
        "missing_title",
        (
            float(weights["missing_title"])
            if not title
            else 0.0
        ),
        not bool(title),
    )

    add_component(
        "short_title",
        (
            float(
                weights[
                    "title_shorter_than_15_characters"
                ]
            )
            if title and len(title) < 15
            else 0.0
        ),
        len(title),
    )

    total = round(
        sum(
            component["value"]
            for component in components
        ),
        6,
    )

    nonzero_components = [
        component
        for component in components
        if component["value"] != 0
    ]

    return {
        "domain_score": total,
        "score_components": components,
        "nonzero_score_components": (
            nonzero_components
        ),
        "domain_term_hits": domain_hits,
        "title_term_hits": title_hits,
    }


def domain_sort_key(
    row: dict[str, Any],
) -> tuple[Any, ...]:
    year = optional_year(row.get("year"))

    return (
        -float(row["domain_score"]),
        -integer_or_zero(
            row.get("citation_count")
        ),
        -(year or 0),
        row["canonical_key"],
    )


def global_sort_key(
    row: dict[str, Any],
) -> tuple[Any, ...]:
    year = optional_year(row.get("year"))

    return (
        -float(row["global_priority_score"]),
        -float(row["maximum_domain_score"]),
        -int(row["domain_count"]),
        -integer_or_zero(
            row.get("citation_count")
        ),
        -(year or 0),
        row["canonical_key"],
    )


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str],
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            lineterminator="\n",
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            rendered = dict(row)

            for key, value in list(
                rendered.items()
            ):
                if isinstance(
                    value,
                    (list, dict),
                ):
                    rendered[key] = json.dumps(
                        value,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )

            writer.writerow(rendered)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )

    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY,
    )

    parser.add_argument(
        "--query-registry",
        type=Path,
        default=DEFAULT_QUERY_REGISTRY,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )

    args = parser.parse_args()

    harvest = load_json(args.input)
    policy = load_yaml(args.policy)
    queries = load_yaml(args.query_registry)

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    required_domains = {
        row["domain"]
        for row in queries["query_families"]
    }

    policy_domains = set(
        policy["domain_terms"]
    )

    if policy_domains != required_domains:
        raise ValueError({
            "policy_only": sorted(
                policy_domains - required_domains
            ),
            "query_registry_only": sorted(
                required_domains - policy_domains
            ),
        })

    candidates = harvest["candidates"]

    canonical_keys = [
        candidate["canonical_key"]
        for candidate in candidates
    ]

    if len(canonical_keys) != len(
        set(canonical_keys)
    ):
        raise ValueError(
            "DUPLICATE_HARVEST_CANONICAL_KEYS"
        )

    pair_rows: list[dict[str, Any]] = []
    rows_by_domain: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    candidate_lookup = {
        candidate["canonical_key"]: candidate
        for candidate in candidates
    }

    for candidate in candidates:
        candidate_domains = sorted(
            set(candidate["domains"])
        )

        unknown_domains = (
            set(candidate_domains)
            - required_domains
        )

        if unknown_domains:
            raise ValueError({
                "candidate_key": candidate[
                    "canonical_key"
                ],
                "unknown_domains": sorted(
                    unknown_domains
                ),
            })

        for domain in candidate_domains:
            scoring = score_candidate_domain(
                candidate,
                domain,
                policy,
            )

            row = {
                "canonical_key": candidate[
                    "canonical_key"
                ],
                "domain": domain,
                "domain_score": scoring[
                    "domain_score"
                ],
                "score_components": scoring[
                    "score_components"
                ],
                "nonzero_score_components": scoring[
                    "nonzero_score_components"
                ],
                "domain_term_hits": scoring[
                    "domain_term_hits"
                ],
                "title_term_hits": scoring[
                    "title_term_hits"
                ],
                "title": candidate.get(
                    "title",
                    "",
                ),
                "authors": candidate.get(
                    "authors",
                    [],
                ),
                "year": candidate.get("year"),
                "doi": candidate.get("doi"),
                "pmid": candidate.get("pmid"),
                "arxiv": candidate.get(
                    "arxiv"
                ),
                "venue": candidate.get(
                    "venue"
                ),
                "publication_type": (
                    candidate.get(
                        "publication_type"
                    )
                ),
                "citation_count": (
                    candidate.get(
                        "citation_count"
                    )
                ),
                "abstract_available": bool(
                    candidate.get(
                        "abstract_available"
                    )
                ),
                "url": candidate.get("url"),
                "query_family_ids": candidate.get(
                    "query_family_ids",
                    [],
                ),
                "discovery_queries": candidate.get(
                    "discovery_queries",
                    [],
                ),
                "all_candidate_domains": (
                    candidate_domains
                ),
                "discovery_source": candidate.get(
                    "discovery_source"
                ),
                "admission_state": (
                    "UNSCREENED_NOT_ADMITTED"
                ),
            }

            rows_by_domain[domain].append(
                row
            )

    domain_counts: dict[str, int] = {}

    for domain in sorted(required_domains):
        domain_rows = rows_by_domain[domain]
        domain_rows.sort(
            key=domain_sort_key
        )

        domain_counts[domain] = len(
            domain_rows
        )

        for rank, row in enumerate(
            domain_rows,
            start=1,
        ):
            row["domain_rank"] = rank
            row["domain_candidate_count"] = (
                len(domain_rows)
            )
            pair_rows.append(row)

    pair_rows.sort(
        key=lambda row: (
            row["domain"],
            row["domain_rank"],
            row["canonical_key"],
        )
    )

    pair_rows_by_candidate: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in pair_rows:
        pair_rows_by_candidate[
            row["canonical_key"]
        ].append(row)

    breadth_weight = float(
        policy["global_priority"][
            "domain_breadth_weight"
        ]
    )

    global_rows: list[dict[str, Any]] = []

    for canonical_key in sorted(
        candidate_lookup
    ):
        candidate = candidate_lookup[
            canonical_key
        ]

        assigned_rows = pair_rows_by_candidate[
            canonical_key
        ]

        maximum_domain_score = max(
            row["domain_score"]
            for row in assigned_rows
        )

        domain_count = len(assigned_rows)

        global_priority_score = round(
            maximum_domain_score
            + breadth_weight
            * (domain_count - 1),
            6,
        )

        strongest_domain_rows = sorted(
            assigned_rows,
            key=domain_sort_key,
        )

        global_rows.append({
            "canonical_key": canonical_key,
            "global_priority_score": (
                global_priority_score
            ),
            "maximum_domain_score": (
                maximum_domain_score
            ),
            "domain_breadth_bonus": round(
                breadth_weight
                * (domain_count - 1),
                6,
            ),
            "domain_count": domain_count,
            "assigned_domains": sorted(
                row["domain"]
                for row in assigned_rows
            ),
            "domain_rankings": [
                {
                    "domain": row["domain"],
                    "domain_rank": row[
                        "domain_rank"
                    ],
                    "domain_candidate_count": row[
                        "domain_candidate_count"
                    ],
                    "domain_score": row[
                        "domain_score"
                    ],
                }
                for row in sorted(
                    assigned_rows,
                    key=lambda item: (
                        item["domain"]
                    ),
                )
            ],
            "strongest_domain": (
                strongest_domain_rows[0][
                    "domain"
                ]
            ),
            "title": candidate.get(
                "title",
                "",
            ),
            "authors": candidate.get(
                "authors",
                [],
            ),
            "year": candidate.get("year"),
            "doi": candidate.get("doi"),
            "pmid": candidate.get("pmid"),
            "arxiv": candidate.get("arxiv"),
            "venue": candidate.get(
                "venue"
            ),
            "publication_type": (
                candidate.get(
                    "publication_type"
                )
            ),
            "citation_count": candidate.get(
                "citation_count"
            ),
            "abstract_available": bool(
                candidate.get(
                    "abstract_available"
                )
            ),
            "url": candidate.get("url"),
            "query_family_ids": candidate.get(
                "query_family_ids",
                [],
            ),
            "discovery_queries": candidate.get(
                "discovery_queries",
                [],
            ),
            "admission_state": (
                "UNSCREENED_NOT_ADMITTED"
            ),
        })

    global_rows.sort(
        key=global_sort_key
    )

    for rank, row in enumerate(
        global_rows,
        start=1,
    ):
        row["global_rank"] = rank
        row["global_candidate_count"] = (
            len(global_rows)
        )

    top_per_domain = int(
        policy["shortlist_policy"][
            "top_per_domain"
        ]
    )

    shortlist_rows = [
        row
        for row in pair_rows
        if row["domain_rank"]
        <= top_per_domain
    ]

    complete_pair_payload = {
        "stage": 1,
        "artifact": (
            "complete_candidate_domain_ranking"
        ),
        "ranking_policy_version": (
            policy["policy_version"]
        ),
        "candidate_count": len(candidates),
        "candidate_domain_pair_count": len(
            pair_rows
        ),
        "domain_count": len(
            required_domains
        ),
        "domain_candidate_counts": dict(
            sorted(domain_counts.items())
        ),
        "admission_status": (
            "UNSCREENED_NOT_ADMITTED"
        ),
        "rows": pair_rows,
    }

    global_payload = {
        "stage": 1,
        "artifact": (
            "complete_deduplicated_global_ranking"
        ),
        "ranking_policy_version": (
            policy["policy_version"]
        ),
        "candidate_count": len(global_rows),
        "global_priority_formula": (
            policy["global_priority"][
                "formula"
            ]
        ),
        "admission_status": (
            "UNSCREENED_NOT_ADMITTED"
        ),
        "rows": global_rows,
    }

    shortlist_payload = {
        "stage": 1,
        "artifact": (
            "derived_top_per_domain_review_view"
        ),
        "ranking_policy_version": (
            policy["policy_version"]
        ),
        "top_per_domain": top_per_domain,
        "domain_slot_count": len(
            shortlist_rows
        ),
        "unique_candidate_count": len({
            row["canonical_key"]
            for row in shortlist_rows
        }),
        "authoritative_ranking": False,
        "admission_status": (
            "UNSCREENED_NOT_ADMITTED"
        ),
        "rows": shortlist_rows,
    }

    pair_json = (
        args.output_dir
        / "stage1_complete_domain_ranking.json"
    )

    pair_csv = (
        args.output_dir
        / "stage1_complete_domain_ranking.csv"
    )

    global_json = (
        args.output_dir
        / "stage1_complete_global_ranking.json"
    )

    global_csv = (
        args.output_dir
        / "stage1_complete_global_ranking.csv"
    )

    shortlist_json = (
        args.output_dir
        / "stage1_top20_domain_review_view.json"
    )

    shortlist_csv = (
        args.output_dir
        / "stage1_top20_domain_review_view.csv"
    )

    pair_json.write_text(
        json.dumps(
            complete_pair_payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    global_json.write_text(
        json.dumps(
            global_payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    shortlist_json.write_text(
        json.dumps(
            shortlist_payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    write_csv(
        pair_csv,
        pair_rows,
        [
            "domain",
            "domain_rank",
            "domain_candidate_count",
            "canonical_key",
            "domain_score",
            "title",
            "year",
            "authors",
            "doi",
            "pmid",
            "arxiv",
            "venue",
            "publication_type",
            "citation_count",
            "abstract_available",
            "url",
            "query_family_ids",
            "discovery_queries",
            "all_candidate_domains",
            "domain_term_hits",
            "title_term_hits",
            "score_components",
            "nonzero_score_components",
            "admission_state",
        ],
    )

    write_csv(
        global_csv,
        global_rows,
        [
            "global_rank",
            "global_candidate_count",
            "canonical_key",
            "global_priority_score",
            "maximum_domain_score",
            "domain_breadth_bonus",
            "domain_count",
            "assigned_domains",
            "strongest_domain",
            "domain_rankings",
            "title",
            "year",
            "authors",
            "doi",
            "pmid",
            "arxiv",
            "venue",
            "publication_type",
            "citation_count",
            "abstract_available",
            "url",
            "query_family_ids",
            "discovery_queries",
            "admission_state",
        ],
    )

    write_csv(
        shortlist_csv,
        shortlist_rows,
        [
            "domain",
            "domain_rank",
            "domain_candidate_count",
            "canonical_key",
            "domain_score",
            "title",
            "year",
            "authors",
            "doi",
            "pmid",
            "arxiv",
            "venue",
            "publication_type",
            "citation_count",
            "abstract_available",
            "url",
            "query_family_ids",
            "domain_term_hits",
            "title_term_hits",
            "nonzero_score_components",
            "admission_state",
        ],
    )

    implementation_path = Path(__file__)

    lineage = {
        "stage": 1,
        "artifact": "candidate_ranking_lineage",
        "ranking_policy_version": (
            policy["policy_version"]
        ),
        "inputs": [
            {
                "role": "harvest_snapshot",
                "path": str(args.input),
                "bytes": args.input.stat().st_size,
                "sha256": sha256(args.input),
                "canonical_content_sha256": (
                    harvest["content_sha256"]
                ),
            },
            {
                "role": "ranking_policy",
                "path": str(args.policy),
                "bytes": args.policy.stat().st_size,
                "sha256": sha256(args.policy),
            },
            {
                "role": "query_registry",
                "path": str(
                    args.query_registry
                ),
                "bytes": (
                    args.query_registry.stat().st_size
                ),
                "sha256": sha256(
                    args.query_registry
                ),
            },
            {
                "role": "ranking_implementation",
                "path": str(
                    implementation_path
                ),
                "bytes": (
                    implementation_path.stat().st_size
                ),
                "sha256": sha256(
                    implementation_path
                ),
            },
        ],
        "counts": {
            "harvest_candidate_count": len(
                candidates
            ),
            "global_candidate_count": len(
                global_rows
            ),
            "candidate_domain_pair_count": len(
                pair_rows
            ),
            "domain_count": len(
                required_domains
            ),
            "shortlist_domain_slot_count": len(
                shortlist_rows
            ),
            "shortlist_unique_candidate_count": len({
                row["canonical_key"]
                for row in shortlist_rows
            }),
        },
        "outputs": [],
        "interpretation_limits": (
            policy["prohibited_interpretations"]
        ),
    }

    output_paths = [
        pair_json,
        pair_csv,
        global_json,
        global_csv,
        shortlist_json,
        shortlist_csv,
    ]

    lineage["outputs"] = [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in output_paths
    ]

    lineage["lineage_content_sha256"] = (
        canonical_json_sha256(lineage)
    )

    lineage_path = (
        args.output_dir
        / "stage1_candidate_ranking_lineage.json"
    )

    lineage_path.write_text(
        json.dumps(
            lineage,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"HARVEST_CANDIDATES="
        f"{len(candidates)}"
    )
    print(
        f"GLOBAL_RANKED_CANDIDATES="
        f"{len(global_rows)}"
    )
    print(
        f"CANDIDATE_DOMAIN_PAIRS="
        f"{len(pair_rows)}"
    )
    print(
        f"RANKED_DOMAINS="
        f"{len(required_domains)}"
    )
    print(
        f"TOP20_DOMAIN_SLOTS="
        f"{len(shortlist_rows)}"
    )
    print(
        "TOP20_UNIQUE_CANDIDATES="
        f"{shortlist_payload['unique_candidate_count']}"
    )
    print(
        f"LINEAGE={lineage_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
