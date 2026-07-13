from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


ROOT = Path("analysis/prior_art")

TRIAGE_PATH = (
    ROOT / "results/stage1_candidate_triage.json"
)

DECISION_DIR = (
    ROOT / "corpus/screening_decisions"
)

SCHEMA_PATH = (
    ROOT / "schemas/screening_decision.schema.json"
)

QUERY_REGISTRY = (
    ROOT / "registry/search_query_registry.yaml"
)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected YAML mapping: {path}"
        )

    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON object: {path}"
        )

    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--triage",
        type=Path,
        default=TRIAGE_PATH,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results",
    )

    parser.add_argument(
        "--require-complete",
        action="store_true",
    )

    args = parser.parse_args()

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    triage = load_json(args.triage)
    schema = load_json(SCHEMA_PATH)
    queries = load_yaml(QUERY_REGISTRY)

    required_domains = {
        row["domain"]
        for row in queries["query_families"]
    }

    triage_pairs = {
        (
            row["domain"],
            row["canonical_key"],
        )
        for row in triage["rows"]
    }

    records: list[
        tuple[Path, dict[str, Any]]
    ] = []

    for path in sorted(
        DECISION_DIR.glob("*.yaml")
    ):
        records.append(
            (path, load_yaml(path))
        )

    validator = Draft202012Validator(schema)
    schema_errors: list[dict[str, Any]] = []

    for path, record in records:
        for error in sorted(
            validator.iter_errors(record),
            key=lambda item: list(item.path),
        ):
            schema_errors.append({
                "file": str(path),
                "path": list(error.path),
                "message": error.message,
            })

    decision_pairs = [
        (
            row["domain"],
            row["candidate_key"],
        )
        for _, row in records
    ]

    pair_counts = Counter(decision_pairs)

    duplicate_pairs = sorted(
        {
            pair
            for pair, count in pair_counts.items()
            if count > 1
        }
    )

    decisions_not_in_triage = sorted(
        set(decision_pairs) - triage_pairs
    )

    invalid_domains = sorted({
        row["domain"]
        for _, row in records
        if row["domain"] not in required_domains
    })

    decisions_by_domain = Counter(
        row["domain"]
        for _, row in records
    )

    included_by_domain = Counter(
        row["domain"]
        for _, row in records
        if row["decision"] == "INCLUDE"
    )

    included_records = [
        row
        for _, row in records
        if row["decision"] == "INCLUDE"
    ]

    gates = {
        "screening_records_schema_valid": (
            not schema_errors
        ),
        "screening_pairs_unique": (
            not duplicate_pairs
        ),
        "all_decisions_reference_triage": (
            not decisions_not_in_triage
        ),
        "all_decision_domains_registered": (
            not invalid_domains
        ),
    }

    if args.require_complete:
        gates.update({
            "screening_corpus_nonempty": bool(
                records
            ),
            "all_triage_slots_screened": (
                set(decision_pairs) == triage_pairs
            ),
            "every_domain_has_decisions": (
                required_domains
                <= set(decisions_by_domain)
            ),
            "every_domain_has_included_source": (
                required_domains
                <= set(included_by_domain)
            ),
            "all_included_sources_verified": (
                bool(included_records)
                and all(
                    row["primary_source_verified"]
                    and row["identifier_verified"]
                    and row["full_text_reviewed"]
                    and bool(row["claims_addressed"])
                    for row in included_records
                )
            ),
        })

    summary = {
        "stage": 1,
        "status": (
            "PASS"
            if all(gates.values())
            else "OPEN_FAILED_GATES"
        ),
        "triage_slot_count": len(
            triage_pairs
        ),
        "screening_decision_count": len(
            records
        ),
        "include_count": sum(
            row["decision"] == "INCLUDE"
            for _, row in records
        ),
        "exclude_count": sum(
            row["decision"] == "EXCLUDE"
            for _, row in records
        ),
        "defer_count": sum(
            row["decision"] == "DEFER"
            for _, row in records
        ),
        "decision_counts_by_domain": dict(
            sorted(decisions_by_domain.items())
        ),
        "included_counts_by_domain": dict(
            sorted(included_by_domain.items())
        ),
        "schema_errors": schema_errors,
        "duplicate_pairs": [
            {
                "domain": domain,
                "candidate_key": key,
            }
            for domain, key in duplicate_pairs
        ],
        "decisions_not_in_triage": [
            {
                "domain": domain,
                "candidate_key": key,
            }
            for domain, key
            in decisions_not_in_triage
        ],
        "invalid_domains": invalid_domains,
        "gates": gates,
        "failed_gates": [
            name
            for name, passed in gates.items()
            if not passed
        ],
    }

    summary_path = (
        args.output_dir
        / "stage1_screening_summary.json"
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path, _ in records
    ]

    (
        args.output_dir
        / "stage1_screening_manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )

    return (
        0
        if all(gates.values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
