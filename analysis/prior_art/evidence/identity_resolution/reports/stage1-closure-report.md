# Stage 1 Identity Resolution Closure

## Scope

Canonical identity resolution for the complete ranked prior-art corpus.

## Corpus coverage

- Expected ranked candidates: 1,303
- Present normalized records: 1,303
- Missing ranked records: 0
- Duplicate ranked records: 0

## Resolution-state distribution

| Resolution state | Count |
|---|---:|
| VERIFIED | 1,221 |
| CONFLICT | 19 |
| CORRECTION_ONLY | 1 |
| NON_SCHOLARLY | 15 |
| UNRESOLVED | 47 |
| **Total** | **1,303** |

`CONFLICT`, `CORRECTION_ONLY`, `NON_SCHOLARLY`, and `UNRESOLVED`
are explicit terminal adjudication states. They are not missing records
or execution failures.

## Production execution

- Newly produced records in final production execution: 1,156
- Selected records not created: 0
- Failed batches: 0
- Present after execution: 1,303
- Missing after execution: 0

## Evidence validation

The full corpus closure validation confirmed:

- every expected rank exists exactly once;
- every normalized record is valid JSON;
- every normalized record passes the Stage 1 validator;
- every referenced raw evidence file exists;
- every referenced raw evidence SHA-256 matches its stored bytes.

## Graph projection

The complete deterministic Stage 1 identity graph contains:

| Graph object | Count |
|---|---:|
| Nodes | 4,446 |
| Edges | 3,311 |
| Artifact nodes | 1,303 |
| Adjudication nodes | 1,303 |
| Source snapshot nodes | 1,840 |
| DERIVES_FROM edges | 1,303 |
| OBSERVED_IN edges | 1,840 |
| SAME_WORK_AS edges | 168 |

Graph integrity results:

- Unique node IDs: 4,446
- Unique edge IDs: 3,311
- Unique artifact ranks: 1,303
- Dangling edges: 0
- Invalid adjudication-edge directions: 0
- Semantic audit: PASS

## Artifact-type distribution

| Artifact type | Count |
|---|---:|
| PAPER | 1,157 |
| SUPPLEMENT | 118 |
| DATASET | 13 |
| STANDARD | 13 |
| GRANT | 2 |
| **Total** | **1,303** |

## Deterministic graph artifact

Path:

```text
analysis/prior_art/graph_ir/generated/stage1-full-1303.json

SHA-256:

c36543e838288854dc4f0395b0352bfd78d7291a9ec80cc7a0507c461460bfbb
Closure decision

Stage 1 identity resolution is complete.

WP-STAGE-1: CLOSED

WP-GRAPH-02B: CLOSED

The next implementation boundary is universal prior-work ingestion and
canonical document normalization for PDF, text, XML, JATS, TEI, HTML,
DOCX, JSON, JSONL, and CSV artifacts.
