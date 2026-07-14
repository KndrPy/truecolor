from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile Stage 1 corpus coverage using "
            "explicit existing-artifact dispositions."
        )
    )

    parser.add_argument(
        "--manifest",
        required=True,
    )

    parser.add_argument(
        "--coverage",
        required=True,
    )

    parser.add_argument(
        "--source-config",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
    )

    return parser.parse_args()


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
    *values: str,
) -> str:
    material = "\x1f".join(values)

    suffix = hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:16]

    return f"{prefix}-{suffix}"


def normalize_value(value: Any) -> str:
    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def normalize_identity(
    field: str,
    value: Any,
) -> str | None:
    raw = str(value or "").strip()

    if not raw:
        return None

    normalized_field = field.lower()

    if normalized_field == "doi":
        doi = raw.lower()

        for prefix in (
            "https://doi.org/",
            "http://doi.org/",
            "doi:",
        ):
            if doi.startswith(prefix):
                doi = doi[len(prefix):]

        return f"doi:{doi}"

    if normalized_field == "pmid":
        pmid = raw

        if pmid.lower().startswith("pmid:"):
            pmid = pmid.split(":", 1)[1]

        return f"pmid:{pmid}"

    return raw


def flatten_json_records(
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

    preferred = (
        "records",
        "sources",
        "papers",
        "items",
        "cohort",
        "review_cohort",
        "claim_review_cohort",
        "statuses",
    )

    for key in preferred:
        child = value.get(key)

        if isinstance(child, list):
            records = [
                record
                for record in child
                if isinstance(record, dict)
            ]

            if records:
                return records

    candidate_lists = [
        child
        for child in value.values()
        if isinstance(child, list)
        and child
        and all(
            isinstance(record, dict)
            for record in child
        )
    ]

    if len(candidate_lists) == 1:
        return candidate_lists[0]

    return []


def load_records(
    path: Path,
    source_format: str,
) -> list[dict[str, Any]]:
    if source_format == "json":
        return flatten_json_records(
            read_json(path)
        )

    if source_format == "csv":
        with path.open(
            newline="",
            encoding="utf-8",
        ) as handle:
            return list(
                csv.DictReader(handle)
            )

    raise RuntimeError(
        f"unsupported disposition source format: "
        f"{source_format}"
    )


def first_present(
    record: dict[str, Any],
    fields: list[str],
) -> tuple[str | None, Any]:
    lookup = {
        str(key).strip().lower():
            value
        for key, value in record.items()
    }

    for field in fields:
        key = field.strip().lower()

        if key not in lookup:
            continue

        value = lookup[key]

        if value not in {
            None,
            "",
        }:
            return field, value

    return None, None


def record_identity(
    record: dict[str, Any],
    fields: list[str],
) -> tuple[str | None, str | None]:
    for field in fields:
        lookup = {
            str(key).strip().lower():
                value
            for key, value in record.items()
        }

        key = field.strip().lower()

        if key not in lookup:
            continue

        identity = normalize_identity(
            field,
            lookup[key],
        )

        if identity:
            return field, identity

    return None, None


def canonical_alias_map(
    aliases: dict[str, list[str]],
) -> dict[str, str]:
    result: dict[str, str] = {}

    for role, values in aliases.items():
        result[
            normalize_value(role)
        ] = role

        for value in values:
            result[
                normalize_value(value)
            ] = role

    return result


def rebuild_hashes(
    output_directory: Path,
) -> None:
    hash_path = (
        output_directory
        / "artifact_hashes.json"
    )

    hashes: dict[str, str] = {}

    for path in sorted(
        output_directory.rglob("*.json")
    ):
        if path == hash_path:
            continue

        hashes[
            path.relative_to(
                ROOT
            ).as_posix()
        ] = sha256_file(path)

    write_json(
        hash_path,
        hashes,
    )


def main() -> int:
    args = arguments()

    manifest_path = Path(
        args.manifest
    ).resolve()

    coverage_path = Path(
        args.coverage
    ).resolve()

    source_config_path = Path(
        args.source_config
    ).resolve()

    output_directory = Path(
        args.output
    ).resolve()

    manifest = read_json(
        manifest_path
    )

    coverage = read_json(
        coverage_path
    )

    source_config = read_json(
        source_config_path
    )

    alias_map = canonical_alias_map(
        source_config["role_aliases"]
    )

    reason_required_roles = set(
        source_config[
            "reason_required_roles"
        ]
    )

    governed_identities = {
        member["canonical_identity"]
        for member
        in manifest["corpus"]["members"]
    }

    observations_by_identity: dict[
        str,
        list[dict[str, Any]],
    ] = {
        identity: []
        for identity in governed_identities
    }

    source_reports: list[
        dict[str, Any]
    ] = []

    for source in sorted(
        source_config["sources"],
        key=lambda item: int(
            item["precedence"]
        ),
    ):
        path = (
            ROOT / source["path"]
        )

        if not path.is_file():
            source_reports.append(
                {
                    "source_id":
                        source["source_id"],
                    "path":
                        source["path"],
                    "exists": False,
                    "sha256": None,
                    "record_count": 0,
                    "matched_governed_count": 0,
                }
            )
            continue

        records = load_records(
            path,
            source["format"],
        )

        matched_count = 0

        for index, record in enumerate(
            records
        ):
            identity_field, identity = (
                record_identity(
                    record,
                    source[
                        "identity_fields"
                    ],
                )
            )

            if (
                identity is None
                or identity
                not in governed_identities
            ):
                continue

            disposition_field, raw_value = (
                first_present(
                    record,
                    source[
                        "disposition_fields"
                    ],
                )
            )

            if disposition_field is None:
                continue

            matched_count += 1

            normalized_disposition = (
                normalize_value(raw_value)
            )

            mapped_role = alias_map.get(
                normalized_disposition
            )

            reason_field, raw_reason = (
                first_present(
                    record,
                    source[
                        "reason_fields"
                    ],
                )
            )

            reason = (
                str(raw_reason).strip()
                if raw_reason not in {
                    None,
                    "",
                }
                else None
            )

            observation_state = (
                "MAPPED"
                if mapped_role is not None
                else "UNMAPPED"
            )

            if (
                mapped_role
                in reason_required_roles
                and not reason
            ):
                observation_state = (
                    "INVALID_MISSING_REASON"
                )

            observations_by_identity[
                identity
            ].append(
                {
                    "observation_id":
                        stable_id(
                            "DISPOSITION-EVIDENCE",
                            source["source_id"],
                            identity,
                            str(index),
                        ),
                    "source_id":
                        source["source_id"],
                    "source_path":
                        source["path"],
                    "source_sha256":
                        sha256_file(path),
                    "source_precedence":
                        int(
                            source["precedence"]
                        ),
                    "source_record_index":
                        index,
                    "identity_field":
                        identity_field,
                    "canonical_identity":
                        identity,
                    "disposition_field":
                        disposition_field,
                    "raw_disposition":
                        raw_value,
                    "normalized_disposition":
                        normalized_disposition,
                    "mapped_role":
                        mapped_role,
                    "reason_field":
                        reason_field,
                    "reason":
                        reason,
                    "observation_state":
                        observation_state,
                }
            )

        source_reports.append(
            {
                "source_id":
                    source["source_id"],
                "path":
                    source["path"],
                "exists": True,
                "sha256":
                    sha256_file(path),
                "record_count":
                    len(records),
                "matched_governed_count":
                    matched_count,
            }
        )

    original_records = {
        record["canonical_identity"]:
            record
        for record in coverage["records"]
    }

    reconciled_records: list[
        dict[str, Any]
    ] = []

    evidence_records: list[
        dict[str, Any]
    ] = []

    conflict_records: list[
        dict[str, Any]
    ] = []

    unmapped_records: list[
        dict[str, Any]
    ] = []

    invalid_records: list[
        dict[str, Any]
    ] = []

    resolved_count = 0

    for identity in sorted(
        governed_identities
    ):
        original = original_records[
            identity
        ]

        observations = sorted(
            observations_by_identity[
                identity
            ],
            key=lambda item: (
                item[
                    "source_precedence"
                ],
                item["source_id"],
                item[
                    "source_record_index"
                ],
            ),
        )

        evidence_records.extend(
            observations
        )

        if (
            original[
                "coverage_state"
            ]
            == "TERMINAL"
        ):
            reconciled_records.append(
                original
            )
            continue

        mapped = [
            observation
            for observation in observations
            if observation[
                "observation_state"
            ]
            == "MAPPED"
        ]

        invalid = [
            observation
            for observation in observations
            if observation[
                "observation_state"
            ]
            == "INVALID_MISSING_REASON"
        ]

        unmapped = [
            observation
            for observation in observations
            if observation[
                "observation_state"
            ]
            == "UNMAPPED"
        ]

        mapped_roles = {
            observation["mapped_role"]
            for observation in mapped
        }

        if invalid:
            invalid_records.append(
                {
                    "canonical_identity":
                        identity,
                    "observations":
                        invalid,
                }
            )

        if unmapped:
            unmapped_records.append(
                {
                    "canonical_identity":
                        identity,
                    "observations":
                        unmapped,
                }
            )

        if len(mapped_roles) > 1:
            conflict_records.append(
                {
                    "canonical_identity":
                        identity,
                    "mapped_roles":
                        sorted(mapped_roles),
                    "observations":
                        mapped,
                }
            )

            reconciled_records.append(
                {
                    **original,
                    "coverage_state":
                        "PENDING",
                    "coverage_role":
                        "REVIEW_DISPOSITION_REQUIRED",
                    "coverage_reason":
                        None,
                    "derivation": {
                        "method":
                            "conflicting_explicit_"
                            "dispositions",
                    },
                }
            )
            continue

        if (
            len(mapped_roles) == 1
            and not invalid
        ):
            selected = mapped[0]
            selected_role = selected[
                "mapped_role"
            ]

            resolved_count += 1

            reconciled_records.append(
                {
                    **original,
                    "coverage_state":
                        "TERMINAL",
                    "coverage_role":
                        selected_role,
                    "coverage_reason":
                        selected["reason"],
                    "derivation": {
                        "method":
                            "explicit_existing_"
                            "artifact_disposition",
                        "observation_id":
                            selected[
                                "observation_id"
                            ],
                        "source_id":
                            selected[
                                "source_id"
                            ],
                        "source_path":
                            selected[
                                "source_path"
                            ],
                        "source_sha256":
                            selected[
                                "source_sha256"
                            ],
                        "disposition_field":
                            selected[
                                "disposition_field"
                            ],
                        "raw_disposition":
                            selected[
                                "raw_disposition"
                            ],
                    },
                }
            )
            continue

        reconciled_records.append(
            original
        )

    terminal_count = sum(
        1
        for record in reconciled_records
        if record[
            "coverage_state"
        ]
        == "TERMINAL"
    )

    pending_count = sum(
        1
        for record in reconciled_records
        if record[
            "coverage_state"
        ]
        == "PENDING"
    )

    role_counts: dict[str, int] = {}

    for record in reconciled_records:
        role = record[
            "coverage_role"
        ]

        role_counts[role] = (
            role_counts.get(role, 0)
            + 1
        )

    evidence_register_path = (
        output_directory
        / "corpus_disposition_evidence_register.json"
    )

    reconciliation_report_path = (
        output_directory
        / "corpus_disposition_reconciliation_report.json"
    )

    conflict_report_path = (
        output_directory
        / "corpus_disposition_conflict_report.json"
    )

    unmapped_report_path = (
        output_directory
        / "corpus_disposition_unmapped_report.json"
    )

    write_json(
        evidence_register_path,
        {
            "register_schema":
                "qudipi.stage1.corpus-disposition-evidence-register",
            "register_version": 1,
            "source_config_id":
                source_config["config_id"],
            "source_config_path":
                source_config_path.relative_to(
                    ROOT
                ).as_posix(),
            "source_config_sha256":
                sha256_file(
                    source_config_path
                ),
            "source_reports":
                source_reports,
            "observation_count":
                len(evidence_records),
            "observations":
                evidence_records,
        },
    )

    write_json(
        reconciliation_report_path,
        {
            "report_schema":
                "qudipi.stage1.corpus-disposition-reconciliation-report",
            "report_version": 1,
            "configured_governed_source_count":
                len(governed_identities),
            "previous_terminal_count":
                coverage[
                    "terminal_coverage_count"
                ],
            "resolved_from_existing_artifacts":
                resolved_count,
            "terminal_coverage_count":
                terminal_count,
            "pending_disposition_count":
                pending_count,
            "conflict_count":
                len(conflict_records),
            "unmapped_identity_count":
                len(unmapped_records),
            "invalid_identity_count":
                len(invalid_records),
            "role_counts":
                role_counts,
        },
    )

    write_json(
        conflict_report_path,
        {
            "report_schema":
                "qudipi.stage1.corpus-disposition-conflict-report",
            "report_version": 1,
            "conflict_count":
                len(conflict_records),
            "invalid_count":
                len(invalid_records),
            "conflicts":
                conflict_records,
            "invalid_records":
                invalid_records,
        },
    )

    write_json(
        unmapped_report_path,
        {
            "report_schema":
                "qudipi.stage1.corpus-disposition-unmapped-report",
            "report_version": 1,
            "identity_count":
                len(unmapped_records),
            "records":
                unmapped_records,
        },
    )

    coverage[
        "records"
    ] = reconciled_records

    coverage[
        "terminal_coverage_count"
    ] = terminal_count

    coverage[
        "pending_disposition_count"
    ] = pending_count

    coverage[
        "invalid_disposition_count"
    ] = len(invalid_records)

    coverage[
        "role_counts"
    ] = role_counts

    coverage[
        "disposition_reconciliation_config_id"
    ] = source_config["config_id"]

    write_json(
        coverage_path,
        coverage,
    )

    coverage_gap_path = (
        output_directory
        / "corpus_coverage_gap_report.json"
    )

    coverage_gap = read_json(
        coverage_gap_path
    )

    coverage_gap[
        "terminal_coverage_count"
    ] = terminal_count

    coverage_gap[
        "pending_disposition_count"
    ] = pending_count

    coverage_gap[
        "invalid_disposition_count"
    ] = len(invalid_records)

    coverage_gap[
        "stage_state"
    ] = (
        "COMPLETE"
        if (
            pending_count == 0
            and not conflict_records
            and not invalid_records
        )
        else "OPEN"
    )

    coverage_gap[
        "pending_corpus_members"
    ] = [
        {
            "coverage_record_id":
                record[
                    "coverage_record_id"
                ],
            "corpus_member_id":
                record[
                    "corpus_member_id"
                ],
            "canonical_identity":
                record[
                    "canonical_identity"
                ],
            "coverage_role":
                record[
                    "coverage_role"
                ],
        }
        for record in reconciled_records
        if record[
            "coverage_state"
        ]
        == "PENDING"
    ]

    write_json(
        coverage_gap_path,
        coverage_gap,
    )

    stage_gap_path = (
        output_directory
        / "stage1_gap_report.json"
    )

    stage_gap = read_json(
        stage_gap_path
    )

    blockers = [
        blocker
        for blocker in stage_gap[
            "remaining_blockers"
        ]
        if blocker
        not in {
            "governed_corpus_terminal_disposition",
            "invalid_corpus_dispositions",
            "conflicting_corpus_dispositions",
            "unmapped_explicit_corpus_dispositions",
        }
    ]

    if pending_count:
        blockers.append(
            "governed_corpus_terminal_disposition"
        )

    if conflict_records:
        blockers.append(
            "conflicting_corpus_dispositions"
        )

    if invalid_records:
        blockers.append(
            "invalid_corpus_dispositions"
        )

    if unmapped_records:
        blockers.append(
            "unmapped_explicit_corpus_dispositions"
        )

    stage_gap[
        "remaining_blockers"
    ] = list(
        dict.fromkeys(blockers)
    )

    stage_gap[
        "terminal_coverage_count"
    ] = terminal_count

    stage_gap[
        "pending_corpus_disposition_count"
    ] = pending_count

    stage_gap[
        "corpus_disposition_conflict_count"
    ] = len(conflict_records)

    stage_gap[
        "unmapped_explicit_disposition_count"
    ] = len(unmapped_records)

    stage_gap[
        "invalid_corpus_disposition_count"
    ] = len(invalid_records)

    write_json(
        stage_gap_path,
        stage_gap,
    )

    rebuild_hashes(
        output_directory
    )

    print(
        "QUDIPI_STAGE1_DISPOSITION_RECONCILIATION=PASS"
    )

    print(
        "configured_governed_source_count="
        f"{len(governed_identities)}"
    )

    print(
        "resolved_from_existing_artifacts="
        f"{resolved_count}"
    )

    print(
        "terminal_coverage_count="
        f"{terminal_count}"
    )

    print(
        "pending_disposition_count="
        f"{pending_count}"
    )

    print(
        "conflict_count="
        f"{len(conflict_records)}"
    )

    print(
        "unmapped_identity_count="
        f"{len(unmapped_records)}"
    )

    print(
        "invalid_identity_count="
        f"{len(invalid_records)}"
    )

    return 0


if __name__ == "__main__":
    main()
