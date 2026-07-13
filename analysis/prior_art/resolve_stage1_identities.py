from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("analysis/prior_art")

QUEUE_DIR = (
    ROOT / "corpus/identity_verifications"
)

POLICY_PATH = (
    ROOT / "policy/stage1_identity_resolution_policy.yaml"
)

RAW_DIR = (
    ROOT / "evidence/identity_resolution/raw"
)

NORMALIZED_DIR = (
    ROOT / "evidence/identity_resolution/normalized"
)

CHECKPOINT_DIR = (
    ROOT / "evidence/identity_resolution/checkpoints"
)

USER_AGENT = (
    "TrueColorPriorArtIdentityResolver/1.0 "
    "(KndrPy/truecolor; scholarly identity verification)"
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


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).replace(
        microsecond=0
    ).isoformat().replace(
        "+00:00",
        "Z",
    )


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None

    rendered = value.strip().lower()

    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "doi:",
    ):
        if rendered.startswith(prefix):
            rendered = rendered[len(prefix):]

    return rendered or None


def strip_markup(value: Any) -> str:
    text = str(value or "")

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    return html.unescape(text)


def normalize_text(value: Any) -> str:
    text = strip_markup(value)

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return " ".join(text.split())


def token_set(value: Any) -> set[str]:
    return set(
        normalize_text(value).split()
    )


def jaccard(
    left: set[str],
    right: set[str],
) -> float:
    if not left and not right:
        return 1.0

    if not left or not right:
        return 0.0

    return len(left & right) / len(
        left | right
    )


def title_similarity(
    left: Any,
    right: Any,
) -> float:
    return round(
        jaccard(
            token_set(left),
            token_set(right),
        ),
        6,
    )


def author_family_tokens(
    authors: list[str],
) -> set[str]:
    tokens = set()

    for author in authors:
        normalized = normalize_text(
            author
        )

        parts = normalized.split()

        if parts:
            tokens.add(parts[-1])

    return tokens


def author_overlap(
    harvested: list[str],
    canonical: list[str],
) -> float:
    return round(
        jaccard(
            author_family_tokens(harvested),
            author_family_tokens(canonical),
        ),
        6,
    )


def scalar_title(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            rendered = strip_markup(
                item
            ).strip()

            if rendered:
                return rendered

        return None

    rendered = strip_markup(
        value
    ).strip()

    return rendered or None


def scalar_venue(value: Any) -> str | None:
    return scalar_title(value)


def crossref_authors(
    item: dict[str, Any],
) -> list[str]:
    authors = []

    for author in item.get(
        "author",
        [],
    ):
        name = " ".join(
            part.strip()
            for part in [
                str(author.get("given") or ""),
                str(author.get("family") or ""),
            ]
            if part.strip()
        )

        if name:
            authors.append(name)

    return authors


def crossref_year(
    item: dict[str, Any],
) -> int | None:
    candidates = [
        item.get("published-print"),
        item.get("published-online"),
        item.get("published"),
        item.get("issued"),
        item.get("created"),
    ]

    for candidate in candidates:
        if not isinstance(
            candidate,
            dict,
        ):
            continue

        parts = candidate.get(
            "date-parts"
        )

        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
        ):
            try:
                return int(parts[0][0])
            except (
                TypeError,
                ValueError,
            ):
                pass

        timestamp = candidate.get(
            "date-time"
        )

        if timestamp:
            match = re.match(
                r"^(\d{4})",
                str(timestamp),
            )

            if match:
                return int(
                    match.group(1)
                )

    return None


def request_bytes(
    url: str,
    *,
    timeout: int,
    retry_delays: list[float],
) -> tuple[
    int | None,
    bytes,
    str | None,
]:
    last_error: Exception | None = None

    for attempt in range(
        len(retry_delays) + 1
    ):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                return (
                    response.status,
                    response.read(),
                    None,
                )

        except urllib.error.HTTPError as exc:
            body = exc.read()

            if (
                exc.code < 500
                and exc.code != 429
            ):
                return (
                    exc.code,
                    body,
                    str(exc),
                )

            last_error = exc

        except Exception as exc:
            last_error = exc

        if attempt < len(retry_delays):
            time.sleep(
                retry_delays[attempt]
            )

    return (
        None,
        b"",
        str(last_error)
        if last_error
        else "unknown_request_failure",
    )


def persist_raw(
    *,
    candidate_rank: int,
    source: str,
    request_identity: str,
    payload: bytes,
    http_status: int | None,
    error: str | None,
) -> dict[str, Any]:
    candidate_dir = (
        RAW_DIR
        / f"global-{candidate_rank:04d}"
    )

    candidate_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    identity_hash = sha256_bytes(
        request_identity.encode(
            "utf-8"
        )
    )[:16]

    payload_path = (
        candidate_dir
        / f"{source}__{identity_hash}.json"
    )

    envelope = {
        "source": source,
        "request_identity": (
            request_identity
        ),
        "retrieved_at_utc": utc_now(),
        "http_status": http_status,
        "error": error,
        "response_body_utf8": (
            payload.decode(
                "utf-8",
                errors="replace",
            )
        ),
    }

    rendered = (
        json.dumps(
            envelope,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")

    if not payload_path.exists():
        payload_path.write_bytes(
            rendered
        )

    return {
        "source": source,
        "request_identity": (
            request_identity
        ),
        "retrieved_at_utc": envelope[
            "retrieved_at_utc"
        ],
        "http_status": http_status,
        "raw_path": str(payload_path),
        "raw_sha256": sha256_path(
            payload_path
        ),
    }


def crossref_lookup_doi(
    *,
    rank: int,
    doi: str,
    timeout: int,
    retry_delays: list[float],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any],
]:
    encoded = urllib.parse.quote(
        doi,
        safe="",
    )

    url = (
        "https://api.crossref.org/"
        f"works/{encoded}"
    )

    status, payload, error = (
        request_bytes(
            url,
            timeout=timeout,
            retry_delays=retry_delays,
        )
    )

    evidence = persist_raw(
        candidate_rank=rank,
        source="crossref_doi",
        request_identity=f"doi:{doi}",
        payload=payload,
        http_status=status,
        error=error,
    )

    if status != 200:
        return None, evidence

    try:
        parsed = json.loads(
            payload.decode("utf-8")
        )
    except Exception:
        return None, evidence

    item = parsed.get("message")

    if not isinstance(item, dict):
        return None, evidence

    normalized = {
        "doi": normalize_doi(
            item.get("DOI")
        ),
        "pmid": None,
        "pmcid": None,
        "arxiv": None,
        "title": scalar_title(
            item.get("title")
        ),
        "authors": crossref_authors(
            item
        ),
        "year": crossref_year(item),
        "venue": scalar_venue(
            item.get("container-title")
        ),
        "publication_type": item.get(
            "type"
        ),
        "publication_status": (
            "PUBLISHED"
        ),
        "url": item.get("URL"),
        "relation": item.get(
            "relation",
            {},
        ),
        "update_to": item.get(
            "update-to",
            [],
        ),
    }

    return normalized, evidence


def europe_pmc_lookup_pmid(
    *,
    rank: int,
    pmid: str,
    timeout: int,
    retry_delays: list[float],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any],
]:
    query = urllib.parse.urlencode({
        "query": f"EXT_ID:{pmid} AND SRC:MED",
        "format": "json",
        "resultType": "core",
        "pageSize": 5,
    })

    url = (
        "https://www.ebi.ac.uk/europepmc/"
        "webservices/rest/search?"
        + query
    )

    status, payload, error = (
        request_bytes(
            url,
            timeout=timeout,
            retry_delays=retry_delays,
        )
    )

    evidence = persist_raw(
        candidate_rank=rank,
        source="europe_pmc_pmid",
        request_identity=f"pmid:{pmid}",
        payload=payload,
        http_status=status,
        error=error,
    )

    if status != 200:
        return None, evidence

    try:
        parsed = json.loads(
            payload.decode("utf-8")
        )
    except Exception:
        return None, evidence

    results = (
        parsed.get("resultList", {})
        .get("result", [])
    )

    if not results:
        return None, evidence

    item = results[0]

    authors = []

    author_list = (
        item.get("authorList", {})
        .get("author", [])
    )

    for author in author_list:
        name = author.get(
            "fullName"
        )

        if name:
            authors.append(
                str(name)
            )

    if not authors:
        author_string = str(
            item.get(
                "authorString",
                "",
            )
        )

        authors = [
            value.strip()
            for value in author_string.split(
                ","
            )
            if value.strip()
        ]

    try:
        year = int(
            item.get("pubYear")
        )
    except (
        TypeError,
        ValueError,
    ):
        year = None

    normalized = {
        "doi": normalize_doi(
            item.get("doi")
        ),
        "pmid": str(
            item.get("pmid")
        ) if item.get("pmid") else None,
        "pmcid": item.get("pmcid"),
        "arxiv": None,
        "title": scalar_title(
            item.get("title")
        ),
        "authors": authors,
        "year": year,
        "venue": item.get(
            "journalTitle"
        ),
        "publication_type": (
            item.get("pubType")
        ),
        "publication_status": (
            "PUBLISHED"
        ),
        "url": (
            "https://europepmc.org/"
            f"article/MED/{pmid}"
        ),
        "is_retracted": bool(
            item.get("isRetracted")
        ),
    }

    return normalized, evidence


def crossref_title_search(
    *,
    rank: int,
    title: str,
    year: int | None,
    timeout: int,
    retry_delays: list[float],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    parameters = {
        "query.title": title,
        "rows": 5,
    }

    if year:
        parameters["filter"] = (
            f"from-pub-date:{year}-01-01,"
            f"until-pub-date:{year}-12-31"
        )

    url = (
        "https://api.crossref.org/works?"
        + urllib.parse.urlencode(
            parameters
        )
    )

    request_identity = (
        f"title:{normalize_text(title)}"
        f"|year:{year or 'unknown'}"
    )

    status, payload, error = (
        request_bytes(
            url,
            timeout=timeout,
            retry_delays=retry_delays,
        )
    )

    evidence = persist_raw(
        candidate_rank=rank,
        source="crossref_title",
        request_identity=request_identity,
        payload=payload,
        http_status=status,
        error=error,
    )

    if status != 200:
        return [], evidence

    try:
        parsed = json.loads(
            payload.decode("utf-8")
        )
    except Exception:
        return [], evidence

    items = (
        parsed.get("message", {})
        .get("items", [])
    )

    normalized = []

    for item in items:
        normalized.append({
            "doi": normalize_doi(
                item.get("DOI")
            ),
            "pmid": None,
            "pmcid": None,
            "arxiv": None,
            "title": scalar_title(
                item.get("title")
            ),
            "authors": (
                crossref_authors(item)
            ),
            "year": crossref_year(
                item
            ),
            "venue": scalar_venue(
                item.get(
                    "container-title"
                )
            ),
            "publication_type": (
                item.get("type")
            ),
            "publication_status": (
                "PUBLISHED"
            ),
            "url": item.get("URL"),
            "relation": item.get(
                "relation",
                {},
            ),
            "update_to": item.get(
                "update-to",
                [],
            ),
        })

    return normalized, evidence


def compare_metadata(
    record: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, Any]:
    harvested_title = record.get(
        "harvested_title",
        "",
    )

    harvested_authors = []

    for note in record.get(
        "review_notes",
        [],
    ):
        _ = note

    harvested_year = None

    identifier = record[
        "canonical_identifier"
    ]

    title_score = title_similarity(
        harvested_title,
        canonical.get("title"),
    )

    doi_match = None

    harvested_doi = normalize_doi(
        identifier.get("doi")
    )

    canonical_doi = normalize_doi(
        canonical.get("doi")
    )

    if harvested_doi and canonical_doi:
        doi_match = (
            harvested_doi
            == canonical_doi
        )

    pmid_match = None

    harvested_pmid = identifier.get(
        "pmid"
    )

    canonical_pmid = canonical.get(
        "pmid"
    )

    if harvested_pmid and canonical_pmid:
        pmid_match = (
            str(harvested_pmid)
            == str(canonical_pmid)
        )

    return {
        "title_similarity": title_score,
        "doi_match": doi_match,
        "pmid_match": pmid_match,
        "harvested_year": harvested_year,
        "canonical_year": canonical.get(
            "year"
        ),
        "author_overlap": author_overlap(
            harvested_authors,
            canonical.get(
                "authors",
                [],
            ),
        ) if harvested_authors else None,
    }


def classify(
    *,
    record: dict[str, Any],
    canonical: dict[str, Any] | None,
    comparison: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[str, str, str]:
    if canonical is None:
        return (
            "UNRESOLVED",
            (
                "No authoritative metadata record "
                "resolved from attempted identifiers."
            ),
            "UNRESOLVED",
        )

    if canonical.get("is_retracted"):
        return (
            "RETRACTED",
            (
                "Authoritative metadata marks "
                "the publication as retracted."
            ),
            "RETRACTION_OF",
        )

    publication_type = normalize_text(
        canonical.get(
            "publication_type"
        )
    )

    title_text = normalize_text(
        canonical.get("title")
    )

    if (
        "correction" in publication_type
        or "correction" in title_text
        or "erratum" in publication_type
        or "erratum" in title_text
    ):
        return (
            "CORRECTION_ONLY",
            (
                "Resolved record is a correction "
                "or erratum rather than the "
                "underlying publication."
            ),
            "CORRECTION_OF",
        )

    threshold = float(
        policy["thresholds"][
            "normalized_title_similarity"
        ]
    )

    conflict_threshold = float(
        policy["thresholds"][
            "normalized_title_conflict_below"
        ]
    )

    title_score = comparison[
        "title_similarity"
    ]

    identifier_match = (
        comparison["doi_match"] is not False
        and comparison["pmid_match"] is not False
    )

    if (
        title_score >= threshold
        and identifier_match
    ):
        return (
            "VERIFIED",
            (
                "Authoritative identifier resolved "
                "and normalized title met the "
                "verification threshold."
            ),
            "CANONICAL_VERSION",
        )

    if (
        title_score < conflict_threshold
        or not identifier_match
    ):
        return (
            "CONFLICT",
            (
                "Authoritative metadata conflicts "
                "with harvested identity."
            ),
            "UNRESOLVED",
        )

    return (
        "UNRESOLVED",
        (
            "Authoritative metadata resolved, "
            "but identity similarity remained "
            "between verification and conflict "
            "thresholds."
        ),
        "UNRESOLVED",
    )


def result_path(rank: int) -> Path:
    return (
        NORMALIZED_DIR
        / f"global-{rank:04d}.json"
    )


def resolve_record(
    *,
    path: Path,
    policy: dict[str, Any],
    timeout: int,
    retry_delays: list[float],
    delay: float,
) -> dict[str, Any]:
    record = load_yaml(path)

    rank = int(record["global_rank"])

    identifiers = record[
        "canonical_identifier"
    ]

    doi = normalize_doi(
        identifiers.get("doi")
    )

    pmid = identifiers.get("pmid")

    title = str(
        record.get("harvested_title")
        or ""
    ).strip()

    attempted = []
    evidence = []
    canonical = None
    source_used = None

    if doi:
        attempted.append({
            "identifier_type": "doi",
            "identifier_value": doi,
            "attempted": True,
            "result": None,
        })

        canonical, raw = (
            crossref_lookup_doi(
                rank=rank,
                doi=doi,
                timeout=timeout,
                retry_delays=retry_delays,
            )
        )

        evidence.append(raw)

        attempted[-1]["result"] = (
            "RESOLVED"
            if canonical
            else "NOT_RESOLVED"
        )

        if canonical:
            source_used = (
                "crossref_doi"
            )

        time.sleep(delay)

    if canonical is None and pmid:
        attempted.append({
            "identifier_type": "pmid",
            "identifier_value": str(pmid),
            "attempted": True,
            "result": None,
        })

        canonical, raw = (
            europe_pmc_lookup_pmid(
                rank=rank,
                pmid=str(pmid),
                timeout=timeout,
                retry_delays=retry_delays,
            )
        )

        evidence.append(raw)

        attempted[-1]["result"] = (
            "RESOLVED"
            if canonical
            else "NOT_RESOLVED"
        )

        if canonical:
            source_used = (
                "europe_pmc_pmid"
            )

        time.sleep(delay)

    if canonical is None and title:
        attempted.append({
            "identifier_type": (
                "title_author_year"
            ),
            "identifier_value": (
                normalize_text(title)
            ),
            "attempted": True,
            "result": None,
        })

        candidates, raw = (
            crossref_title_search(
                rank=rank,
                title=title,
                year=None,
                timeout=timeout,
                retry_delays=retry_delays,
            )
        )

        evidence.append(raw)

        if candidates:
            candidates.sort(
                key=lambda item: (
                    -title_similarity(
                        title,
                        item.get("title"),
                    ),
                    str(
                        item.get("doi")
                        or ""
                    ),
                )
            )

            canonical = candidates[0]
            source_used = (
                "crossref_title"
            )

        attempted[-1]["result"] = (
            "RESOLVED"
            if canonical
            else "NOT_RESOLVED"
        )

        time.sleep(delay)

    comparison = compare_metadata(
        record,
        canonical or {},
    )

    state, reason, relationship = classify(
        record=record,
        canonical=canonical,
        comparison=comparison,
        policy=policy,
    )

    conflicts = []

    if comparison.get(
        "doi_match"
    ) is False:
        conflicts.append({
            "field": "doi",
            "harvested": doi,
            "authoritative": (
                canonical or {}
            ).get("doi"),
        })

    if comparison.get(
        "pmid_match"
    ) is False:
        conflicts.append({
            "field": "pmid",
            "harvested": pmid,
            "authoritative": (
                canonical or {}
            ).get("pmid"),
        })

    conflict_threshold = float(
        policy["thresholds"][
            "normalized_title_conflict_below"
        ]
    )

    if (
        canonical
        and comparison[
            "title_similarity"
        ] < conflict_threshold
    ):
        conflicts.append({
            "field": "title",
            "harvested": title,
            "authoritative": canonical.get(
                "title"
            ),
            "similarity": comparison[
                "title_similarity"
            ],
        })

    return {
        "candidate_key": record[
            "candidate_key"
        ],
        "global_rank": rank,
        "attempted_identifiers": attempted,
        "resolution_state": state,
        "resolution_reason": reason,
        "authoritative_source": (
            source_used
        ),
        "retrieval_evidence": evidence,
        "normalized_metadata": (
            canonical or {}
        ),
        "field_comparison": comparison,
        "version_relationship": (
            relationship
        ),
        "related_candidate_keys": [],
        "conflicts": conflicts,
    }


def write_checkpoint(
    *,
    start_rank: int,
    end_rank: int,
    completed: list[int],
    skipped: list[int],
    failed: list[
        dict[str, Any]
    ],
) -> None:
    CHECKPOINT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    checkpoint = {
        "stage": 1,
        "artifact": (
            "identity_resolution_checkpoint"
        ),
        "start_rank": start_rank,
        "end_rank": end_rank,
        "updated_at_utc": utc_now(),
        "completed_ranks": sorted(
            completed
        ),
        "skipped_existing_ranks": sorted(
            skipped
        ),
        "failures": failed,
    }

    path = (
        CHECKPOINT_DIR
        / (
            f"ranks-{start_rank:04d}-"
            f"{end_rank:04d}.json"
        )
    )

    path.write_text(
        json.dumps(
            checkpoint,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--start-rank",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--end-rank",
        type=int,
        default=1303,
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    if args.start_rank < 1:
        raise ValueError(
            "--start-rank must be >= 1"
        )

    if args.end_rank > 1303:
        raise ValueError(
            "--end-rank must be <= 1303"
        )

    if args.start_rank > args.end_rank:
        raise ValueError(
            "start rank exceeds end rank"
        )

    policy = load_yaml(
        POLICY_PATH
    )

    retry_delays = [
        float(value)
        for value in policy[
            "execution"
        ][
            "retry_backoff_seconds"
        ]
    ]

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    NORMALIZED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    queue_by_rank = {}

    for path in sorted(
        QUEUE_DIR.glob("*.yaml")
    ):
        record = load_yaml(path)

        queue_by_rank[
            int(record["global_rank"])
        ] = path

    completed = []
    skipped = []
    failures = []

    for rank in range(
        args.start_rank,
        args.end_rank + 1,
    ):
        source_path = queue_by_rank.get(
            rank
        )

        if source_path is None:
            failures.append({
                "global_rank": rank,
                "error": (
                    "identity queue record missing"
                ),
            })

            write_checkpoint(
                start_rank=args.start_rank,
                end_rank=args.end_rank,
                completed=completed,
                skipped=skipped,
                failed=failures,
            )

            continue

        output_path = result_path(rank)

        if (
            output_path.exists()
            and not args.overwrite
        ):
            skipped.append(rank)
            continue

        try:
            result = resolve_record(
                path=source_path,
                policy=policy,
                timeout=args.timeout,
                retry_delays=retry_delays,
                delay=args.delay,
            )

            output_path.write_text(
                json.dumps(
                    result,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            completed.append(rank)

        except Exception as exc:
            failures.append({
                "global_rank": rank,
                "error": repr(exc),
            })

        write_checkpoint(
            start_rank=args.start_rank,
            end_rank=args.end_rank,
            completed=completed,
            skipped=skipped,
            failed=failures,
        )

        print(
            f"rank={rank:04d} "
            f"completed={len(completed)} "
            f"skipped={len(skipped)} "
            f"failed={len(failures)}"
        )

    print(
        f"RESOLUTION_RANGE="
        f"{args.start_rank}-{args.end_rank}"
    )
    print(
        f"COMPLETED={len(completed)}"
    )
    print(
        f"SKIPPED_EXISTING={len(skipped)}"
    )
    print(
        f"FAILED={len(failures)}"
    )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
