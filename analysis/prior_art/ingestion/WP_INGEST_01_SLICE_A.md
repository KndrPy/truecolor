# WP-INGEST-01 Slice A Closure Contract

## Included capabilities

- CAP-INTAKE-001 — Receive Artifact Stream
- CAP-INTAKE-002 — Detect Actual Media Type
- CAP-INTAKE-003 — Persist Immutable Source

## Explicitly excluded

- archive expansion;
- URL downloading;
- OCR;
- document parsing;
- identity resolution;
- extraction;
- graph projection;
- UI upload workflow.

## Implemented job

Given a local artifact file, preserve its bytes in an immutable
content-addressed store, compute and verify SHA-256, detect the actual
media type from bytes or structure, record a separate intake-attempt
manifest, and validate the manifest and stored object.

## Storage invariant

```text
objects/sha256/<first-2>/<next-2>/<sha256>.blob

The object path is derived only from the content SHA-256.

Deduplication invariant

Two intake attempts containing identical bytes:

produce the same artifact ID;
reference the same immutable object;
preserve separate intake-attempt manifests;
do not overwrite the existing object.
Media-detection precedence
empty artifact;
byte signature;
archive structure;
structured text probe;
text heuristic;
low-confidence filename hint;
application/octet-stream.

The filename cannot override a recognized byte signature.

Failure closure
Failure	Result
missing source	SOURCE_NOT_FOUND
checksum mismatch	CHECKSUM_MISMATCH
size limit exceeded	SIZE_LIMIT_EXCEEDED
invalid size policy	INVALID_MAX_BYTES
existing object hash mismatch	OBJECT_INTEGRITY_FAILURE
Acceptance gates
Python compilation passes.
Unit tests pass.
Adversarial falsification passes.
Same bytes deduplicate.
Separate attempts remain separately manifested.
Misleading extension does not override PDF signature.
Stored bytes re-hash exactly.
JSON Schema validation passes.
Missing, oversized, and checksum-invalid inputs fail explicitly.
No repository raw artifact is required for tests.
Closure evidence
analysis/prior_art/ingestion/reports/intake-unit-tests.txt
analysis/prior_art/ingestion/reports/intake-falsification.json
analysis/prior_art/ingestion/reports/intake-pilot-result.json
analysis/prior_art/ingestion/reports/intake-pilot-validation.json
analysis/prior_art/ingestion/reports/intake-slice-a-closure.json

