from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("analysis/prior_art")


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


def sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--harvest",
        type=Path,
        default=(
            ROOT
            / "evidence/discovery/"
            "stage1_candidate_harvest.snapshot.json"
        ),
    )

    parser.add_argument(
        "--policy",
        type=Path,
        default=(
            ROOT
            / "policy/"
            "stage1_candidate_ranking_policy.yaml"
        ),
    )

    parser.add_argument(
        "--ranking-dir",
        type=Path,
        default=(
            ROOT / "evidence/ranking"
        ),
    )

    args = parser.parse_args()

    harvest = load_json(args.harvest)
    policy = load_yaml(args.policy)

    pairs = load_json(
        args.ranking_dir
        / "stage1_complete_domain_ranking.json"
    )

    global_ranking = load_json(
        args.ranking_dir
        / "stage1_complete_global_ranking.json"
    )

    shortlist = load_json(
        args.ranking_dir
        / "stage1_top20_domain_review_view.json"
    )

    lineage = load_json(
        args.ranking_dir
        / "stage1_candidate_ranking_lineage.json"
    )

    harvest_candidates = harvest[
        "candidates"
    ]

    harvest_keys = {
        row["canonical_key"]
        for row in harvest_candidates
    }

    global_rows = global_ranking["rows"]
    pair_rows = pairs["rows"]
    shortlist_rows = shortlist["rows"]

    global_keys = {
        row["canonical_key"]
        for row in global_rows
    }

    assert len(harvest_candidates) == 1303
    assert harvest_keys == global_keys
    assert len(global_rows) == 1303

    global_rank_values = sorted(
        row["global_rank"]
        for row in global_rows
    )

    assert global_rank_values == list(
        range(1, 1304)
    )

    assert len({
        row["canonical_key"]
        for row in global_rows
    }) == 1303

    expected_pair_set = {
        (
            candidate["canonical_key"],
            domain,
        )
        for candidate in harvest_candidates
        for domain in set(
            candidate["domains"]
        )
    }

    observed_pair_set = {
        (
            row["canonical_key"],
            row["domain"],
        )
        for row in pair_rows
    }

    assert observed_pair_set == (
        expected_pair_set
    )

    assert len(pair_rows) == len(
        expected_pair_set
    )

    pair_counts = Counter(
        (
            row["canonical_key"],
            row["domain"],
        )
        for row in pair_rows
    )

    assert all(
        count == 1
        for count in pair_counts.values()
    )

    by_domain: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in pair_rows:
        by_domain[row["domain"]].append(
            row
        )

    assert len(by_domain) == 14

    for domain, rows in by_domain.items():
        ranks = sorted(
            row["domain_rank"]
            for row in rows
        )

        assert ranks == list(
            range(1, len(rows) + 1)
        ), domain

        assert all(
            row["domain_candidate_count"]
            == len(rows)
            for row in rows
        )

    top_per_domain = int(
        policy["shortlist_policy"][
            "top_per_domain"
        ]
    )

    expected_shortlist_pairs = {
        (
            row["canonical_key"],
            row["domain"],
        )
        for row in pair_rows
        if row["domain_rank"]
        <= top_per_domain
    }

    observed_shortlist_pairs = {
        (
            row["canonical_key"],
            row["domain"],
        )
        for row in shortlist_rows
    }

    assert observed_shortlist_pairs == (
        expected_shortlist_pairs
    )

    assert len(shortlist_rows) == (
        14 * top_per_domain
    )

    assert shortlist[
        "authoritative_ranking"
    ] is False

    assert all(
        row["admission_state"]
        == "UNSCREENED_NOT_ADMITTED"
        for row in pair_rows
    )

    assert all(
        row["admission_state"]
        == "UNSCREENED_NOT_ADMITTED"
        for row in global_rows
    )

    output_records = lineage["outputs"]

    for record in output_records:
        path = Path(record["path"])

        assert path.is_file(), path
        assert path.stat().st_size == (
            record["bytes"]
        ), path
        assert sha256(path) == (
            record["sha256"]
        ), path

    assert lineage["counts"][
        "harvest_candidate_count"
    ] == 1303

    assert lineage["counts"][
        "global_candidate_count"
    ] == 1303

    assert lineage["counts"][
        "candidate_domain_pair_count"
    ] == len(pair_rows)

    assert lineage["counts"][
        "domain_count"
    ] == 14

    required_limits = {
        "rank_is_not_source_admission",
        "rank_is_not_scientific_quality",
        "rank_is_not_methodological_validity",
        "rank_is_not_novelty",
        "rank_is_not_ground_truth",
    }

    assert required_limits <= set(
        lineage["interpretation_limits"]
    )

    print("STAGE1_COMPLETE_RANKING_VALIDATION=PASS")
    print("HARVEST_CANDIDATES=1303")
    print("GLOBAL_RANKED_CANDIDATES=1303")
    print(
        "CANDIDATE_DOMAIN_PAIRS="
        f"{len(pair_rows)}"
    )
    print("DOMAIN_RANKINGS=14")
    print(
        "TOP20_DOMAIN_SLOTS="
        f"{len(shortlist_rows)}"
    )
    print(
        "TOP20_UNIQUE_CANDIDATES="
        f"{shortlist['unique_candidate_count']}"
    )
    print(
        "ADMISSION_STATE="
        "UNSCREENED_NOT_ADMITTED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
