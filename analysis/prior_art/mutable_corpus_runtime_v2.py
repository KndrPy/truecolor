from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from analysis.prior_art.mutable_corpus_enterprise import (
    EnterpriseCorpusPolicy,
    artifact_hash_manifest,
    validate_projection_integrity,
)
from analysis.prior_art.mutable_corpus_recovery_projection import route_extraction_recovery
from analysis.prior_art.mutable_corpus_runtime import run_runtime as run_runtime_v1


def run_runtime(
    corpus_root: Path,
    output_root: Path,
    policy: EnterpriseCorpusPolicy,
    expected_sources: Mapping[str, Any] | None,
    dependency_manifest: Mapping[str, Any] | None,
    observed_at: str | None,
    backend: Any = None,
) -> Mapping[str, Any]:
    """Run corpus reconciliation, then apply extraction/scientificity separation."""
    result = run_runtime_v1(
        corpus_root,
        output_root,
        policy,
        expected_sources,
        dependency_manifest,
        observed_at,
        backend=backend,
    )
    queue = route_extraction_recovery(output_root)
    artifact_hash_manifest(output_root)
    validate_projection_integrity(output_root)
    return {
        **result,
        "extraction_recovery_count": queue["record_count"],
    }
