from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("analysis/prior_art")
QUERY_REGISTRY = (
    ROOT / "registry/search_query_registry.yaml"
)

DEFAULT_OUTPUT = (
    ROOT / "results/stage1_candidate_harvest.json"
)

USER_AGENT = (
    "TrueColorPriorArt/1.0 "
    "(KndrPy/truecolor; scholarly metadata acquisition)"
)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(f"Expected mapping: {path}")

    return value


def request_json(
    url: str,
    *,
    timeout: int = 30,
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(retries):
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
                payload = response.read()

            value = json.loads(
                payload.decode("utf-8")
            )

            if not isinstance(value, dict):
                raise TypeError(
                    f"Expected JSON object from {url}"
                )

            return value

        except Exception as exc:
            last_error = exc

            if attempt + 1 < retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"Request failed after {retries} attempts: {url}"
    ) from last_error


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None

    doi = value.strip().lower()

    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "doi:",
    ):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]

    return doi or None


def title_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    return str(value or "").strip()


def crossref_candidates(
    query: str,
    *,
    rows: int,
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "query.bibliographic": query,
        "rows": rows,
        "select": (
            "DOI,title,author,published,"
            "published-print,published-online,"
            "type,container-title,URL,abstract,"
            "is-referenced-by-count"
        ),
    })

    url = (
        "https://api.crossref.org/works?"
        + params
    )

    payload = request_json(url)
    items = payload.get(
        "message",
        {},
    ).get("items", [])

    results = []

    for item in items:
        authors = []

        for author in item.get("author", []):
            name = " ".join(
                part
                for part in [
                    author.get("given", ""),
                    author.get("family", ""),
                ]
                if part
            ).strip()

            if name:
                authors.append(name)

        date_parts = (
            item.get("published-print", {})
            .get("date-parts")
            or item.get("published-online", {})
            .get("date-parts")
            or item.get("published", {})
            .get("date-parts")
            or []
        )

        year = None

        if (
            date_parts
            and isinstance(date_parts[0], list)
            and date_parts[0]
        ):
            year = date_parts[0][0]

        results.append({
            "discovery_source": "crossref",
            "query": query,
            "title": title_text(
                item.get("title")
            ),
            "authors": authors,
            "year": year,
            "doi": normalize_doi(
                item.get("DOI")
            ),
            "pmid": None,
            "arxiv": None,
            "publication_type": item.get("type"),
            "venue": title_text(
                item.get("container-title")
            ),
            "url": item.get("URL"),
            "citation_count": item.get(
                "is-referenced-by-count"
            ),
            "abstract_available": bool(
                item.get("abstract")
            ),
        })

    return results


def europe_pmc_candidates(
    query: str,
    *,
    page_size: int,
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "query": query,
        "format": "json",
        "pageSize": page_size,
        "resultType": "core",
    })

    url = (
        "https://www.ebi.ac.uk/"
        "europepmc/webservices/rest/search?"
        + params
    )

    payload = request_json(url)

    items = (
        payload.get("resultList", {})
        .get("result", [])
    )

    results = []

    for item in items:
        author_string = item.get(
            "authorString",
            "",
        )

        authors = [
            value.strip()
            for value in author_string.split(",")
            if value.strip()
        ]

        results.append({
            "discovery_source": "europe_pmc",
            "query": query,
            "title": str(
                item.get("title", "")
            ).strip(),
            "authors": authors,
            "year": item.get("pubYear"),
            "doi": normalize_doi(
                item.get("doi")
            ),
            "pmid": item.get("pmid"),
            "arxiv": None,
            "publication_type": item.get(
                "pubType"
            ),
            "venue": item.get(
                "journalTitle"
            ),
            "url": (
                "https://europepmc.org/article/"
                f"{item.get('source')}/"
                f"{item.get('id')}"
                if item.get("source")
                and item.get("id")
                else None
            ),
            "citation_count": item.get(
                "citedByCount"
            ),
            "abstract_available": bool(
                item.get("abstractText")
            ),
        })

    return results


def canonical_key(
    record: dict[str, Any],
) -> str:
    doi = normalize_doi(record.get("doi"))

    if doi:
        return f"doi:{doi}"

    pmid = record.get("pmid")

    if pmid:
        return f"pmid:{str(pmid).strip()}"

    title = " ".join(
        str(record.get("title", ""))
        .lower()
        .split()
    )

    year = str(
        record.get("year") or "unknown"
    )

    return f"title:{title}|year:{year}"


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--crossref-rows",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--europe-pmc-rows",
        type=int,
        default=20,
    )

    args = parser.parse_args()

    registry = load_yaml(QUERY_REGISTRY)

    candidates_by_key: dict[
        str,
        dict[str, Any],
    ] = {}

    executions = []

    for family in registry["query_families"]:
        query_id = family["query_id"]
        domain = family["domain"]

        execution = {
            "query_family_id": query_id,
            "domain": domain,
            "queries": [],
        }

        for query in family["queries"]:
            query_results = {
                "query": query,
                "crossref_count": 0,
                "europe_pmc_count": 0,
                "errors": [],
            }

            try:
                records = crossref_candidates(
                    query,
                    rows=args.crossref_rows,
                )

                query_results[
                    "crossref_count"
                ] = len(records)

                for record in records:
                    key = canonical_key(record)

                    existing = candidates_by_key.get(
                        key
                    )

                    if existing is None:
                        record["canonical_key"] = key
                        record["domains"] = [domain]
                        record["query_family_ids"] = [
                            query_id
                        ]
                        record["discovery_queries"] = [
                            query
                        ]
                        candidates_by_key[key] = record
                    else:
                        existing["domains"] = sorted(
                            set(
                                existing["domains"]
                            )
                            | {domain}
                        )
                        existing[
                            "query_family_ids"
                        ] = sorted(
                            set(
                                existing[
                                    "query_family_ids"
                                ]
                            )
                            | {query_id}
                        )
                        existing[
                            "discovery_queries"
                        ] = sorted(
                            set(
                                existing[
                                    "discovery_queries"
                                ]
                            )
                            | {query}
                        )

            except Exception as exc:
                query_results["errors"].append({
                    "source": "crossref",
                    "message": str(exc),
                })

            try:
                records = europe_pmc_candidates(
                    query,
                    page_size=args.europe_pmc_rows,
                )

                query_results[
                    "europe_pmc_count"
                ] = len(records)

                for record in records:
                    key = canonical_key(record)

                    existing = candidates_by_key.get(
                        key
                    )

                    if existing is None:
                        record["canonical_key"] = key
                        record["domains"] = [domain]
                        record["query_family_ids"] = [
                            query_id
                        ]
                        record["discovery_queries"] = [
                            query
                        ]
                        candidates_by_key[key] = record
                    else:
                        existing["domains"] = sorted(
                            set(
                                existing["domains"]
                            )
                            | {domain}
                        )
                        existing[
                            "query_family_ids"
                        ] = sorted(
                            set(
                                existing[
                                    "query_family_ids"
                                ]
                            )
                            | {query_id}
                        )
                        existing[
                            "discovery_queries"
                        ] = sorted(
                            set(
                                existing[
                                    "discovery_queries"
                                ]
                            )
                            | {query}
                        )

                        if not existing.get("pmid"):
                            existing["pmid"] = record.get(
                                "pmid"
                            )

            except Exception as exc:
                query_results["errors"].append({
                    "source": "europe_pmc",
                    "message": str(exc),
                })

            execution["queries"].append(
                query_results
            )

            time.sleep(0.15)

        executions.append(execution)

    candidates = sorted(
        candidates_by_key.values(),
        key=lambda row: (
            -int(row.get("citation_count") or 0),
            str(row.get("year") or ""),
            row.get("title", ""),
        ),
    )

    payload = {
        "stage": 1,
        "harvest_version": "1.0.0",
        "query_registry_sha256": hashlib.sha256(
            QUERY_REGISTRY.read_bytes()
        ).hexdigest(),
        "query_family_count": len(
            registry["query_families"]
        ),
        "candidate_count": len(candidates),
        "executions": executions,
        "candidates": candidates,
    }

    payload["content_sha256"] = sha256_json(
        payload
    )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "stage": 1,
                "query_family_count": payload[
                    "query_family_count"
                ],
                "candidate_count": payload[
                    "candidate_count"
                ],
                "output": str(args.output),
                "content_sha256": payload[
                    "content_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
