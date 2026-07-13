# WP-PARSE-01 Slice B3

## Closed capability

### CAP-PARSE-006 — Deterministic HTML structure hardening

HTML is reduced through a deterministic event-driven parser that preserves semantic document order, recovers from malformed closing tags, excludes non-content elements, generates stable indexed source paths, and prevents nested structural text duplication.

## Execution contract

- HTML decoding uses UTF-8 with optional BOM handling.
- HTML entity references are normalized through the standard-library parser.
- Tag names are normalized to lowercase.
- Every non-void element receives a deterministic sibling-indexed path.
- Unmatched closing tags do not mutate parser ancestry.
- Mismatched closing tags close only through the matching open ancestor.
- Implicitly open paragraphs, list items, and headings are closed at deterministic structural boundaries.
- Void elements never remain on the element stack.
- `br` and `wbr` preserve a canonical word boundary.
- `head`, `script`, `style`, `noscript`, and `template` content is excluded.
- Nested semantic elements emit through the nearest active semantic segment and do not duplicate text.
- Non-semantic visible text is emitted through a deterministic fallback container segment.

## Semantic segment mapping

- `h1` through `h6` → `HEADING`
- `p`, `blockquote`, `caption`, `figcaption`, `pre` → `PARAGRAPH`
- `li` → `LIST_ITEM`
- `td`, `th` → `TABLE_CELL`
- visible fallback container text → `XML_ELEMENT`

## Provenance contract

Each emitted segment records:

- deterministic indexed HTML path;
- semantic segment kind;
- exact canonical text;
- exact canonical start and end offsets;
- stable content-derived segment identifier.

Example path:

```text
/html[1]/body[1]/div[2]/p[3]
Failure contract

The parser fails explicitly with:

SOURCE_NOT_UTF8 when the source cannot be decoded as UTF-8;
HTML_PARSE_FAILED when the HTML event reducer raises an unexpected parsing failure.

Recoverable malformed HTML does not fail parsing.

Acceptance criteria
Semantic blocks remain in source document order.
Indexed sibling paths are unique within their parent.
Excluded elements contribute no canonical text.
Unmatched closing tags do not pop unrelated elements.
Mismatched closing tags recover deterministically.
Void tags do not corrupt ancestry.
Nested semantic elements do not duplicate canonical text.
Entity and whitespace normalization is deterministic.
Every segment range resolves exactly to its segment text.
Repeated parsing produces identical text, segments, paths, ranges, and identifiers.
Existing ingestion, parsing, tabular, DOCX, XML, PDF, and OCR regressions remain green.
Validation evidence
Focused HTML tests: 10.
Prior ingestion, parsing, and OCR regression tests: 41.
Final combined expected test count: 51.
Explicit exclusions

This slice does not add:

canonical HTML table objects;
row-span or column-span normalization;
browser-equivalent HTML5 tree construction;
CSS visibility evaluation;
JavaScript execution;
encoding detection beyond UTF-8;
parser retry or failure ledgers;
cross-format semantic equivalence validation.
