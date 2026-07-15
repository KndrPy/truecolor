from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(".").resolve()

PDF_ROOT = Path(
    "preprocessed_intake/"
    "corpus_prior_art_paper-pdf"
)

REVIEW_PATH = Path(
    "artifacts/stage_01/disposition_review/"
    "corpus_disposition_review.csv"
)

OUTPUT_PATH = Path(
    "artifacts/stage_01/disposition_review/"
    "corpus_disposition_pdf_reconciliation.json"
)

MISSING_CSV_PATH = Path(
    "artifacts/stage_01/disposition_review/"
    "corpus_disposition_missing_pdfs.csv"
)

MATCHED_CSV_PATH = Path(
    "artifacts/stage_01/disposition_review/"
    "corpus_disposition_matched_pdfs.csv"
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


def normalize_text(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value or "").lower(),
    )


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()

    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):]

    return text.strip()


def normalize_pmid(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .removeprefix("pmid:")
    )


def filename_tokens(path: Path) -> set[str]:
    stem = path.stem.lower()

    raw_parts = re.split(
        r"[^a-z0-9]+",
        stem,
    )

    return {
        part
        for part in raw_parts
        if len(part) >= 4
    }


def title_tokens(value: Any) -> set[str]:
    raw_parts = re.split(
        r"[^a-z0-9]+",
        str(value or "").lower(),
    )

    stopwords = {
        "with",
        "from",
        "using",
        "based",
        "human",
        "skin",
        "color",
        "colour",
        "spectral",
        "imaging",
        "dataset",
        "data",
        "study",
        "analysis",
        "review",
        "method",
        "methods",
    }

    return {
        part
        for part in raw_parts
        if len(part) >= 5
        and part not in stopwords
    }


def exact_filename_number(path: Path) -> int | None:
    match = re.match(
        r"^(\d{2})_",
        path.name,
    )

    if match is None:
        return None

    return int(match.group(1))


with REVIEW_PATH.open(
    newline="",
    encoding="utf-8",
) as handle:
    review_rows = list(
        csv.DictReader(handle)
    )

pdf_paths = sorted(
    PDF_ROOT.glob("*.pdf")
)

errors: list[str] = []
candidate_matrix: list[dict[str, Any]] = []

for review_row in review_rows:
    review_order = int(
        review_row["review_order"]
    )

    title = review_row.get(
        "title",
        "",
    )

    doi = normalize_doi(
        review_row.get(
            "doi",
            "",
        )
    )

    pmid = normalize_pmid(
        review_row.get(
            "pmid",
            "",
        )
    )

    canonical_identity = review_row[
        "canonical_identity"
    ]

    source_metadata = json.loads(
        review_row[
            "source_metadata_json"
        ]
    )

    candidate_scores: list[
        dict[str, Any]
    ] = []

    review_title_tokens = title_tokens(
        title
    )

    for pdf_path in pdf_paths:
        score = 0
        reasons: list[str] = []

        pdf_filename_tokens = filename_tokens(
            pdf_path
        )

        pdf_number = exact_filename_number(
            pdf_path
        )

        filename_normalized = normalize_text(
            pdf_path.stem
        )

        if (
            pdf_number is not None
            and pdf_number == review_order
        ):
            score += 100
            reasons.append(
                "EXACT_REVIEW_ORDER_FILENAME"
            )

        if doi:
            normalized_doi_token = (
                normalize_text(doi)
            )

            if (
                normalized_doi_token
                and normalized_doi_token
                in filename_normalized
            ):
                score += 1000
                reasons.append(
                    "DOI_FILENAME"
                )

        if pmid:
            normalized_pmid_token = (
                normalize_text(pmid)
            )

            if (
                normalized_pmid_token
                and normalized_pmid_token
                in filename_normalized
            ):
                score += 1000
                reasons.append(
                    "PMID_FILENAME"
                )

        common_title_tokens = sorted(
            review_title_tokens
            & pdf_filename_tokens
        )

        if common_title_tokens:
            score += (
                15
                * len(
                    common_title_tokens
                )
            )
            reasons.append(
                "TITLE_TOKEN_OVERLAP:"
                + ",".join(
                    common_title_tokens
                )
            )

        if score > 0:
            candidate_scores.append(
                {
                    "pdf_path":
                        pdf_path.as_posix(),
                    "pdf_sha256":
                        sha256_file(
                            pdf_path
                        ),
                    "pdf_size_bytes":
                        pdf_path.stat().st_size,
                    "score":
                        score,
                    "reasons":
                        reasons,
                }
            )

    candidate_scores.sort(
        key=lambda item: (
            -item["score"],
            item["pdf_path"],
        )
    )

    selected = None
    state = "PDF_NOT_CONFIRMED"

    if candidate_scores:
        top = candidate_scores[0]

        second_score = (
            candidate_scores[1]["score"]
            if len(candidate_scores) > 1
            else -1
        )

        if (
            top["score"] >= 1000
            or (
                top["score"] >= 100
                and top["score"] > second_score
            )
        ):
            selected = top
            state = "PDF_CONFIRMED"
        elif (
            top["score"] >= 45
            and top["score"] > second_score
        ):
            selected = top
            state = "PDF_PROVISIONAL_MATCH"
        else:
            state = "PDF_AMBIGUOUS"

    candidate_matrix.append(
        {
            "review_order":
                review_order,
            "task_id":
                review_row[
                    "task_id"
                ],
            "canonical_identity":
                canonical_identity,
            "title":
                title,
            "doi":
                doi,
            "pmid":
                pmid,
            "source_metadata":
                source_metadata,
            "pdf_state":
                state,
            "selected_pdf":
                selected,
            "candidate_count":
                len(
                    candidate_scores
                ),
            "candidates":
                candidate_scores,
        }
    )

selected_pdf_paths = [
    record["selected_pdf"]["pdf_path"]
    for record in candidate_matrix
    if record["selected_pdf"] is not None
]

duplicate_selected_paths = sorted(
    {
        path
        for path in selected_pdf_paths
        if selected_pdf_paths.count(path) > 1
    }
)

if duplicate_selected_paths:
    for path in duplicate_selected_paths:
        errors.append(
            "PDF selected for more than one "
            f"governed record: {path}"
        )

confirmed_records = [
    record
    for record in candidate_matrix
    if record["pdf_state"]
    == "PDF_CONFIRMED"
]

provisional_records = [
    record
    for record in candidate_matrix
    if record["pdf_state"]
    == "PDF_PROVISIONAL_MATCH"
]

ambiguous_records = [
    record
    for record in candidate_matrix
    if record["pdf_state"]
    == "PDF_AMBIGUOUS"
]

missing_records = [
    record
    for record in candidate_matrix
    if record["pdf_state"]
    == "PDF_NOT_CONFIRMED"
]

matched_fieldnames = [
    "review_order",
    "task_id",
    "canonical_identity",
    "title",
    "doi",
    "pmid",
    "pdf_state",
    "pdf_path",
    "pdf_sha256",
    "pdf_size_bytes",
    "match_score",
    "match_reasons",
]

with MATCHED_CSV_PATH.open(
    "w",
    newline="",
    encoding="utf-8",
) as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=matched_fieldnames,
    )

    writer.writeheader()

    for record in (
        confirmed_records
        + provisional_records
        + ambiguous_records
    ):
        selected = record[
            "selected_pdf"
        ]

        writer.writerow(
            {
                "review_order":
                    record[
                        "review_order"
                    ],
                "task_id":
                    record[
                        "task_id"
                    ],
                "canonical_identity":
                    record[
                        "canonical_identity"
                    ],
                "title":
                    record["title"],
                "doi":
                    record["doi"],
                "pmid":
                    record["pmid"],
                "pdf_state":
                    record[
                        "pdf_state"
                    ],
                "pdf_path":
                    (
                        selected[
                            "pdf_path"
                        ]
                        if selected
                        else ""
                    ),
                "pdf_sha256":
                    (
                        selected[
                            "pdf_sha256"
                        ]
                        if selected
                        else ""
                    ),
                "pdf_size_bytes":
                    (
                        selected[
                            "pdf_size_bytes"
                        ]
                        if selected
                        else ""
                    ),
                "match_score":
                    (
                        selected[
                            "score"
                        ]
                        if selected
                        else ""
                    ),
                "match_reasons":
                    (
                        "|".join(
                            selected[
                                "reasons"
                            ]
                        )
                        if selected
                        else ""
                    ),
            }
        )

missing_fieldnames = [
    "review_order",
    "task_id",
    "canonical_identity",
    "title",
    "doi",
    "pmid",
    "pdf_state",
]

with MISSING_CSV_PATH.open(
    "w",
    newline="",
    encoding="utf-8",
) as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=missing_fieldnames,
    )

    writer.writeheader()

    for record in missing_records:
        writer.writerow(
            {
                field:
                    record[field]
                for field
                in missing_fieldnames
            }
        )

result = {
    "report_schema":
        "qudipi.stage1.prior-art-pdf-reconciliation",
    "report_version": 1,
    "configured_review_record_count":
        len(review_rows),
    "repository_prior_art_pdf_count":
        len(pdf_paths),
    "confirmed_match_count":
        len(confirmed_records),
    "provisional_match_count":
        len(provisional_records),
    "ambiguous_match_count":
        len(ambiguous_records),
    "missing_pdf_count":
        len(missing_records),
    "duplicate_selected_pdf_count":
        len(duplicate_selected_paths),
    "duplicate_selected_pdf_paths":
        duplicate_selected_paths,
    "errors":
        errors,
    "records":
        candidate_matrix,
}

OUTPUT_PATH.write_text(
    json.dumps(
        result,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)

print(
    "QUDIPI_STAGE1_PDF_RECONCILIATION="
    + (
        "PASS"
        if not errors
        else "FAIL"
    )
)

print(
    "configured_review_record_count="
    f"{len(review_rows)}"
)

print(
    "repository_prior_art_pdf_count="
    f"{len(pdf_paths)}"
)

print(
    "confirmed_match_count="
    f"{len(confirmed_records)}"
)

print(
    "provisional_match_count="
    f"{len(provisional_records)}"
)

print(
    "ambiguous_match_count="
    f"{len(ambiguous_records)}"
)

print(
    "missing_pdf_count="
    f"{len(missing_records)}"
)

print(
    "duplicate_selected_pdf_count="
    f"{len(duplicate_selected_paths)}"
)

print(
    f"output={OUTPUT_PATH}"
)

print(
    f"matched_csv={MATCHED_CSV_PATH}"
)

print(
    f"missing_csv={MISSING_CSV_PATH}"
)

for record in candidate_matrix:
    selected = record[
        "selected_pdf"
    ]

    selected_path = (
        selected["pdf_path"]
        if selected
        else ""
    )

    print(
        "RECORD  "
        f"order={record['review_order']} "
        f"state={record['pdf_state']} "
        f"pdf={selected_path} "
        f"title={record['title']}"
    )

if errors:
    for error in errors:
        print(f"ERROR  {error}")

    raise RuntimeError(
        "PDF reconciliation failed"
    )
