# WP-INGEST-01 Slice B Closure Contract

## Capabilities

- CAP-INTAKE-004 — Safely expand ZIP, TAR, and GZIP containers
- CAP-INTAKE-005 — Deterministic artifact and attempt index
- CAP-INTAKE-006 — Access, license, source, and lineage metadata

## Archive safety invariants

1. Absolute paths are rejected.
2. `..`, empty, and dot path segments are rejected.
3. ZIP and TAR symbolic links are rejected.
4. TAR hard links and special members are rejected.
5. Maximum member count is enforced before extraction.
6. Declared member size is enforced before extraction.
7. Observed member size is enforced during extraction.
8. Aggregate expanded size is bounded.
9. Compression ratio is bounded.
10. Archive expansion is explicit and one level per invocation.
11. Every extracted regular file enters the immutable intake kernel.
12. Every child receives parent/root/archive-member lineage metadata.

## Deduplication index invariants

1. One artifact ID corresponds to one SHA-256.
2. One artifact ID corresponds to one immutable object path.
3. Multiple intake attempts may reference one artifact.
4. Attempt IDs are globally unique.
5. Index output is deterministic for identical manifests and metadata.
6. Index hash excludes nondeterministic timestamps.

## Metadata policy invariant

`processing_allowed` is true only when:

```text
access_status == AVAILABLE
AND license_status != PROHIBITED
Closure gates
all modules compile;
Slice A tests remain passing;
Slice B tests pass;
path traversal fails explicitly;
ZIP and TAR links fail explicitly;
member limits fail explicitly;
GZIP expands exactly one child;
identical child bytes deduplicate;
metadata policy gate is correct;
deterministic index output is byte-equivalent;
real ZIP pilot expands and validates.
