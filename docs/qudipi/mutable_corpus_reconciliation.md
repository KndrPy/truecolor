# Mutable Corpus Reconciliation

## Purpose

QuDiPi treats the researcher-controlled intake directory as mutable runtime input. Files may be added, removed, renamed, replaced, or reordered at any time. Filenames and prior review queues are never scientific identity authority.

The authoritative runtime entry point is:

```bash
python -m analysis.prior_art.mutable_corpus_service \
  --corpus-root preprocessed_intake/corpus_prior_art_paper-pdf \
  --output-root artifacts/stage_01/corpus_runtime
```

The intake directory remains excluded from Git. Generated registries are projections of the current filesystem and extracted document content.

## Identity hierarchy

Each physical file is evaluated from its bytes and extracted contents:

1. Binary SHA-256 identifies byte-exact duplicates.
2. Normalized full-text SHA-256 identifies equivalent text encodings.
3. DOI, PMID, and arXiv identifiers establish bibliographic identity.
4. Extracted title, authors, publication year, venue, and content fingerprint support identity when identifiers are absent.
5. Distinct resolved DOI or PMID values prevent similar documents from being collapsed into one work.

The service models physical files and scientific works separately. Multiple files may resolve to one work when they are duplicate copies or supported versions of the same publication.

## Relationship states

- `EXACT_FILE_DUPLICATE`: identical file bytes.
- `SAME_WORK_SAME_VERSION`: equivalent content or shared canonical identifier.
- `SAME_WORK_DIFFERENT_VERSION`: supported preprint, manuscript, conference, or journal version relationship.
- `RELATED_WORK`: scientifically related documents that remain distinct works.

Low-confidence similarity never removes a document. Ambiguous content remains represented as an independent work until stronger evidence is available.

## Mutable change events

Comparing the current snapshot with a prior snapshot emits:

- `FILE_ADDED`
- `FILE_REMOVED`
- `FILE_MOVED`
- `FILE_REPLACED`
- `IDENTITY_CHANGED`

A rename is detected by matching unchanged binary content across removed and added paths. A replacement is detected when the same path has different bytes.

## Outputs

A successful run atomically writes:

- `corpus_snapshot.json`
- `physical_file_registry.json`
- `scientific_work_registry.json`
- `document_relationships.json`
- `missing_reference_candidates.json`
- `corpus_policy_effective.json`
- `corpus_change_set.json`
- `stale_downstream_artifact_report.json`

The snapshot identifier is deterministic for the corpus contents, inferred identities, relationships, and effective policy. Observation time is excluded from the snapshot hash.

## Missing references

DOIs found in reference sections but absent from the current corpus are emitted as `CITED_WORK_NOT_INGESTED` candidates. QuDiPi does not silently download, exclude, or declare those works unavailable. Acquisition is a separate policy-controlled capability.

## Downstream invalidation

A dependency manifest may identify generated artifacts and their `source_file_ids`. When source files are added, removed, moved, replaced, or reidentified, only declared dependent artifacts are marked `STALE`.

Example:

```json
{
  "artifacts": [
    {
      "artifact_path": "artifacts/stage_01/evidence/example.json",
      "source_file_ids": ["FILE-0123456789abcdef0123"]
    }
  ]
}
```

## Operational guarantees

- No fixed corpus count.
- No filename-order dependency.
- No stale review list as corpus authority.
- No deletion of historical snapshots by reconciliation.
- No autonomous scientific exclusion or novelty adjudication.
- Atomic projection writes.
- Deterministic registries for unchanged corpus state.
- Explicit extraction failures and insufficient-text states.

## Validation

The falsification suite covers arbitrary filenames, exact duplicates, distinct identifiers, rename detection, replacement detection, runtime inclusion and exclusion policy, missing-reference candidates, selective downstream invalidation, and deterministic snapshot identity.

```bash
python -m pytest -q tests/qudipi/test_mutable_corpus_service.py
```
