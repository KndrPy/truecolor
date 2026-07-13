from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


DEFAULT_INPUT = Path(
    "analysis/prior_art/results/"
    "stage1_candidate_harvest.json"
)

DEFAULT_OUTPUT = Path(
    "analysis/prior_art/results/"
    "stage1_screening_queue.csv"
)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    args = parser.parse_args()

    payload = json.loads(
        args.input.read_text(encoding="utf-8")
    )

    rows = []

    for index, candidate in enumerate(
        payload["candidates"],
        start=1,
    ):
        rows.append({
            "candidate_rank": index,
            "canonical_key": candidate[
                "canonical_key"
            ],
            "title": candidate.get(
                "title",
                "",
            ),
            "year": candidate.get(
                "year",
                "",
            ),
            "authors": " | ".join(
                candidate.get("authors", [])
            ),
            "doi": candidate.get(
                "doi",
                "",
            ) or "",
            "pmid": candidate.get(
                "pmid",
                "",
            ) or "",
            "venue": candidate.get(
                "venue",
                "",
            ) or "",
            "citation_count": candidate.get(
                "citation_count",
                "",
            ) or "",
            "domains": " | ".join(
                candidate.get("domains", [])
            ),
            "query_family_ids": " | ".join(
                candidate.get(
                    "query_family_ids",
                    [],
                )
            ),
            "primary_source_verified": "",
            "publication_status_verified": "",
            "include_exclude": "",
            "exclusion_reason": "",
            "claims_addressed": "",
            "screening_notes": "",
        })

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with args.output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0])
            if rows
            else [
                "candidate_rank",
                "canonical_key",
                "title",
            ],
            lineterminator="\n",
        )

        writer.writeheader()
        writer.writerows(rows)

    print(
        f"SCREENING_ROWS={len(rows)}"
    )
    print(
        f"SCREENING_QUEUE={args.output}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
