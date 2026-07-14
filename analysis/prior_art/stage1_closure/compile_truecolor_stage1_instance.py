from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PRIOR_ART = ROOT / "analysis" / "prior_art"

CLAIM_REGISTRY = (
    PRIOR_ART
    / "registry"
    / "novelty_claim_registry.yaml"
)

PROTOCOL = (
    PRIOR_ART
    / "protocol"
    / "stage1_protocol.yaml"
)

EVIDENCE_INDEX = (
    PRIOR_ART
    / "scientific_extraction"
    / "stage1_p1_scientific_evidence_index.json"
)

SECOND_REVIEW_COHORT = (
    PRIOR_ART
    / "scientific_extraction"
    / "stage1_p1_second_review_cohort.json"
)

GOVERNED_CORPUS_MANIFEST = (
    PRIOR_ART
    / "adjudication"
    / "stage1_claim_review_cohort_final.json"
)

OUTPUT = (
    ROOT
    / "artifacts"
    / "stage_01"
    / "truecolor_stage1_instance.json"
)

ALLOWED_FIELD_STATES = [
    "ESTABLISHED_FROM_SOURCE",
    "NOT_ESTABLISHED_FROM_AVAILABLE_SOURCE",
    "PENDING_SOURCE_REVIEW",
    "NOT_APPLICABLE",
    "CONTRADICTED_WITHIN_SOURCE",
    "UNRESOLVED",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def stable_id(
    prefix: str,
    value: str,
) -> str:
    suffix = hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:16]

    return f"{prefix}-{suffix}"


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def scalar(value: str) -> Any:
    normalized = value.strip()

    if normalized == "":
        return ""

    if normalized in {"true", "false"}:
        return normalized == "true"

    if normalized in {"null", "~"}:
        return None

    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {'"', "'"}
    ):
        return normalized[1:-1]

    try:
        return int(normalized)
    except ValueError:
        return normalized


def load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        return load_simple_yaml(path)

    return yaml.safe_load(
        path.read_text(encoding="utf-8")
    )


def load_simple_yaml(path: Path) -> Any:
    text = path.read_text(
        encoding="utf-8"
    )

    if path == CLAIM_REGISTRY:
        claims: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        active_list: str | None = None
        active_text: str | None = None

        for raw_line in text.splitlines():
            stripped = raw_line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("- claim_id:"):
                if current is not None:
                    claims.append(current)

                current = {
                    "claim_id": scalar(
                        stripped.split(":", 1)[1]
                    )
                }

                active_list = None
                active_text = None
                continue

            if current is None:
                continue

            if stripped.startswith("- "):
                if active_list is not None:
                    current.setdefault(
                        active_list,
                        [],
                    ).append(
                        scalar(stripped[2:])
                    )

                continue

            if ":" in stripped:
                key, raw_value = stripped.split(
                    ":",
                    1,
                )

                key = key.strip()
                raw_value = raw_value.strip()

                if raw_value:
                    current[key] = scalar(raw_value)
                    active_list = None
                    active_text = key
                else:
                    current[key] = []
                    active_list = key
                    active_text = None

                continue

            if active_text is not None:
                previous = str(
                    current.get(active_text, "")
                )

                current[active_text] = (
                    previous + " " + stripped
                ).strip()

        if current is not None:
            claims.append(current)

        return {
            "registry_version": "1.0.0",
            "claims": claims,
        }

    protocol: dict[str, Any] = {}
    active_list: str | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if active_list is not None:
                protocol.setdefault(
                    active_list,
                    [],
                ).append(
                    scalar(stripped[2:])
                )

            continue

        if ":" in stripped:
            key, raw_value = stripped.split(
                ":",
                1,
            )

            key = key.strip()
            raw_value = raw_value.strip()

            if raw_value:
                protocol[key] = scalar(raw_value)
                active_list = None
            else:
                protocol[key] = []
                active_list = key

    return protocol


def canonical_identity_from_row(
    row: dict[str, str],
) -> str:
    preferred_keys = (
        "canonical_key",
        "canonical_identity",
        "doi",
        "pmid",
        "source_id",
        "title",
    )

    for key in preferred_keys:
        value = str(
            row.get(key, "")
        ).strip()

        if not value:
            continue

        if key == "doi":
            return "doi:" + value.lower()

        if key == "pmid":
            return "pmid:" + value

        return value

    serialized = json.dumps(
        row,
        sort_keys=True,
    )

    return stable_id(
        "unresolved",
        serialized,
    )


def extract_manifest_records(
    value: Any,
) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            record
            for record in value
            if isinstance(record, dict)
        ]

    if not isinstance(value, dict):
        return []

    preferred_keys = (
        "records",
        "papers",
        "sources",
        "cohort",
        "review_cohort",
        "claim_review_cohort",
        "items",
    )

    for key in preferred_keys:
        child = value.get(key)

        if isinstance(child, list):
            records = [
                record
                for record in child
                if isinstance(record, dict)
            ]

            if records:
                return records

    list_values = [
        child
        for child in value.values()
        if isinstance(child, list)
        and child
        and all(
            isinstance(record, dict)
            for record in child
        )
    ]

    if len(list_values) == 1:
        return list_values[0]

    return []


def load_governed_corpus() -> list[dict[str, Any]]:
    if not GOVERNED_CORPUS_MANIFEST.is_file():
        raise RuntimeError(
            "configured governed corpus manifest "
            "does not exist: "
            f"{GOVERNED_CORPUS_MANIFEST}"
        )

    manifest = read_json(
        GOVERNED_CORPUS_MANIFEST
    )

    rows = extract_manifest_records(
        manifest
    )

    if not rows:
        raise RuntimeError(
            "configured governed corpus manifest "
            "contains no identifiable records"
        )

    members: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        canonical_identity = (
            canonical_identity_from_row(row)
        )

        if canonical_identity in seen:
            continue

        seen.add(canonical_identity)

        members.append(
            {
                "corpus_member_id": stable_id(
                    "CORPUS",
                    canonical_identity,
                ),
                "canonical_identity":
                    canonical_identity,
                "membership_roles": [
                    "GOVERNED_CORPUS"
                ],
                "source_metadata": {
                    str(key): value
                    for key, value in row.items()
                    if value not in {
                        None,
                        "",
                    }
                },
            }
        )

    if not members:
        raise RuntimeError(
            "configured governed corpus became "
            "empty after identity normalization"
        )

    return members


def normalized_evidence_record(
    index_record: dict[str, Any],
    review_keys: set[str],
) -> dict[str, Any]:
    relative_path = Path(
        index_record[
            "evidence_record_path"
        ]
    )

    path = ROOT / relative_path
    raw = read_json(path)

    canonical_identity = str(
        raw.get(
            "canonical_key",
            index_record.get(
                "canonical_key",
                "",
            ),
        )
    ).strip()

    source_id = stable_id(
        "SRC",
        canonical_identity,
    )

    evidence_record_id = stable_id(
        "EVID",
        canonical_identity,
    )

    field_observations = []

    for field_id, field in sorted(
        raw.get("fields", {}).items()
    ):
        if not isinstance(field, dict):
            continue

        field_observations.append(
            {
                "field_id": field_id,
                "state": field.get(
                    "state",
                    "UNRESOLVED",
                ),
                "value": field.get("value"),
                "evidence_spans": field.get(
                    "evidence",
                    [],
                ),
                "review_notes": field.get(
                    "review_notes"
                ),
            }
        )

    quality = raw.get(
        "quality_control",
        {},
    )

    source = raw.get("source", {})

    bindings = []

    for binding_type, binding_path in (
        (
            "SOURCE_OBJECT",
            source.get("local_source_path"),
        ),
        (
            "NORMALIZED_TEXT",
            source.get("local_text_path"),
        ),
        (
            "REVIEW_PACKET",
            source.get("review_packet_path"),
        ),
        (
            "EVIDENCE_SELECTION",
            raw.get(
                "primary_extraction_evidence_selection"
            ),
        ),
    ):
        if not binding_path:
            continue

        candidate = ROOT / binding_path

        bindings.append(
            {
                "binding_type": binding_type,
                "path": binding_path,
                "exists": candidate.is_file(),
                "sha256": (
                    sha256_file(candidate)
                    if candidate.is_file()
                    else None
                ),
            }
        )

    return {
        "evidence_record_id":
            evidence_record_id,
        "source_id": source_id,
        "canonical_identity":
            canonical_identity,
        "title": raw.get("title"),
        "doi": raw.get("doi"),
        "record_path":
            relative_path.as_posix(),
        "record_sha256":
            sha256_file(path),
        "claim_ids":
            list(raw.get("claim_ids", [])),
        "extraction_scope":
            raw.get("extraction_scope"),
        "scientific_content_state":
            raw.get(
                "scientific_content_state"
            ),
        "review_eligibility":
            raw.get("review_eligibility"),
        "terminal_source_state":
            raw.get(
                "terminal_source_state"
            ),
        "field_observations":
            field_observations,
        "claim_observations":
            raw.get(
                "truecolor_claim_overlap",
                [],
            ),
        "source_bindings": bindings,
        "review_state": {
            "primary_review_completed":
                bool(
                    quality.get(
                        "primary_review_completed"
                    )
                ),
            "primary_reviewer":
                quality.get(
                    "primary_reviewer"
                ),
            "second_review_required": (
                canonical_identity
                in review_keys
            ),
            "second_review_completed":
                bool(
                    quality.get(
                        "second_review_completed"
                    )
                ),
            "second_reviewer":
                quality.get(
                    "second_reviewer"
                ),
            "final_review_state":
                quality.get(
                    "final_review_state"
                ),
            "discrepancies":
                quality.get(
                    "discrepancies",
                    [],
                ),
        },
    }


def main() -> None:
    claims_document = load_yaml(
        CLAIM_REGISTRY
    )

    protocol_document = load_yaml(
        PROTOCOL
    )

    evidence_index = read_json(
        EVIDENCE_INDEX
    )

    review_cohort = read_json(
        SECOND_REVIEW_COHORT
    )

    if not isinstance(evidence_index, list):
        raise RuntimeError(
            "scientific evidence index must be a list"
        )

    if not isinstance(review_cohort, list):
        raise RuntimeError(
            "second-review cohort must be a list"
        )

    claims = claims_document.get(
        "claims",
        [],
    )

    review_keys = {
        str(record.get("canonical_key", ""))
        for record in review_cohort
    }

    evidence_records = [
        normalized_evidence_record(
            record,
            review_keys,
        )
        for record in evidence_index
    ]

    governed_members = (
        load_governed_corpus()
    )

    governed_by_identity = {
        member["canonical_identity"]:
            member
        for member in governed_members
    }

    for evidence in evidence_records:
        canonical_identity = evidence[
            "canonical_identity"
        ]

        member = governed_by_identity.get(
            canonical_identity
        )

        if member is None:
            member = {
                "corpus_member_id": stable_id(
                    "CORPUS",
                    canonical_identity,
                ),
                "canonical_identity":
                    canonical_identity,
                "membership_roles": [
                    "GOVERNED_CORPUS",
                    "PRIORITY_ADJUDICATION",
                ],
                "source_metadata": {
                    "title":
                        evidence.get("title"),
                    "doi":
                        evidence.get("doi"),
                },
            }

            governed_members.append(member)
            governed_by_identity[
                canonical_identity
            ] = member
        elif (
            "PRIORITY_ADJUDICATION"
            not in member[
                "membership_roles"
            ]
        ):
            member[
                "membership_roles"
            ].append(
                "PRIORITY_ADJUDICATION"
            )

    field_ids = sorted(
        {
            observation["field_id"]
            for record in evidence_records
            for observation
            in record["field_observations"]
        }
    )

    instance = {
        "schema_id":
            "qudipi.stage1.compiled-instance",
        "schema_version": 1,
        "research_pack_id": "skin_photon",
        "study_id": "truecolor",
        "protocol": {
            "path":
                PROTOCOL.relative_to(
                    ROOT
                ).as_posix(),
            "sha256":
                sha256_file(PROTOCOL),
            "document":
                protocol_document,
        },
        "corpus": {
            "members":
                sorted(
                    governed_members,
                    key=lambda member: (
                        member[
                            "canonical_identity"
                        ]
                    ),
                ),
            "membership_roles": [
                "GOVERNED_CORPUS",
                "PRIORITY_ADJUDICATION",
                "DEEP_REVIEW",
                "MATERIAL_LINEAGE_REFERENCE",
                "EXCLUDED_WITH_REASON",
            ],
        },
        "claims": claims,
        "evidence_schema": {
            "schema_id":
                "truecolor.stage1.scientific-evidence",
            "schema_version": 1,
            "field_ids": field_ids,
            "allowed_field_states":
                ALLOWED_FIELD_STATES,
        },
        "evidence_records":
            evidence_records,
        "review_policy": {
            "policy_id":
                "truecolor-stage1-review-policy",
            "primary_review": {
                "required_when": {
                    "review_eligibility": [
                        "COMPLETE",
                        "BOUNDED",
                    ],
                    "primary_review_completed":
                        False,
                }
            },
            "independent_second_review": {
                "required_source_ids": [
                    record["source_id"]
                    for record
                    in evidence_records
                    if record[
                        "review_state"
                    ][
                        "second_review_required"
                    ]
                ],
                "independence_required": True,
            },
        },
        "closure_contract": {
            "requirements":
                protocol_document.get(
                    "closure_requirements",
                    [],
                ),
            "full_governed_corpus_coverage_required":
                True,
            "all_registered_claims_adjudicated_required":
                True,
            "all_required_reviews_completed_required":
                True,
            "novelty_kill_decisions_required":
                True,
            "framing_synthesis_required":
                True,
            "lineage_synthesis_required":
                True,
            "contradiction_synthesis_required":
                True,
            "novelty_frontier_required":
                True,
            "artifact_hashes_required":
                True,
        },
        "source_authorities": {
            "claim_registry": {
                "path":
                    CLAIM_REGISTRY.relative_to(
                        ROOT
                    ).as_posix(),
                "sha256":
                    sha256_file(
                        CLAIM_REGISTRY
                    ),
            },
            "evidence_index": {
                "path":
                    EVIDENCE_INDEX.relative_to(
                        ROOT
                    ).as_posix(),
                "sha256":
                    sha256_file(
                        EVIDENCE_INDEX
                    ),
            },
            "second_review_cohort": {
                "path":
                    SECOND_REVIEW_COHORT.relative_to(
                        ROOT
                    ).as_posix(),
                "sha256":
                    sha256_file(
                        SECOND_REVIEW_COHORT
                    ),
            },
            "governed_corpus": {
                "path": (
                    GOVERNED_CORPUS_MANIFEST
                    .relative_to(ROOT)
                    .as_posix()
                ),
                "exists":
                    GOVERNED_CORPUS_MANIFEST.is_file(),
                "sha256": (
                    sha256_file(
                        GOVERNED_CORPUS_MANIFEST
                    )
                    if GOVERNED_CORPUS_MANIFEST.is_file()
                    else None
                ),
            },
        },
    }

    write_json(OUTPUT, instance)

    governed_count = len(
        instance["corpus"]["members"]
    )

    evidence_count = len(
        instance["evidence_records"]
    )

    claim_count = len(
        instance["claims"]
    )

    required_second_reviews = len(
        instance[
            "review_policy"
        ][
            "independent_second_review"
        ][
            "required_source_ids"
        ]
    )

    print(
        "QUDIPI_TRUECOLOR_STAGE1_INSTANCE=PASS"
    )

    print(
        f"governed_corpus_count={governed_count}"
    )

    print(
        f"evidence_record_count={evidence_count}"
    )

    print(
        f"claim_count={claim_count}"
    )

    print(
        "required_second_review_count="
        f"{required_second_reviews}"
    )

    print(
        "full_corpus_evidence_coverage="
        f"{evidence_count}/{governed_count}"
    )


if __name__ == "__main__":
    main()
