# WP-PARSE-01 Slice B5

## Closed capability

### CAP-PARSE-012 — Cross-format canonical validation

This slice adds deterministic validation of the canonical-document contract across every registered parser route:

- PDF with embedded text;
- PDF with OCR-derived text;
- XML;
- HTML;
- plain text;
- Markdown;
- DOCX;
- CSV;
- TSV;
- XLSX.

The validator operates on completed canonical documents. It does not alter parser execution or canonicalization behavior.

## Universal canonical invariants

Every canonical document must satisfy:

- JSON Schema validation;
- recomputable deterministic `document_id`;
- `artifact_id` consistency with `content_sha256`;
- unique segment identifiers;
- ordered, non-overlapping segment ranges;
- exact canonical-text resolution for every segment;
- unique table identifiers;
- route-appropriate empty collections;
- stable document and serialized output across repeated parsing.

## Document identity

The validator recomputes the document identifier from the same canonical basis used by `parse_document.py`:

- artifact identity;
- content SHA-256;
- source media type;
- parser route;
- canonical text;
- segments;
- pages;
- tables;
- OCR assessment.

Any difference between the persisted and recomputed identifier is reported as:

```text
DOCUMENT_ID_MISMATCH
Segment invariants

For every segment:

canonical_start <= canonical_end;
the range remains inside the canonical text;
the canonical slice equals segment.text;
segment order is monotonic;
segments do not overlap;
segment identifiers are unique.
Route collection invariants

For non-PDF routes:

pages == []
ocr_assessment == []

For routes other than DOCX, CSV, TSV, and XLSX:

tables == []
PDF invariants

For PDF documents:

page numbers are contiguous from one;
page count equals OCR-assessment count;
every segment references an existing page;
every segment has a bounding box;
embedded-text pages have no OCR confidence;
embedded-text pages have NOT_RUN OCR execution status;
OCR pages have numeric OCR confidence;
OCR pages have SUCCEEDED OCR execution status.
Table invariants

For DOCX, CSV, TSV, and XLSX:

table indexes are contiguous from zero;
table identifiers are unique;
source_kind agrees with parser route;
declared row count equals the number of rows;
declared column count equals the maximum cells in any row;
row indexes are contiguous from one;
cell column indexes are contiguous from one;
cell references are unique within each table;
every TABLE_CELL segment resolves to an existing table, row, column, and cell reference.
Cross-format prose equivalence

Plain text, Markdown, HTML, and XML retain route-native canonical representations.

Exact raw document.text equality is not required because:

plain text preserves source terminal newlines;
Markdown preserves source markup;
structured formats emit normalized visible text.

A deterministic prose projection reduces each format to ordered semantic blocks.

For the shared fixture, every route must project to:

Heading
First paragraph.
Second paragraph.

The projection does not modify persisted canonical documents.

Cross-format tabular equivalence

CSV, TSV, and XLSX fixtures must produce equivalent ordered cell-value matrices.

CSV and TSV retain string-oriented values.

XLSX retains native value types.

The following are not required to match across formats:

document identifier;
canonical text;
table identifier;
source media type;
cell-reference implementation;
native value type where the source format cannot preserve it.
Determinism

Each route fixture is ingested and parsed twice.

The following must remain stable:

canonical document object;
canonical output path;
canonical output bytes;
canonical JSON byte representation;
document identifier.
Falsification coverage

The validator is explicitly tested to reject a canonical document whose persisted document_id is replaced with a different schema-valid identifier.

Acceptance criteria
All nine parser routes are represented by focused validation.
Embedded-text PDF invariants pass.
OCR-derived PDF invariants pass.
Universal segment invariants pass.
Route-specific collection invariants pass.
DOCX table and provenance invariants pass.
CSV, TSV, and XLSX table invariants pass.
Equivalent prose formats produce one semantic projection.
Equivalent tabular formats produce one ordered value matrix.
Schema route enumeration covers every registered route.
Repeated parsing is byte-stable.
Tampered document identity is rejected.
Existing 60 ingestion and parsing tests remain green.
Validation evidence
Focused cross-format tests: 15.
Existing regression tests: 60.
Final combined expected test count: 75.
Explicit exclusions

This slice does not add:

parser repair;
semantic deduplication;
fuzzy text comparison;
embedding similarity;
lossy equivalence scoring;
OCR ensemble adjudication;
alternate parser routing;
source-content mutation;
cross-document identity merging;
persistent validation ledgers.
