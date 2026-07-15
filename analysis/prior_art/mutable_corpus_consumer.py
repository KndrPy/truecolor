from __future__ import annotations

import argparse
import contextlib
import fcntl
from pathlib import Path
from typing import Any, Iterable, Mapping

from analysis.prior_art.mutable_corpus import ExtractionBackend, PopplerExtractionBackend
from analysis.prior_art.mutable_corpus_closure_validator import validate_consumer_closure
from analysis.prior_art.mutable_corpus_contracts import write_contract_projections
from analysis.prior_art.mutable_corpus_enterprise import (
    EnterpriseCorpusError,
    EnterpriseCorpusPolicy,
    artifact_hash_manifest,
    atomic_write_json,
    validate_projection_integrity,
)
from analysis.prior_art.mutable_corpus_runtime import (
    expected_sources_from_review_csv,
    load_optional,
    merge_expected_sources,
    run_runtime,
)


@contextlib.contextmanager
def consumer_lock(output_root: Path) -> Iterable[None]:
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".mutable_corpus_consumer.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EnterpriseCorpusError(
                f"another consumer reconciliation is active: {lock_path}"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_consumer_reconciliation(
    corpus_root: Path,
    output_root: Path,
    policy: EnterpriseCorpusPolicy,
    expected_sources: Mapping[str, Any] | None,
    dependency_manifest: Mapping[str, Any] | None,
    observed_at: str | None,
    backend: ExtractionBackend | None = None,
) -> Mapping[str, Any]:
    corpus_root = corpus_root.resolve()
    output_root = output_root.resolve()
    extraction_backend = backend or PopplerExtractionBackend(
        policy.extraction_timeout_seconds
    )
    closure_path = output_root / "MUTABLE_CORPUS_RECONCILIATION_CLOSED.json"
    with consumer_lock(output_root):
        if closure_path.exists():
            closure_path.unlink()
        result = run_runtime(
            corpus_root,
            output_root,
            policy,
            expected_sources,
            dependency_manifest,
            observed_at,
            backend=extraction_backend,
        )
        write_contract_projections(
            corpus_root,
            output_root,
            expected_sources,
            extraction_backend,
        )
        artifact_hash_manifest(output_root)
        validate_projection_integrity(output_root)
        semantic_gates = validate_consumer_closure(output_root)
        closure = {
            "schema": "qudipi.mutable-corpus.closure-evidence",
            "schema_version": 2,
            "run_id": result["run_id"],
            "snapshot_id": result["snapshot_id"],
            "semantic_gates": semantic_gates,
            "capability_state": "CLOSED",
        }
        atomic_write_json(closure_path, closure)
        artifact_hash_manifest(output_root)
        validate_projection_integrity(output_root)
        return {**result, "capability_state": "CLOSED", "semantic_gates": semantic_gates}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the complete QuDiPi consumer-grade mutable corpus capability."
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--expected-sources")
    parser.add_argument("--prior-review-csv")
    parser.add_argument("--dependency-manifest")
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    policy = EnterpriseCorpusPolicy.from_mapping(
        load_optional(Path(args.policy)) if args.policy else None
    )
    explicit = load_optional(Path(args.expected_sources)) if args.expected_sources else None
    review = expected_sources_from_review_csv(
        Path(args.prior_review_csv) if args.prior_review_csv else None
    )
    expected = merge_expected_sources(explicit, review)
    dependencies = (
        load_optional(Path(args.dependency_manifest))
        if args.dependency_manifest
        else None
    )
    result = run_consumer_reconciliation(
        Path(args.corpus_root),
        Path(args.output_root),
        policy,
        expected,
        dependencies,
        args.observed_at,
    )
    print("QUDIPI_MUTABLE_CORPUS_CONSUMER=PASS")
    print(f"run_id={result['run_id']}")
    print(f"snapshot_id={result['snapshot_id']}")
    print(f"capability_state={result['capability_state']}")
    for gate, state in sorted(result["semantic_gates"].items()):
        print(f"gate.{gate}={state}")


if __name__ == "__main__":
    main()
