# MutableCorpusReconciliation

`MutableCorpusReconciliation` is QuDiPi's content-driven intake boundary for a researcher-controlled scientific corpus. The directory is mutable: researchers may add, remove, rename, replace, include, or exclude documents without preserving filename order or a fixed manifest.

## Canonical entry point

```bash
python -m analysis.prior_art.mutable_corpus_consumer \
  --corpus-root preprocessed_intake/corpus_prior_art_paper-pdf \
  --output-root artifacts/stage_01/corpus_runtime \
  --prior-review-csv artifacts/stage_01/disposition_review/corpus_disposition_review.csv
```

Optional inputs:

- `--policy`: enterprise resource, inclusion, exclusion, and similarity policy.
- `--expected-sources`: expected source and claim mappings.
- `--prior-review-csv`: converts prior bibliographic records into non-authoritative expected-source inputs.
- `--dependency-manifest`: maps downstream artifacts to source file IDs for selective invalidation.
- `--observed-at`: deterministic test or replay timestamp.

## Identity boundary

Scientific identity is derived from PDF content and metadata. Filename numbering and prior review order are never identity evidence. The runtime uses:

- PDF signature validation and resource bounds;
- binary SHA-256 and normalized-text SHA-256;
- primary DOI, PMID, and arXiv extraction from the bibliographic region before references;
- title, author, venue, year, page count, and bibliographic page range;
- normalized publisher locators;
- MinHash, SimHash, abstract, section-heading, and reference fingerprints;
- conservative duplicate, same-version, different-version, related-work, and ambiguity rules.

Conflicting resolved identifiers are never silently collapsed. They enter `ambiguous_identity_queue.json`.

## Durable model

The runtime maintains separate projections for:

- physical files and their path/hash lifecycle;
- physical-file-to-document-version bindings;
- document versions;
- canonical scientific works;
- duplicate and version-family relationships;
- immutable snapshots and an append-only event ledger.

Renaming preserves scientific identity. Replacement, removal, duplicate creation, duplicate resolution, and version-family changes produce explicit events. Removed files remain represented in lifecycle history.

## Authority boundary

The runtime may discover, extract, normalize, classify, group, report, and invalidate dependent artifacts. It does not autonomously:

- decide scientific novelty;
- exclude relevant scientific work without an explicit rule;
- declare a locally absent source unavailable;
- select a scientifically authoritative publication version;
- download missing sources silently.

`preferred_file_id` is a processing preference only. Researcher or explicit policy authority is required for scientific adjudication.

## Required projections

Each successful consumer run produces:

```text
corpus_snapshot.json
scientific_work_registry.json
document_version_registry.json
physical_file_registry.json
physical_file_version_registry.json
physical_file_lifecycle_registry.json
exact_duplicate_report.json
version_family_report.json
work_identity_state_registry.json
ambiguous_identity_queue.json
unreadable_document_report.json
non_scientific_document_report.json
corpus_change_set.json
stale_downstream_artifact_report.json
missing_reference_candidates.json
claim_source_coverage_report.json
stage1_review_queue_projection.json
bibliographic_locator_registry.json
scientific_authority_boundary.json
reconciliation_run_manifest.json
mutable_corpus_contract.json
artifact_hashes.json
```

Historical evidence is written under:

```text
history/corpus_event_ledger.jsonl
history/snapshots/SNAPSHOT-*.json
```

## Closure semantics

`MUTABLE_CORPUS_RECONCILIATION_CLOSED.json` is removed at the beginning of every run. It is recreated only after required-output, referential-integrity, state-space, failure-preservation, durable-history, Stage 1 projection, authority-boundary, and fixed-corpus-prohibition gates pass.

A closure marker proves the completed runtime instance. It does not decide novelty or close Stage 1 scientific adjudication.
