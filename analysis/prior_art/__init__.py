"""Prior-art analysis capabilities."""

from analysis.prior_art import mutable_corpus_enterprise as _mutable_corpus_enterprise
from analysis.prior_art import mutable_corpus_service as _mutable_corpus_service
from analysis.prior_art.mutable_corpus_enterprise_overrides import (
    build_document_versions as _build_document_versions,
    infer_primary_identity as _infer_primary_identity,
    infer_version_relationships as _infer_version_relationships,
)

_mutable_corpus_enterprise.build_document_versions = _build_document_versions
_mutable_corpus_enterprise.infer_version_relationships = _infer_version_relationships
_mutable_corpus_service.infer_identity = _infer_primary_identity

__all__ = []
