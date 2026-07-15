"""Prior-art analysis capabilities."""

from analysis.prior_art import mutable_corpus_enterprise as _mutable_corpus_enterprise
from analysis.prior_art.mutable_corpus_enterprise_overrides import (
    build_document_versions as _build_document_versions,
)

_mutable_corpus_enterprise.build_document_versions = _build_document_versions

__all__ = []
