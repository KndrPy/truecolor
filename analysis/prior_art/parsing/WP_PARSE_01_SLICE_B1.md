# WP-PARSE-01 Slice B1

## Closed capabilities

### CAP-PARSE-008 — DOCX canonicalization

DOCX Open Packaging Convention containers are detected by archive structure and parsed from `word/document.xml` without relying on filename extensions. Paragraphs and table cells are emitted as canonical segments with document-part, paragraph, table, row, column, and cell-reference provenance.

Acceptance criteria:

- DOCX containers route deterministically to `DOCX`.
- Paragraph text is emitted in source document order.
- Table rows and cells are normalized into the canonical table model.
- Every emitted DOCX segment maps to `word/document.xml`.
- Table-cell segments include table, row, column, and cell-reference coordinates.
- Malformed or incomplete DOCX containers fail explicitly.

### CAP-PARSE-009 — Tabular artifact normalization

CSV, TSV, and XLSX artifacts are normalized into a common canonical table representation. CSV and TSV retain source byte offsets where recoverable. XLSX retains workbook sheet names, row numbers, column numbers, cell references, typed values, and formulas.

Acceptance criteria:

- CSV and TSV are distinguished by detected delimiter.
- XLSX containers are identified through workbook archive structure.
- CSV, TSV, and XLSX use distinct deterministic parser routes.
- Each logical table declares row and column counts.
- Each cell includes row, column, reference, value, and value type.
- XLSX formulas remain formulas rather than cached values.
- Immutable object-store filenames do not affect XLSX parsing.
- Repeated parsing of identical artifacts produces identical canonical documents.

## Explicit exclusions

This slice does not execute OCR, render PDF pages, reconcile OCR coordinates, harden malformed HTML parsing, or implement parser retry ledgers. Those remain separate bounded slices.

## Validation

- Intake media-detection regression: 14 tests.
- Parser regression: 19 tests.
- Combined regression: 33 tests.
- Focused DOCX, CSV, TSV, and XLSX validation: 4 tests.
