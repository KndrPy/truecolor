# WP-PARSE-01 Slice B4

## Closed capability

### CAP-PARSE-010 — Deterministic parser failure and retry ledger

Every CLI-driven parse execution is represented by an immutable, deterministic parse-attempt record linked to its intake attempt, input manifest, parser route, canonical output, and any prior parse attempt.

The ledger records successful and failed terminal outcomes without changing the parser-specific execution contracts or the direct `parse_intake_manifest()` API.

## Attempt identity

A parse-attempt identifier is derived from:

- the SHA-256 digest of the immutable intake manifest;
- the resolved canonical-output root;
- the parser implementation version;
- the explicit prior parse-attempt identifier, when present.

The identifier does not depend on wall-clock time, UUIDs, process identity, or filesystem enumeration order.

Format:

```text
parse:<64 lowercase hexadecimal characters>
Attempt state contract

Each persisted attempt has exactly two recorded states:

STARTED → SUCCEEDED
STARTED → FAILED

The final record is written atomically after the parser reaches a terminal outcome.

No partial attempt record is exposed.

Success contract

A successful record captures:

parse-attempt identity;
optional prior-attempt identity;
intake-attempt identity;
artifact identity;
content SHA-256;
resolved manifest path;
manifest SHA-256;
parser route, implementation name, and version;
canonical document identity;
resolved canonical output path;
SUCCEEDED terminal state;
null error payload.

A repeated invocation with the same deterministic inputs:

resolves to the same parse-attempt identity;
reads the existing immutable success record;
does not execute the parser again;
returns the referenced canonical document when it remains available.
Failure contract

A failed record captures:

the same execution and source identities as a successful record;
FAILED terminal state;
stable error code;
bounded diagnostic message;
retryability flag;
exception type;
null canonical document identity;
null canonical output path.

Diagnostic messages are limited to 1,024 characters.

A repeated invocation of the same failed attempt:

resolves to the same parse-attempt identity;
replays the persisted failure;
does not execute the parser again;
does not mutate or overwrite the persisted record.
Retry contract

A retry is explicit.

The caller supplies the failed or prior parse-attempt identifier through:

--prior-parse-attempt-id

The prior identifier becomes part of the new attempt identity. The retry therefore receives a distinct immutable record while preserving lineage to the prior attempt.

This slice does not automatically schedule or initiate retries.

Canonical-output integrity

Canonical documents continue to use the existing atomic write implementation.

A parser failure:

persists a failed parse-attempt record;
does not produce a canonical document;
leaves no partial *.canonical.json file.

A prior successful attempt whose referenced canonical output is missing is not silently re-executed. The CLI reports IDEMPOTENT_OUTPUT_MISSING.

CLI contract

The parser CLI accepts:

--manifest
--output-root
--attempt-root
--prior-parse-attempt-id

When --attempt-root is omitted, records are stored beneath:

<output-root>/_parse_attempts

Successful CLI output includes:

status;
parse_attempt_id;
attempt_record;
document_id;
parser route;
segment count;
page count;
canonical output path.

Failed CLI output includes:

status;
parse_attempt_id, when an attempt was established;
attempt-record path, when persisted;
structured failure data.
Persistence contract

Each terminal record is serialized as sorted, indented UTF-8 JSON with a trailing newline and written through temporary-file replacement.

Record location:

<attempt-root>/<digest-prefix>/<digest>/parse-attempt.json

The parse-attempt record must validate against:

schemas/parse_attempt.schema.json
Acceptance criteria
Attempt identity is deterministic for identical execution inputs.
A prior-attempt link changes the attempt identity.
Success records are persisted and schema-valid.
Failure records are persisted and schema-valid.
Intake, artifact, manifest, content, and parser identities are captured.
Error diagnostics are bounded.
Failed parsing leaves no canonical output.
Repeated success does not execute the parser again.
Repeated failure does not execute the parser again.
Existing direct callers of parse_intake_manifest() remain compatible.
Existing parser and CLI regressions remain green.
Record serialization is byte-stable across repeated resolution.
Validation evidence
Focused parse-attempt tests: 9.
Existing ingestion and parser regression tests: 51.
Final combined expected test count: 60.
Explicit exclusions

This slice does not add:

automatic retry scheduling;
exponential backoff;
retry-count limits;
work queues;
distributed locking;
concurrent claim or lease management;
parser repair;
alternate parser selection;
telemetry export;
wall-clock timestamps;
cross-format canonical equivalence validation.
