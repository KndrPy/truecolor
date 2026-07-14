# WP-PARSE-01 Parent Closure

## Work package

WP-PARSE-01 closes deterministic, provenance-preserving canonical parsing for the supported prior-art artifact formats.

## Closed capability inventory

### CAP-PARSE-001 — Deterministic parser routing

A normalized detected media type resolves to one registered parser route or fails explicitly with `UNSUPPORTED_MEDIA_TYPE`.

Closed by:

```text
WP_PARSE_01_SLICE_A.md
CAP-PARSE-002 — Embedded PDF text and word geometry extraction

PDF embedded text is extracted with page-level geometry and canonical segment provenance.

Closed by:

WP_PARSE_01_SLICE_A.md
CAP-PARSE-003 — Page-level OCR requirement classification

Every PDF page receives a deterministic OCR requirement assessment.

Closed by:

WP_PARSE_01_SLICE_A.md
CAP-PARSE-004 — OCR execution with page-level provenance

Pages requiring OCR are rendered and recognized with engine, language, confidence, DPI, and coordinate provenance.

Closed by:

WP_PARSE_01_SLICE_B2.md
CAP-PARSE-005 — XML, JATS, and TEI canonicalization

Registered XML-family media types are normalized into deterministic canonical text and source paths.

Closed by:

WP_PARSE_01_SLICE_A.md
CAP-PARSE-006 — Deterministic HTML structure hardening

HTML parsing handles malformed structure deterministically, suppresses excluded content, preserves semantic ordering, and emits indexed source paths.

Closed by:

WP_PARSE_01_SLICE_B3.md
CAP-PARSE-007 — Text and Markdown canonicalization

Plain-text and Markdown artifacts are normalized with deterministic canonical ranges and source offsets.

Closed by:

WP_PARSE_01_SLICE_A.md
CAP-PARSE-008 — DOCX canonicalization

DOCX paragraphs and tables are normalized with document-part and table-cell provenance.

Closed by:

WP_PARSE_01_SLICE_B1.md
CAP-PARSE-009 — Tabular artifact normalization

CSV, TSV, and XLSX artifacts are normalized into typed table, row, cell, and canonical-segment structures.

Closed by:

WP_PARSE_01_SLICE_B1.md
CAP-PARSE-010 — Deterministic parser failure and retry ledger

CLI parse execution persists immutable success or failure records with deterministic attempt identity and explicit retry lineage.

Closed by:

WP_PARSE_01_SLICE_B4.md
CAP-PARSE-011 — Canonical-to-source coordinate mapping

Every canonical segment retains route-appropriate source coordinates, paths, geometry, document-part, table, row, column, or cell provenance.

Closed by:

WP_PARSE_01_SLICE_A.md

Extended by:

WP_PARSE_01_SLICE_B1.md
WP_PARSE_01_SLICE_B2.md
WP_PARSE_01_SLICE_B3.md
CAP-PARSE-012 — Cross-format canonical validation

Every registered route is subject to shared canonical invariants, route-specific provenance validation, deterministic document identity, stable serialization, and bounded cross-format equivalence checks.

Closed by:

WP_PARSE_01_SLICE_B5.md
Supported parser routes

The closed route set is:

PDF
XML
HTML
TEXT
MARKDOWN
DOCX
CSV
TSV
XLSX

The registered media types include:

application/pdf
application/xml
text/xml
application/jats+xml
application/tei+xml
text/html
application/xhtml+xml
text/plain
text/markdown
application/vnd.openxmlformats-officedocument.wordprocessingml.document
text/csv
text/tab-separated-values
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Canonical document contract

Every successfully parsed artifact produces a schema-valid canonical document containing:

deterministic document identity;
artifact and content identity;
source media type;
parser route, name, and version;
canonical text;
ordered canonical segments;
route-specific source provenance;
PDF page and OCR assessment structures where applicable;
tabular structures where applicable;
terminal PARSED status.

The document validates against:

schemas/canonical_document.schema.json
Determinism contract

For identical immutable input bytes and parser implementation version:

parser routing is stable;
canonical text is stable;
segments are stable;
page structures are stable;
OCR assessments are stable for the same toolchain outputs;
table structures are stable;
document identity is stable;
output path is stable;
serialized canonical output is byte-stable.
Provenance contract

Canonical content remains resolvable to route-appropriate source evidence.

Depending on format, provenance includes:

source character offsets;
PDF page number and bounding box;
embedded or OCR extraction method;
OCR confidence, engine, language, and render DPI;
XML or HTML structural path;
DOCX document part and paragraph index;
table index, row index, column index, sheet name, and cell reference.
Failure contract

Unsupported media types and parser failures produce explicit structured errors.

CLI-driven parsing additionally persists an immutable parse-attempt record containing:

parse-attempt identity;
prior-attempt lineage;
intake-attempt identity;
artifact and manifest identity;
parser identity;
terminal success or failure;
canonical output identity on success;
bounded structured diagnostics on failure.

Failed parsing produces no partial canonical document.

Validation contract

The parent closure requires all slice closure reports to pass:

parse-slice-a-closure.json
parse-slice-b1-closure.json
parse-slice-b2-closure.json
parse-slice-b3-closure.json
parse-slice-b4-closure.json
parse-slice-b5-closure.json

The complete final regression contains 75 tests covering:

ingestion compatibility;
routing;
text and Markdown;
XML;
hardened HTML;
embedded PDF extraction;
OCR execution and provenance;
DOCX;
CSV;
TSV;
XLSX;
parse-attempt persistence and retry lineage;
cross-format canonical invariants.
Parent acceptance criteria

WP-PARSE-01 is closed only when:

capabilities CAP-PARSE-001 through CAP-PARSE-012 are each mapped to at least one closed slice;
no capability number in the range 001–012 is absent;
all six slice closure reports have status == PASS;
all canonical and parse-attempt schemas are present;
all nine parser routes are registered;
the full 75-test regression passes;
local and remote Git heads are synchronized;
the worktree is clean after the parent closure commit.
Explicitly separate work

The following remain outside WP-PARSE-01 unless introduced through a separately defined work package:

spelling correction;
language-model repair;
OCR ensemble voting;
handwriting recognition;
automatic multilingual OCR selection;
semantic adjudication;
fuzzy equivalence;
embedding similarity;
semantic deduplication;
automatic retry scheduling;
backoff and queue orchestration;
distributed leases or locks;
telemetry export;
cross-document identity resolution.

These exclusions do not constitute open WP-PARSE-01 capabilities.

Closure conclusion

All capabilities CAP-PARSE-001 through CAP-PARSE-012 are implemented, tested, evidenced, and assigned to closed slices.

WP-PARSE-01 is complete.
