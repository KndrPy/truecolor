from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

IDENTITY_ROOT = (
    ROOT
    / "evidence"
    / "identity_resolution"
)

NORMALIZED_ROOT = (
    IDENTITY_ROOT
    / "normalized"
)

RANKING_CANDIDATES = [
    ROOT / "evidence/ranking/global_ranking.json",
    ROOT / "evidence/ranking/global_ranking.jsonl",
    ROOT / "global_ranking.json",
    ROOT / "global_ranking.jsonl",
]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON object: {path}"
        )

    return value


def canonical_json_bytes(
    value: Any,
) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def stable_id(
    prefix: str,
    value: Any,
) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(value)
    ).hexdigest()[:24]

    return f"{prefix}:{digest}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def evidence_timestamp(
    result: dict[str, Any],
) -> str:
    candidate_fields = [
        "resolved_at",
        "completed_at",
        "created_at",
        "timestamp",
    ]

    for field in candidate_fields:
        value = str(
            result.get(field)
            or ""
        ).strip()

        if value:
            return value

    retrieval_times = []

    for evidence in result.get(
        "retrieval_evidence",
        [],
    ):
        for field in [
            "retrieved_at",
            "timestamp",
            "created_at",
        ]:
            value = str(
                evidence.get(field)
                or ""
            ).strip()

            if value:
                retrieval_times.append(
                    value
                )

    if retrieval_times:
        return sorted(
            retrieval_times
        )[-1]

    return "1970-01-01T00:00:00Z"


def publication_node_type(
    publication_type: str | None,
    state: str,
) -> str:
    normalized = str(
        publication_type or ""
    ).strip().lower()

    if normalized == "dataset":
        return "DATASET"

    if normalized == "grant":
        return "GRANT"

    if normalized in {
        "posted-content",
        "supplement",
        "component",
    }:
        return "SUPPLEMENT"

    if normalized == "standard":
        return "STANDARD"

    if state == "NON_SCHOLARLY":
        return "SUPPLEMENT"

    return "PAPER"


def record_label(
    rank: int,
    result: dict[str, Any],
) -> str:
    metadata = result.get(
        "normalized_metadata",
        {},
    )

    title = str(
        metadata.get("title")
        or ""
    ).strip()

    venue = str(
        metadata.get("venue")
        or ""
    ).strip()

    doi = str(
        metadata.get("doi")
        or ""
    ).strip()

    if title:
        return title

    if venue:
        return venue

    if doi:
        return doi

    return f"Stage 1 identity record {rank:04d}"


def evidence_locator(
    artifact_id: str,
    locator_value: str,
    source_sha256: str | None,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "locator_type": "API_RESPONSE",
        "locator_value": locator_value,
        "quoted_text": None,
        "source_sha256": source_sha256,
    }


def metadata_locator(
    artifact_id: str,
    locator_value: str,
    source_sha256: str,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "locator_type": "METADATA",
        "locator_value": locator_value,
        "quoted_text": None,
        "source_sha256": source_sha256,
    }


def add_node(
    nodes: list[dict[str, Any]],
    seen: set[str],
    node: dict[str, Any],
) -> None:
    node_id = node["node_id"]

    if node_id in seen:
        return

    seen.add(node_id)
    nodes.append(node)


def add_edge(
    edges: list[dict[str, Any]],
    seen: set[str],
    edge: dict[str, Any],
) -> None:
    edge_id = edge["edge_id"]

    if edge_id in seen:
        return

    seen.add(edge_id)
    edges.append(edge)


def build_graph(
    start_rank: int,
    end_rank: int,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    normalized_paths = []

    for rank in range(
        start_rank,
        end_rank + 1,
    ):
        path = (
            NORMALIZED_ROOT
            / f"global-{rank:04d}.json"
        )

        if path.is_file():
            normalized_paths.append(
                (rank, path)
            )

    manifest_basis = {
        "start_rank": start_rank,
        "end_rank": end_rank,
        "normalized_files": [
            {
                "rank": rank,
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for rank, path in normalized_paths
        ],
    }

    source_manifest_sha256 = (
        hashlib.sha256(
            canonical_json_bytes(
                manifest_basis
            )
        ).hexdigest()
    )

    artifact_node_by_candidate: dict[
        str,
        str,
    ] = {}

    pending_related_edges: list[
        tuple[str, str, int]
    ] = []

    evidence_timestamps = []

    for rank, path in normalized_paths:
        result = load_json(path)

        assessed_at = evidence_timestamp(
            result
        )

        evidence_timestamps.append(
            assessed_at
        )

        state = str(
            result["resolution_state"]
        )

        metadata = result.get(
            "normalized_metadata",
            {},
        )

        candidate_key = str(
            result.get("candidate_key")
            or f"global-{rank:04d}"
        )

        artifact_id = (
            f"artifact:stage1:{candidate_key}"
        )

        artifact_node_by_candidate[
            candidate_key
        ] = artifact_id

        publication_type = metadata.get(
            "publication_type"
        )

        trust_value = (
            1.0
            if state == "VERIFIED"
            else 0.5
            if state in {
                "UNRESOLVED",
                "CONFLICT",
            }
            else 0.9
            if state == "NON_SCHOLARLY"
            else None
        )

        artifact_node = {
            "node_id": artifact_id,
            "node_type": publication_node_type(
                publication_type,
                state,
            ),
            "label": record_label(
                rank,
                result,
            ),
            "properties": {
                "global_rank": rank,
                "candidate_key": candidate_key,
                "resolution_state": state,
                "resolution_reason": result.get(
                    "resolution_reason"
                ),
                "version_relationship": result.get(
                    "version_relationship"
                ),
                "authoritative_source": result.get(
                    "authoritative_source"
                ),
                "title": metadata.get("title"),
                "authors": metadata.get(
                    "authors",
                    [],
                ),
                "year": metadata.get("year"),
                "venue": metadata.get("venue"),
                "doi": metadata.get("doi"),
                "pmid": metadata.get("pmid"),
                "pmcid": metadata.get("pmcid"),
                "arxiv": metadata.get("arxiv"),
                "publication_type": publication_type,
                "publication_status": metadata.get(
                    "publication_status"
                ),
                "relation": metadata.get(
                    "relation",
                    {},
                ),
                "claim_status": "NOT_ASSESSED",
                "truth_status": "NOT_ASSESSED",
                "novelty_status": "NOT_ASSESSED",
            },
            "provenance": [
                metadata_locator(
                    artifact_id,
                    str(path),
                    sha256_file(path),
                )
            ],
            "trust": [
                {
                    "dimension": (
                        "identity_confidence"
                    ),
                    "value": trust_value,
                    "basis": (
                        "Stage 1 identity "
                        f"resolution state: {state}"
                    ),
                    "assessed_by": (
                        "stage1_identity_resolver"
                    ),
                    "assessed_at": assessed_at,
                }
            ],
            "review_status": (
                "MACHINE_REVIEWED"
            ),
        }

        add_node(
            nodes,
            node_ids,
            artifact_node,
        )

        adjudication_id = (
            f"adjudication:stage1:{rank:04d}"
        )

        adjudication_node = {
            "node_id": adjudication_id,
            "node_type": "ADJUDICATION",
            "label": (
                "Stage 1 identity adjudication "
                f"for rank {rank:04d}"
            ),
            "properties": {
                "global_rank": rank,
                "resolution_state": state,
                "resolution_reason": result.get(
                    "resolution_reason"
                ),
                "field_comparison": result.get(
                    "field_comparison",
                    {},
                ),
                "conflicts": result.get(
                    "conflicts",
                    [],
                ),
                "attempted_identifiers": (
                    result.get(
                        "attempted_identifiers",
                        [],
                    )
                ),
            },
            "provenance": [
                metadata_locator(
                    artifact_id,
                    str(path),
                    sha256_file(path),
                )
            ],
            "trust": [],
            "review_status": (
                "MACHINE_REVIEWED"
            ),
        }

        add_node(
            nodes,
            node_ids,
            adjudication_node,
        )

        adjudication_edge = {
            "edge_id": (
                f"edge:identity-adjudication:"
                f"{rank:04d}"
            ),
            "edge_type": "DERIVES_FROM",
            "source_node_id": adjudication_id,
            "target_node_id": artifact_id,
            "properties": {
                "stage": "STAGE_1",
                "relationship": (
                    "IDENTITY_ADJUDICATION_FOR"
                ),
            },
            "provenance": [
                metadata_locator(
                    artifact_id,
                    str(path),
                    sha256_file(path),
                )
            ],
            "confidence": 1.0,
            "review_status": (
                "MACHINE_REVIEWED"
            ),
            "valid_from": None,
            "valid_to": None,
        }

        add_edge(
            edges,
            edge_ids,
            adjudication_edge,
        )

        for evidence_index, evidence in enumerate(
            result.get(
                "retrieval_evidence",
                [],
            ),
            start=1,
        ):
            raw_path = Path(
                evidence["raw_path"]
            )

            raw_sha256 = evidence.get(
                "raw_sha256"
            )

            source = str(
                evidence.get("source")
                or "unknown"
            )

            snapshot_id = stable_id(
                "snapshot",
                {
                    "rank": rank,
                    "source": source,
                    "raw_path": str(raw_path),
                    "raw_sha256": raw_sha256,
                },
            )

            snapshot_node = {
                "node_id": snapshot_id,
                "node_type": (
                    "SOURCE_SNAPSHOT"
                ),
                "label": (
                    f"{source} snapshot "
                    f"for rank {rank:04d}"
                ),
                "properties": {
                    "global_rank": rank,
                    "source": source,
                    "raw_path": str(raw_path),
                    "raw_sha256": raw_sha256,
                    "retrieval_index": (
                        evidence_index
                    ),
                },
                "provenance": [
                    evidence_locator(
                        artifact_id,
                        str(raw_path),
                        raw_sha256,
                    )
                ],
                "trust": [],
                "review_status": (
                    "MACHINE_REVIEWED"
                ),
            }

            add_node(
                nodes,
                node_ids,
                snapshot_node,
            )

            observed_edge = {
                "edge_id": stable_id(
                    "edge:observed-in",
                    {
                        "artifact": artifact_id,
                        "snapshot": snapshot_id,
                    },
                ),
                "edge_type": "OBSERVED_IN",
                "source_node_id": artifact_id,
                "target_node_id": snapshot_id,
                "properties": {
                    "source": source,
                },
                "provenance": [
                    evidence_locator(
                        artifact_id,
                        str(raw_path),
                        raw_sha256,
                    )
                ],
                "confidence": 1.0,
                "review_status": (
                    "MACHINE_REVIEWED"
                ),
                "valid_from": None,
                "valid_to": None,
            }

            add_edge(
                edges,
                edge_ids,
                observed_edge,
            )

        for related_key in result.get(
            "related_candidate_keys",
            [],
        ):
            pending_related_edges.append(
                (
                    artifact_id,
                    str(related_key),
                    rank,
                )
            )

    for (
        source_artifact_id,
        related_candidate_key,
        rank,
    ) in pending_related_edges:
        target_artifact_id = (
            artifact_node_by_candidate.get(
                related_candidate_key
            )
        )

        if target_artifact_id is None:
            continue

        relation_basis = {
            "source": source_artifact_id,
            "target": target_artifact_id,
            "relation": "SAME_WORK_AS",
        }

        add_edge(
            edges,
            edge_ids,
            {
                "edge_id": stable_id(
                    "edge:same-work-as",
                    relation_basis,
                ),
                "edge_type": "SAME_WORK_AS",
                "source_node_id": (
                    source_artifact_id
                ),
                "target_node_id": (
                    target_artifact_id
                ),
                "properties": {
                    "basis": (
                        "Stage 1 related "
                        "candidate linkage"
                    ),
                    "global_rank": rank,
                },
                "provenance": [
                    {
                        "artifact_id": (
                            source_artifact_id
                        ),
                        "locator_type": (
                            "METADATA"
                        ),
                        "locator_value": (
                            "related_candidate_keys"
                        ),
                        "quoted_text": None,
                        "source_sha256": None,
                    }
                ],
                "confidence": 0.8,
                "review_status": (
                    "MACHINE_REVIEWED"
                ),
                "valid_from": None,
                "valid_to": None,
            },
        )

    nodes.sort(
        key=lambda item: item["node_id"]
    )

    edges.sort(
        key=lambda item: item["edge_id"]
    )

    return {
        "graph_id": (
            f"truecolor-stage1-identity-"
            f"{start_rank:04d}-{end_rank:04d}"
        ),
        "schema_version": "1.0.0",
        "created_at": (
            sorted(evidence_timestamps)[-1]
            if evidence_timestamps
            else "1970-01-01T00:00:00Z"
        ),
        "source_manifest_sha256": (
            source_manifest_sha256
        ),
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--start-rank",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--end-rank",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    if args.start_rank < 1:
        raise ValueError(
            "start-rank must be >= 1"
        )

    if args.end_rank < args.start_rank:
        raise ValueError(
            "end-rank must be >= start-rank"
        )

    graph = build_graph(
        args.start_rank,
        args.end_rank,
    )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(
            graph,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"GRAPH_OUTPUT={args.output}"
    )
    print(
        f"GRAPH_NODES={len(graph['nodes'])}"
    )
    print(
        f"GRAPH_EDGES={len(graph['edges'])}"
    )
    print(
        "STAGE1_IDENTITY_GRAPH_BUILD=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
