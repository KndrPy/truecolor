from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

PRIOR_ART = ROOT / "analysis" / "prior_art"
STAGE1 = ROOT / "artifacts" / "stage_01"
MATRIX_DIRECTORY = STAGE1 / "claim_matrices"

PROTOCOL_PATH = (
    PRIOR_ART / "protocol" / "stage1_protocol.yaml"
)

CLAIM_REGISTRY_PATH = (
    PRIOR_ART
    / "registry"
    / "novelty_claim_registry.yaml"
)

CLAIM_SCHEMA_PATH = (
    PRIOR_ART
    / "schemas"
    / "claim_overlap.schema.json"
)

EVIDENCE_INDEX_PATH = (
    PRIOR_ART
    / "scientific_extraction"
    / "stage1_p1_scientific_evidence_index.json"
)

SECOND_REVIEW_PATH = (
    PRIOR_ART
    / "scientific_extraction"
    / "stage1_p1_second_review_cohort.json"
)

PAPER_DIRECTORY = (
    PRIOR_ART
    / "scientific_extraction"
    / "p1"
)

SOURCE_REGISTER_PATH = (
    STAGE1 / "source_register.json"
)

EVIDENCE_REGISTER_PATH = (
    STAGE1 / "evidence_register.json"
)

SECOND_REVIEW_REGISTER_PATH = (
    STAGE1 / "second_review_register.json"
)

CLAIM_REGISTER_PATH = (
    STAGE1 / "claim_register.json"
)

MATRIX_REGISTER_PATH = (
    STAGE1 / "claim_matrix_register.json"
)

KILL_REGISTER_PATH = (
    STAGE1 / "novelty_kill_register.json"
)

UNSUPPORTED_REGISTER_PATH = (
    STAGE1 / "unsupported_field_register.json"
)

GAP_REPORT_PATH = (
    STAGE1 / "stage1_gap_report.json"
)

RUN_MANIFEST_PATH = (
    STAGE1 / "stage1_semantic_ledger_run.json"
)

HASH_MANIFEST_PATH = (
    STAGE1 / "artifact_hashes.json"
)

CLAIM_ID_PATTERN = re.compile(
    r"^TC-NOV-[0-9]{3}$"
)

SOURCE_ID_PATTERN = re.compile(
    r"^PA-[0-9]{4}$"
)

PAPER_FILE_PATTERN = re.compile(
    r"^paper-([0-9]{2})-scientific-evidence\.json$"
)

ALLOWED_OVERLAP_STATES = {
    "NO_MATERIAL_OVERLAP",
    "BACKGROUND_ONLY",
    "COMPONENT_OVERLAP",
    "SUBSTANTIAL_OVERLAP",
    "ANTICIPATED_BY_PRIOR_ART",
    "POTENTIALLY_NOVEL_COMBINATION",
    "POTENTIALLY_NOVEL_ESTIMAND",
    "POTENTIALLY_NOVEL_VALIDATION",
    "UNRESOLVED",
}

TERMINAL_CLAIM_STATES = {
    "NO_MATERIAL_OVERLAP",
    "BACKGROUND_ONLY",
    "COMPONENT_OVERLAP",
    "SUBSTANTIAL_OVERLAP",
    "ANTICIPATED_BY_PRIOR_ART",
    "POTENTIALLY_NOVEL_COMBINATION",
    "POTENTIALLY_NOVEL_ESTIMAND",
    "POTENTIALLY_NOVEL_VALIDATION",
}

COMPLETE_PRIMARY_RECORD_STATES = {
    "PRIMARY_SCIENTIFIC_EXTRACTION_COMPLETE",
}

SOURCE_LIMITED_RECORD_STATES = {
    "INITIALIZED_NOT_REVIEWED",
}

SUPPORTED_FIELD_STATES = {
    "ESTABLISHED_FROM_SOURCE",
    "NOT_ESTABLISHED_FROM_AVAILABLE_SOURCE",
    "PENDING_SOURCE_REVIEW",
}

EXPECTED_PAPER_COUNT = 16
EXPECTED_SECOND_REVIEW_COUNT = 5
EXPECTED_CLAIM_COUNT = 6


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


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


def git_value(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def parse_scalar(value: str) -> Any:
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


def parse_claim_registry(
    path: Path,
) -> list[dict[str, Any]]:
    lines = path.read_text(
        encoding="utf-8"
    ).splitlines()

    claims: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    active_list_key: str | None = None
    active_multiline_key: str | None = None

    for raw_line in lines:
        stripped = raw_line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- claim_id:"):
            if current is not None:
                claims.append(current)

            current = {
                "claim_id": parse_scalar(
                    stripped.split(":", 1)[1]
                )
            }

            active_list_key = None
            active_multiline_key = None
            continue

        if current is None:
            continue

        indentation = len(raw_line) - len(
            raw_line.lstrip()
        )

        if stripped.startswith("- "):
            if active_list_key is not None:
                current.setdefault(
                    active_list_key,
                    [],
                ).append(
                    parse_scalar(stripped[2:])
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
                current[key] = parse_scalar(
                    raw_value
                )
                active_list_key = None
                active_multiline_key = key
            else:
                current[key] = []
                active_list_key = key
                active_multiline_key = None

            continue

        if (
            indentation >= 4
            and active_multiline_key is not None
        ):
            previous = str(
                current.get(
                    active_multiline_key,
                    "",
                )
            )

            current[active_multiline_key] = (
                previous + " " + stripped
            ).strip()

    if current is not None:
        claims.append(current)

    return claims


def source_id_from_order(
    acquisition_order: int,
) -> str:
    return f"PA-{acquisition_order:04d}"


def evidence_id_from_order(
    acquisition_order: int,
) -> str:
    return f"PA-EVID-{acquisition_order:04d}"


def review_id_from_order(
    second_review_order: int,
) -> str:
    return f"PA-REVIEW-{second_review_order:02d}"


def matrix_id_from_claim(
    claim_id: str,
) -> str:
    suffix = claim_id.rsplit("-", 1)[-1]
    return f"PA-MATRIX-{suffix}"


def kill_id_from_claim(
    claim_id: str,
) -> str:
    suffix = claim_id.rsplit("-", 1)[-1]
    return f"PA-KILL-{suffix}"


def validate_source_hash(
    record: dict[str, Any],
) -> tuple[bool, str | None]:
    source = record.get("source", {})

    local_source_path = source.get(
        "local_source_path",
        "",
    )

    expected = source.get(
        "expected_source_sha256",
        "",
    )

    source_exists = bool(
        source.get("source_exists")
    )

    source_hash_valid = bool(
        source.get("source_hash_valid")
    )

    if not local_source_path:
        return (
            not source_exists
            and not source_hash_valid
            and expected == "",
            None,
        )

    path = ROOT / local_source_path

    if not path.is_file():
        return False, None

    actual = sha256_file(path)

    return (
        actual == expected
        and source_hash_valid,
        actual,
    )


def validate_evidence_reference(
    evidence: dict[str, Any],
) -> tuple[bool, str | None]:
    source_path = evidence.get("source")
    line_start = evidence.get("line_start")
    line_end = evidence.get("line_end")
    support = evidence.get("support")

    if not all(
        isinstance(value, str)
        and value.strip()
        for value in (
            source_path,
            line_start,
            line_end,
            support,
        )
    ):
        return False, None

    path = ROOT / source_path

    if not path.is_file():
        return False, None

    if not re.fullmatch(
        r"L[0-9]{5}",
        line_start,
    ):
        return False, None

    if not re.fullmatch(
        r"L[0-9]{5}",
        line_end,
    ):
        return False, None

    if int(line_end[1:]) < int(line_start[1:]):
        return False, None

    return True, sha256_file(path)


def normalize_overlap_row(
    paper: dict[str, Any],
    overlap: dict[str, Any],
) -> dict[str, Any]:
    acquisition_order = int(
        paper["acquisition_order"]
    )

    source_id = source_id_from_order(
        acquisition_order
    )

    raw_classification = overlap.get(
        "overlap_classification"
    )

    raw_state = overlap.get("state")

    if raw_classification in ALLOWED_OVERLAP_STATES:
        overlap_state = raw_classification
    elif raw_state in ALLOWED_OVERLAP_STATES:
        overlap_state = raw_state
    else:
        overlap_state = "UNRESOLVED"

    evidence = overlap.get("evidence", [])

    if not isinstance(evidence, list):
        evidence = []

    overlapping_elements = overlap.get(
        "overlapping_elements",
        [],
    )

    if not isinstance(
        overlapping_elements,
        list,
    ):
        overlapping_elements = []

    if not overlapping_elements:
        mechanism = overlap.get(
            "overlapping_mechanism"
        )

        if mechanism:
            overlapping_elements = [mechanism]

    non_overlapping_elements = overlap.get(
        "non_overlapping_elements",
        [],
    )

    if not isinstance(
        non_overlapping_elements,
        list,
    ):
        non_overlapping_elements = []

    confidence = overlap.get(
        "confidence",
        0.0,
    )

    if not isinstance(confidence, (int, float)):
        confidence = 0.0

    adjudicator = overlap.get(
        "adjudicator",
        "",
    )

    if not isinstance(adjudicator, str):
        adjudicator = ""

    return {
        "claim_id": overlap["claim_id"],
        "source_id": source_id,
        "canonical_key": paper[
            "canonical_key"
        ],
        "paper_title": paper["title"],
        "evidence_record_path": relative(
            PAPER_DIRECTORY
            / (
                f"paper-{acquisition_order:02d}"
                "-scientific-evidence.json"
            )
        ),
        "evidence_record_sha256": sha256_file(
            PAPER_DIRECTORY
            / (
                f"paper-{acquisition_order:02d}"
                "-scientific-evidence.json"
            )
        ),
        "overlap_state": overlap_state,
        "overlapping_elements":
            overlapping_elements,
        "non_overlapping_elements":
            non_overlapping_elements,
        "evidence": evidence,
        "confidence": float(confidence),
        "adjudicator": adjudicator,
        "source_limitation": overlap.get(
            "source_limitation"
        ),
        "adjudication_complete": (
            overlap_state
            in TERMINAL_CLAIM_STATES
            and bool(adjudicator.strip())
            and 0.0 <= float(confidence) <= 1.0
        ),
    }


def artifact_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}

    for path in sorted(
        STAGE1.rglob("*.json")
    ):
        if path == HASH_MANIFEST_PATH:
            continue

        hashes[relative(path)] = sha256_file(
            path
        )

    return hashes


def main() -> int:
    errors: list[str] = []

    MATRIX_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    claims = parse_claim_registry(
        CLAIM_REGISTRY_PATH
    )

    claim_ids = [
        claim.get("claim_id")
        for claim in claims
    ]

    if len(claims) != EXPECTED_CLAIM_COUNT:
        errors.append(
            "novelty claim registry must contain "
            f"{EXPECTED_CLAIM_COUNT} claims"
        )

    if len(claim_ids) != len(
        set(claim_ids)
    ):
        errors.append(
            "duplicate novelty claim IDs detected"
        )

    for claim in claims:
        claim_id = claim.get("claim_id")

        if not isinstance(
            claim_id,
            str,
        ) or not CLAIM_ID_PATTERN.fullmatch(
            claim_id
        ):
            errors.append(
                f"invalid claim ID: {claim_id!r}"
            )

        if not str(
            claim.get("kill_condition", "")
        ).strip():
            errors.append(
                f"{claim_id} lacks a kill condition"
            )

    evidence_index = read_json(
        EVIDENCE_INDEX_PATH
    )

    if not isinstance(
        evidence_index,
        list,
    ):
        errors.append(
            "scientific evidence index must be a list"
        )
        evidence_index = []

    if len(evidence_index) != EXPECTED_PAPER_COUNT:
        errors.append(
            "scientific evidence index must contain "
            f"{EXPECTED_PAPER_COUNT} records"
        )

    paper_paths = sorted(
        PAPER_DIRECTORY.glob(
            "paper-*-scientific-evidence.json"
        )
    )

    if len(paper_paths) != EXPECTED_PAPER_COUNT:
        errors.append(
            "paper evidence directory must contain "
            f"{EXPECTED_PAPER_COUNT} records"
        )

    papers: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    unsupported_records: list[
        dict[str, Any]
    ] = []

    canonical_keys: set[str] = set()
    acquisition_orders: set[int] = set()

    for path in paper_paths:
        match = PAPER_FILE_PATTERN.fullmatch(
            path.name
        )

        if match is None:
            errors.append(
                f"noncanonical paper filename: {path.name}"
            )
            continue

        filename_order = int(match.group(1))
        paper = read_json(path)

        if not isinstance(paper, dict):
            errors.append(
                f"{path.name} must contain an object"
            )
            continue

        papers.append(paper)

        acquisition_order = paper.get(
            "acquisition_order"
        )

        if acquisition_order != filename_order:
            errors.append(
                f"{path.name} acquisition order mismatch"
            )
            continue

        if acquisition_order in acquisition_orders:
            errors.append(
                "duplicate acquisition order: "
                f"{acquisition_order}"
            )

        acquisition_orders.add(
            acquisition_order
        )

        canonical_key = paper.get(
            "canonical_key"
        )

        if not isinstance(
            canonical_key,
            str,
        ) or not canonical_key.strip():
            errors.append(
                f"{path.name} lacks canonical_key"
            )
            continue

        if canonical_key in canonical_keys:
            errors.append(
                "duplicate canonical key: "
                f"{canonical_key}"
            )

        canonical_keys.add(canonical_key)

        source_id = source_id_from_order(
            acquisition_order
        )

        if not SOURCE_ID_PATTERN.fullmatch(
            source_id
        ):
            errors.append(
                f"invalid source ID {source_id}"
            )

        source_hash_ok, observed_hash = (
            validate_source_hash(paper)
        )

        source = paper.get("source", {})

        source_records.append(
            {
                "source_id": source_id,
                "acquisition_order":
                    acquisition_order,
                "canonical_key":
                    canonical_key,
                "doi": paper.get("doi"),
                "title": paper.get("title"),
                "terminal_source_state":
                    paper.get(
                        "terminal_source_state"
                    ),
                "scientific_content_state":
                    paper.get(
                        "scientific_content_state"
                    ),
                "review_eligibility":
                    paper.get(
                        "review_eligibility"
                    ),
                "local_source_path":
                    source.get(
                        "local_source_path",
                        "",
                    ),
                "local_text_path":
                    source.get(
                        "local_text_path",
                        "",
                    ),
                "expected_source_sha256":
                    source.get(
                        "expected_source_sha256",
                        "",
                    ),
                "observed_source_sha256":
                    observed_hash,
                "source_exists":
                    bool(
                        source.get(
                            "source_exists"
                        )
                    ),
                "source_hash_valid":
                    source_hash_ok,
                "evidence_record_path":
                    relative(path),
                "evidence_record_sha256":
                    sha256_file(path),
            }
        )

        if not source_hash_ok:
            errors.append(
                f"{path.name} source-state/hash "
                "contract is inconsistent"
            )

        claim_ids_for_paper = paper.get(
            "claim_ids",
            [],
        )

        if not isinstance(
            claim_ids_for_paper,
            list,
        ) or not claim_ids_for_paper:
            errors.append(
                f"{path.name} lacks claim_ids"
            )
            claim_ids_for_paper = []

        unknown_claims = (
            set(claim_ids_for_paper)
            - set(claim_ids)
        )

        if unknown_claims:
            errors.append(
                f"{path.name} references unknown claims: "
                f"{sorted(unknown_claims)}"
            )

        fields = paper.get("fields", {})

        if not isinstance(fields, dict):
            errors.append(
                f"{path.name} fields must be an object"
            )
            fields = {}

        established_field_count = 0
        unsupported_field_count = 0
        pending_field_count = 0
        evidence_reference_count = 0
        invalid_evidence_reference_count = 0

        for field_name, field in fields.items():
            if not isinstance(field, dict):
                errors.append(
                    f"{path.name} field {field_name} "
                    "must be an object"
                )
                continue

            field_state = field.get("state")

            if (
                field_state
                not in SUPPORTED_FIELD_STATES
            ):
                errors.append(
                    f"{path.name} field {field_name} "
                    f"has invalid state {field_state!r}"
                )

            value = field.get("value")
            evidence = field.get(
                "evidence",
                [],
            )

            if not isinstance(evidence, list):
                errors.append(
                    f"{path.name} field {field_name} "
                    "evidence must be a list"
                )
                evidence = []

            if (
                field_state
                == "ESTABLISHED_FROM_SOURCE"
            ):
                established_field_count += 1

                if value is None:
                    errors.append(
                        f"{path.name} field {field_name} "
                        "is established but has null value"
                    )

                if not evidence:
                    errors.append(
                        f"{path.name} field {field_name} "
                        "is established but lacks evidence"
                    )

            if (
                field_state
                == "PENDING_SOURCE_REVIEW"
            ):
                pending_field_count += 1

                if value is not None:
                    errors.append(
                        f"{path.name} field {field_name} "
                        "is pending review but has a value"
                    )

                if evidence:
                    errors.append(
                        f"{path.name} field {field_name} "
                        "is pending review but has evidence"
                    )

            if (
                field_state
                == (
                    "NOT_ESTABLISHED_FROM_"
                    "AVAILABLE_SOURCE"
                )
            ):
                unsupported_field_count += 1

                if value is not None:
                    errors.append(
                        f"{path.name} field {field_name} "
                        "is unsupported but has a value"
                    )

                unsupported_records.append(
                    {
                        "unsupported_field_id": (
                            f"PA-UNSUP-"
                            f"{acquisition_order:04d}-"
                            f"{field_name}"
                        ),
                        "source_id": source_id,
                        "canonical_key":
                            canonical_key,
                        "field_name":
                            field_name,
                        "state":
                            field_state,
                        "review_notes":
                            field.get(
                                "review_notes"
                            ),
                        "evidence_record_path":
                            relative(path),
                    }
                )

            for reference in evidence:
                if not isinstance(
                    reference,
                    dict,
                ):
                    invalid_evidence_reference_count += 1
                    continue

                valid, _ = (
                    validate_evidence_reference(
                        reference
                    )
                )

                if valid:
                    evidence_reference_count += 1
                else:
                    invalid_evidence_reference_count += 1

        if invalid_evidence_reference_count:
            errors.append(
                f"{path.name} contains "
                f"{invalid_evidence_reference_count} "
                "invalid evidence references"
            )

        quality_control = paper.get(
            "quality_control",
            {},
        )

        if not isinstance(
            quality_control,
            dict,
        ):
            quality_control = {}

        record_state = paper.get(
            "record_state"
        )

        primary_complete = bool(
            quality_control.get(
                "primary_review_completed"
            )
        )

        if (
            record_state
            in COMPLETE_PRIMARY_RECORD_STATES
            and not primary_complete
        ):
            errors.append(
                f"{path.name} claims completed "
                "extraction without completed primary review"
            )

        if (
            record_state
            in SOURCE_LIMITED_RECORD_STATES
            and primary_complete
        ):
            errors.append(
                f"{path.name} is source-limited but "
                "claims completed primary review"
            )

        overlaps = paper.get(
            "truecolor_claim_overlap",
            [],
        )

        if not isinstance(overlaps, list):
            errors.append(
                f"{path.name} overlap data must be a list"
            )
            overlaps = []

        overlap_claim_ids = {
            overlap.get("claim_id")
            for overlap in overlaps
            if isinstance(overlap, dict)
        }

        if overlap_claim_ids != set(
            claim_ids_for_paper
        ):
            errors.append(
                f"{path.name} overlap claims do not "
                "match claim_ids"
            )

        evidence_records.append(
            {
                "evidence_id":
                    evidence_id_from_order(
                        acquisition_order
                    ),
                "source_id": source_id,
                "acquisition_order":
                    acquisition_order,
                "canonical_key":
                    canonical_key,
                "title": paper.get("title"),
                "claim_ids":
                    claim_ids_for_paper,
                "record_state":
                    record_state,
                "extraction_scope":
                    paper.get(
                        "extraction_scope"
                    ),
                "review_eligibility":
                    paper.get(
                        "review_eligibility"
                    ),
                "scientific_content_state":
                    paper.get(
                        "scientific_content_state"
                    ),
                "primary_review_completed":
                    primary_complete,
                "second_review_required":
                    bool(
                        quality_control.get(
                            "second_review_required"
                        )
                    ),
                "second_review_completed":
                    bool(
                        quality_control.get(
                            "second_review_completed"
                        )
                    ),
                "established_field_count":
                    established_field_count,
                "unsupported_field_count":
                    unsupported_field_count,
                "pending_field_count":
                    pending_field_count,
                "evidence_reference_count":
                    evidence_reference_count,
                "evidence_record_path":
                    relative(path),
                "evidence_record_sha256":
                    sha256_file(path),
            }
        )

    second_review_cohort = read_json(
        SECOND_REVIEW_PATH
    )

    if not isinstance(
        second_review_cohort,
        list,
    ):
        errors.append(
            "second-review cohort must be a list"
        )
        second_review_cohort = []

    if (
        len(second_review_cohort)
        != EXPECTED_SECOND_REVIEW_COUNT
    ):
        errors.append(
            "second-review cohort must contain "
            f"{EXPECTED_SECOND_REVIEW_COUNT} entries"
        )

    review_orders: set[int] = set()
    review_canonical_keys: set[str] = set()
    second_review_records: list[
        dict[str, Any]
    ] = []

    papers_by_key = {
        paper["canonical_key"]: paper
        for paper in papers
        if "canonical_key" in paper
    }

    for cohort_record in second_review_cohort:
        second_review_order = cohort_record.get(
            "second_review_order"
        )

        canonical_key = cohort_record.get(
            "canonical_key"
        )

        if second_review_order in review_orders:
            errors.append(
                "duplicate second-review order: "
                f"{second_review_order}"
            )

        review_orders.add(
            second_review_order
        )

        if canonical_key in review_canonical_keys:
            errors.append(
                "duplicate second-review canonical key: "
                f"{canonical_key}"
            )

        review_canonical_keys.add(
            canonical_key
        )

        paper = papers_by_key.get(
            canonical_key
        )

        if paper is None:
            errors.append(
                "second-review entry references "
                f"unknown canonical key {canonical_key}"
            )
            continue

        quality_control = paper.get(
            "quality_control",
            {},
        )

        second_review_records.append(
            {
                "review_id":
                    review_id_from_order(
                        int(second_review_order)
                    ),
                "second_review_order":
                    second_review_order,
                "source_id":
                    source_id_from_order(
                        int(
                            paper[
                                "acquisition_order"
                            ]
                        )
                    ),
                "canonical_key":
                    canonical_key,
                "title":
                    cohort_record.get(
                        "title"
                    ),
                "evidence_record_path":
                    cohort_record.get(
                        "evidence_record_path"
                    ),
                "evidence_record_sha256":
                    sha256_file(
                        ROOT
                        / cohort_record[
                            "evidence_record_path"
                        ]
                    ),
                "second_review_required":
                    bool(
                        quality_control.get(
                            "second_review_required"
                        )
                    ),
                "second_review_completed":
                    bool(
                        quality_control.get(
                            "second_review_completed"
                        )
                    ),
                "second_reviewer":
                    quality_control.get(
                        "second_reviewer"
                    ),
                "discrepancies":
                    quality_control.get(
                        "discrepancies",
                        [],
                    ),
                "final_review_state":
                    quality_control.get(
                        "final_review_state"
                    ),
            }
        )

    rows_by_claim: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for paper in papers:
        overlaps = paper.get(
            "truecolor_claim_overlap",
            [],
        )

        for overlap in overlaps:
            if not isinstance(overlap, dict):
                continue

            claim_id = overlap.get(
                "claim_id"
            )

            if claim_id not in claim_ids:
                continue

            rows_by_claim[claim_id].append(
                normalize_overlap_row(
                    paper,
                    overlap,
                )
            )

    matrix_records: list[
        dict[str, Any]
    ] = []

    kill_records: list[
        dict[str, Any]
    ] = []

    claim_register_records: list[
        dict[str, Any]
    ] = []

    for claim in claims:
        claim_id = claim["claim_id"]
        rows = sorted(
            rows_by_claim.get(
                claim_id,
                [],
            ),
            key=lambda row: row["source_id"],
        )

        complete_rows = [
            row
            for row in rows
            if row["adjudication_complete"]
        ]

        unresolved_rows = [
            row
            for row in rows
            if not row[
                "adjudication_complete"
            ]
        ]

        matrix = {
            "matrix_schema":
                "qudipi.stage1.claim-overlap-matrix",
            "matrix_version": 1,
            "matrix_id":
                matrix_id_from_claim(
                    claim_id
                ),
            "claim_id": claim_id,
            "claim_name":
                claim.get("name"),
            "proposed_claim":
                claim.get(
                    "proposed_claim"
                ),
            "claim_type":
                claim.get("claim_type"),
            "canonical_stages":
                claim.get(
                    "canonical_stages",
                    [],
                ),
            "kill_condition":
                claim.get(
                    "kill_condition"
                ),
            "matrix_state": (
                "COMPLETE"
                if rows
                and not unresolved_rows
                else "OPEN"
            ),
            "source_row_count":
                len(rows),
            "completed_row_count":
                len(complete_rows),
            "unresolved_row_count":
                len(unresolved_rows),
            "rows": rows,
        }

        matrix_path = (
            MATRIX_DIRECTORY
            / (
                claim_id.lower()
                .replace("-", "_")
                + "_matrix.json"
            )
        )

        write_json(
            matrix_path,
            matrix,
        )

        matrix_records.append(
            {
                "matrix_id":
                    matrix["matrix_id"],
                "claim_id": claim_id,
                "matrix_path":
                    relative(matrix_path),
                "matrix_sha256":
                    sha256_file(
                        matrix_path
                    ),
                "matrix_state":
                    matrix["matrix_state"],
                "source_row_count":
                    len(rows),
                "completed_row_count":
                    len(complete_rows),
                "unresolved_row_count":
                    len(unresolved_rows),
            }
        )

        kill_state = (
            "READY_FOR_DECISION"
            if matrix["matrix_state"]
            == "COMPLETE"
            else "BLOCKED_BY_UNRESOLVED_MATRIX"
        )

        kill_records.append(
            {
                "kill_condition_id":
                    kill_id_from_claim(
                        claim_id
                    ),
                "claim_id": claim_id,
                "kill_condition":
                    claim.get(
                        "kill_condition"
                    ),
                "matrix_id":
                    matrix["matrix_id"],
                "matrix_path":
                    relative(matrix_path),
                "decision_state":
                    kill_state,
                "decision": None,
                "decision_basis": [],
                "strongest_competing_source_ids": [],
                "adjudicator": None,
                "confidence": None,
            }
        )

        claim_register_records.append(
            {
                "claim_id": claim_id,
                "name": claim.get("name"),
                "proposed_claim":
                    claim.get(
                        "proposed_claim"
                    ),
                "claim_type":
                    claim.get(
                        "claim_type"
                    ),
                "canonical_stages":
                    claim.get(
                        "canonical_stages",
                        [],
                    ),
                "kill_condition":
                    claim.get(
                        "kill_condition"
                    ),
                "registry_status":
                    claim.get(
                        "status"
                    ),
                "matrix_id":
                    matrix["matrix_id"],
                "matrix_state":
                    matrix["matrix_state"],
                "kill_condition_id":
                    kill_id_from_claim(
                        claim_id
                    ),
                "kill_decision_state":
                    kill_state,
                "final_stage1_disposition":
                    None,
            }
        )

    write_json(
        SOURCE_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.source-register",
            "register_version": 1,
            "expected_record_count":
                EXPECTED_PAPER_COUNT,
            "record_count":
                len(source_records),
            "status": (
                "COMPLETE"
                if (
                    len(source_records)
                    == EXPECTED_PAPER_COUNT
                    and all(
                        record[
                            "source_hash_valid"
                        ]
                        for record in source_records
                    )
                )
                else "INVALID"
            ),
            "records": source_records,
        },
    )

    write_json(
        EVIDENCE_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.evidence-register",
            "register_version": 1,
            "expected_record_count":
                EXPECTED_PAPER_COUNT,
            "record_count":
                len(evidence_records),
            "semantic_completion": {
                "primary_review_complete_count":
                    sum(
                        1
                        for record
                        in evidence_records
                        if record[
                            "primary_review_completed"
                        ]
                    ),
                "pending_primary_review_count":
                    sum(
                        1
                        for record
                        in evidence_records
                        if (
                            not record[
                                "primary_review_completed"
                            ]
                            and record[
                                "review_eligibility"
                            ]
                            in {
                                "COMPLETE",
                                "BOUNDED",
                            }
                        )
                    ),
                "source_limited_count":
                    sum(
                        1
                        for record
                        in evidence_records
                        if record[
                            "review_eligibility"
                        ]
                        in {
                            "UNAVAILABLE",
                            "IDENTITY_AND_ABSTRACT_ONLY",
                        }
                    ),
            },
            "status": (
                "COMPLETE"
                if len(evidence_records)
                == EXPECTED_PAPER_COUNT
                else "INVALID"
            ),
            "records": evidence_records,
        },
    )

    write_json(
        SECOND_REVIEW_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.second-review-register",
            "register_version": 1,
            "expected_record_count":
                EXPECTED_SECOND_REVIEW_COUNT,
            "record_count":
                len(second_review_records),
            "completed_record_count":
                sum(
                    1
                    for record
                    in second_review_records
                    if record[
                        "second_review_completed"
                    ]
                ),
            "status": (
                "COMPLETE"
                if (
                    len(second_review_records)
                    == EXPECTED_SECOND_REVIEW_COUNT
                    and all(
                        record[
                            "second_review_completed"
                        ]
                        for record
                        in second_review_records
                    )
                )
                else "OPEN"
            ),
            "records":
                second_review_records,
        },
    )

    write_json(
        CLAIM_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.claim-register",
            "register_version": 1,
            "expected_claim_count":
                EXPECTED_CLAIM_COUNT,
            "claim_count":
                len(claim_register_records),
            "status": (
                "ADJUDICATED"
                if all(
                    record[
                        "final_stage1_disposition"
                    ]
                    is not None
                    for record
                    in claim_register_records
                )
                else "OPEN"
            ),
            "claims":
                claim_register_records,
        },
    )

    write_json(
        MATRIX_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.claim-matrix-register",
            "register_version": 1,
            "expected_matrix_count":
                EXPECTED_CLAIM_COUNT,
            "matrix_count":
                len(matrix_records),
            "completed_matrix_count":
                sum(
                    1
                    for record
                    in matrix_records
                    if record[
                        "matrix_state"
                    ]
                    == "COMPLETE"
                ),
            "status": (
                "COMPLETE"
                if (
                    len(matrix_records)
                    == EXPECTED_CLAIM_COUNT
                    and all(
                        record[
                            "matrix_state"
                        ]
                        == "COMPLETE"
                        for record
                        in matrix_records
                    )
                )
                else "OPEN"
            ),
            "matrices":
                matrix_records,
        },
    )

    write_json(
        KILL_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.novelty-kill-register",
            "register_version": 1,
            "expected_decision_count":
                EXPECTED_CLAIM_COUNT,
            "decision_count":
                len(kill_records),
            "completed_decision_count":
                sum(
                    1
                    for record
                    in kill_records
                    if record["decision"]
                    is not None
                ),
            "status": (
                "COMPLETE"
                if all(
                    record["decision"]
                    is not None
                    for record in kill_records
                )
                else "OPEN"
            ),
            "decisions":
                kill_records,
        },
    )

    write_json(
        UNSUPPORTED_REGISTER_PATH,
        {
            "register_schema":
                "qudipi.stage1.unsupported-field-register",
            "register_version": 1,
            "record_count":
                len(unsupported_records),
            "status": "COMPLETE",
            "records":
                unsupported_records,
        },
    )

    blockers: list[str] = []

    if errors:
        blockers.append(
            "semantic_contract_errors"
        )

    if any(
        (
            not record[
                "primary_review_completed"
            ]
            and record[
                "review_eligibility"
            ]
            in {
                "COMPLETE",
                "BOUNDED",
            }
        )
        for record in evidence_records
    ):
        blockers.append(
            "primary_scientific_reviews"
        )

    if not all(
        record[
            "second_review_completed"
        ]
        for record in second_review_records
    ):
        blockers.append(
            "independent_second_reviews"
        )

    if not all(
        record["matrix_state"]
        == "COMPLETE"
        for record in matrix_records
    ):
        blockers.append(
            "claim_overlap_adjudication"
        )

    if not all(
        record["decision"]
        is not None
        for record in kill_records
    ):
        blockers.append(
            "novelty_kill_decisions"
        )

    blockers = list(dict.fromkeys(blockers))

    write_json(
        GAP_REPORT_PATH,
        {
            "report_schema":
                "qudipi.stage1.semantic-gap-report",
            "report_version": 1,
            "stage_id": 1,
            "stage_key": "prior_art",
            "status": "OPEN",
            "closure_marker_emitted": False,
            "source_record_count":
                len(source_records),
            "evidence_record_count":
                len(evidence_records),
            "second_review_record_count":
                len(second_review_records),
            "claim_count":
                len(claim_register_records),
            "matrix_count":
                len(matrix_records),
            "kill_condition_count":
                len(kill_records),
            "remaining_blockers":
                blockers,
            "semantic_contract_errors":
                errors,
            "prohibited_actions": [
                "repeat corpus discovery",
                "repeat source acquisition",
                "repeat OCR",
                "repeat identity resolution",
                "repeat global ranking",
                "infer overlap from title or metadata",
                "infer novelty from corpus absence",
                "emit Stage 1 closure before all "
                "adjudications are complete",
            ],
        },
    )

    write_json(
        RUN_MANIFEST_PATH,
        {
            "run_schema":
                "qudipi.stage1.semantic-ledger-run",
            "run_version": 1,
            "status": (
                "PASS"
                if not errors
                else "FAIL"
            ),
            "repository_revision":
                git_value(
                    "rev-parse",
                    "HEAD",
                ),
            "repository_tree":
                git_value(
                    "rev-parse",
                    "HEAD^{tree}",
                ),
            "protocol_path":
                relative(PROTOCOL_PATH),
            "protocol_sha256":
                sha256_file(
                    PROTOCOL_PATH
                ),
            "claim_registry_path":
                relative(
                    CLAIM_REGISTRY_PATH
                ),
            "claim_registry_sha256":
                sha256_file(
                    CLAIM_REGISTRY_PATH
                ),
            "claim_schema_path":
                relative(
                    CLAIM_SCHEMA_PATH
                ),
            "claim_schema_sha256":
                sha256_file(
                    CLAIM_SCHEMA_PATH
                ),
            "evidence_index_path":
                relative(
                    EVIDENCE_INDEX_PATH
                ),
            "evidence_index_sha256":
                sha256_file(
                    EVIDENCE_INDEX_PATH
                ),
            "second_review_cohort_path":
                relative(
                    SECOND_REVIEW_PATH
                ),
            "second_review_cohort_sha256":
                sha256_file(
                    SECOND_REVIEW_PATH
                ),
        },
    )

    write_json(
        HASH_MANIFEST_PATH,
        artifact_hashes(),
    )

    print(
        "QUDIPI_STAGE1_SEMANTIC_LEDGER_BUILD="
        + (
            "PASS"
            if not errors
            else "FAIL"
        )
    )

    print(
        f"source_record_count={len(source_records)}"
    )

    print(
        f"evidence_record_count={len(evidence_records)}"
    )

    print(
        "primary_review_complete_count="
        f"{sum(1 for record in evidence_records if record['primary_review_completed'])}"
    )

    print(
        "second_review_record_count="
        f"{len(second_review_records)}"
    )

    print(
        "second_review_complete_count="
        f"{sum(1 for record in second_review_records if record['second_review_completed'])}"
    )

    print(
        f"claim_count={len(claim_register_records)}"
    )

    print(
        f"matrix_count={len(matrix_records)}"
    )

    print(
        "completed_matrix_count="
        f"{sum(1 for record in matrix_records if record['matrix_state'] == 'COMPLETE')}"
    )

    print(
        f"kill_condition_count={len(kill_records)}"
    )

    print(
        "completed_kill_decision_count="
        f"{sum(1 for record in kill_records if record['decision'] is not None)}"
    )

    print(
        "remaining_blockers="
        + (
            ",".join(blockers)
            if blockers
            else "none"
        )
    )

    for error in errors:
        print(f"ERROR  {error}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
