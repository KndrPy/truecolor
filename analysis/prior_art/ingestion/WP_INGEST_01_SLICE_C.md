# WP-INGEST-01 Slice C Closure Contract

## Purpose

Close adversarial archive-ingestion gaps remaining after Slice B.

## Capabilities hardened

- CAP-INTAKE-004 — bounded archive expansion
- CAP-INTAKE-005 — unambiguous artifact/attempt identity
- CAP-INTAKE-006 — complete parent/root lineage

## Required invariants

### Archive preflight

All members are inspected before the first child artifact is committed.

Preflight rejects:

- absolute paths;
- dot and parent traversal;
- duplicate normalized member paths;
- ZIP symbolic links;
- TAR symbolic and hard links;
- TAR special files;
- member-count overflow;
- member-size overflow;
- total expanded-size overflow;
- excessive declared compression ratio.

### Directory handling

Explicit ZIP and TAR directory entries do not create child artifacts and
do not cause otherwise valid archives to fail.

### Root lineage

For nested explicit archive expansion:

```text
root_artifact_id = original outermost artifact
parent_artifact_id = immediately containing archive
archive_depth = parent depth + 1
Failure isolation

A preflight failure creates:

no child intake manifest;
no child object;
no child metadata;
no successful expansion manifest.
Duplicate member paths

Two archive entries resolving to the same normalized member path are
rejected with:

DUPLICATE_MEMBER_PATH

They are never silently overwritten or represented as ambiguous children.

Closure gates
Slice A and Slice B regression tests pass;
explicit directory entry succeeds;
duplicate member path fails;
late invalid member leaves no committed child;
nested expansion preserves root lineage;
compression-ratio preflight leaves no child;
all CLI modules execute without warnings;
full intake work package closure report passes.
