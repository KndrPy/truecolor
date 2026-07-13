from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("analysis/prior_art")

DEFAULT_RANKING = (
    ROOT
    / "evidence/ranking/"
    "stage1_complete_global_ranking.json"
)

DEFAULT_OUTPUT = (
    ROOT
    / "corpus/identity_verifications"
)

DEFAULT_MANIFEST = (
    ROOT
    / "evidence/verification/"
    "stage1_identity_queue_manifest.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def slug(value: str) -> str:
    rendered = re.sub(
        r"[^a-z0-9]+",
        "-",
        value.lower(),
    ).strip("-")

    return rendered[:60] or "untitled"


def identifier(
    row: dict[str, Any],
) -> dict[str, str | None]:
    return {
        "doi": row.get("doi"),
        "pmid": row.get("pmid"),
        "pmcid": None,
        "arxiv": row.get("arxiv"),
        "isbn": None,
        "patent": None,
        "official_document_id": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--ranking",
        type=Path,
        default=DEFAULT_RANKING,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )

    args = parser.parse_args()

    ranking = json.loads(
        args.ranking.read_text(
            encoding="utf-8"
        )
    )

    rows = ranking["rows"]

    assert len(rows) == 1303

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = []

    for row in rows:
        filename = (
            f"global-{row['global_rank']:04d}__"
            f"{slug(row['title'])}.yaml"
        )

        path = args.output_dir / filename

        harvested_title = str(
            row.get("title") or ""
        )

        harvest_metadata_issues = []

        if not harvested_title.strip():
            harvest_metadata_issues.append(
                "MISSING_HARVESTED_TITLE"
            )

        if not row.get("authors"):
            harvest_metadata_issues.append(
                "MISSING_HARVESTED_AUTHORS"
            )

        if row.get("year") is None:
            harvest_metadata_issues.append(
                "MISSING_HARVESTED_YEAR"
            )

        if not row.get("venue"):
            harvest_metadata_issues.append(
                "MISSING_HARVESTED_VENUE"
            )

        if not any([
            row.get("doi"),
            row.get("pmid"),
            row.get("arxiv"),
        ]):
            harvest_metadata_issues.append(
                "MISSING_CANONICAL_IDENTIFIER"
            )

        record = {
            "candidate_key": row[
                "canonical_key"
            ],
            "global_rank": row[
                "global_rank"
            ],
            "harvested_title": harvested_title,
            "harvest_metadata_issues": (
                harvest_metadata_issues
            ),
            "verification_state": (
                "UNVERIFIED"
            ),
            "canonical_identifier": (
                identifier(row)
            ),
            "canonical_title": None,
            "canonical_authors": [],
            "canonical_year": None,
            "canonical_venue": None,
            "publication_type": None,
            "publication_status": "UNKNOWN",
            "version_relationship": (
                "UNRESOLVED"
            ),
            "related_candidate_keys": [],
            "identity_checks": {
                "canonical_identifier_resolves": None,
                "normalized_title_matches": None,
                "publication_year_matches": None,
                "authorship_matches": None,
                "publication_venue_matches": None,
                "publication_type_resolved": None,
                "publication_status_resolved": None,
                "duplicate_version_relationship_resolved": None,
                "correction_or_retraction_status_resolved": None,
            },
            "authoritative_sources": [],
            "conflicts": [],
            "reviewer": "UNASSIGNED",
            "review_notes": [
                (
                    "Generated from complete global ranking; "
                    "no identity verification has yet occurred."
                )
            ],
        }

        rendered = yaml.safe_dump(
            record,
            sort_keys=False,
            width=100,
        )

        if path.exists():
            current = path.read_text(
                encoding="utf-8"
            )

            if current != rendered:
                raise RuntimeError(
                    f"EXISTING_RECORD_DIFFERS={path}"
                )
        else:
            path.write_text(
                rendered,
                encoding="utf-8",
            )

        generated.append({
            "candidate_key": row[
                "canonical_key"
            ],
            "global_rank": row[
                "global_rank"
            ],
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })

    manifest = {
        "stage": 1,
        "artifact": (
            "complete_identity_verification_queue"
        ),
        "candidate_count": len(rows),
        "record_count": len(generated),
        "initial_verification_state": (
            "UNVERIFIED"
        ),
        "ranking_input": {
            "path": str(args.ranking),
            "bytes": args.ranking.stat().st_size,
            "sha256": sha256(args.ranking),
        },
        "records": generated,
    }

    args.manifest.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.manifest.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"IDENTITY_QUEUE_RECORDS="
        f"{len(generated)}"
    )
    print(
        "INITIAL_VERIFICATION_STATE="
        "UNVERIFIED"
    )
    print(
        f"MANIFEST={args.manifest}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
