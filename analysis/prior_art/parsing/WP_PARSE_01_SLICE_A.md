# WP-PARSE-01 Slice A Closure Contract

## Implemented capabilities

- CAP-PARSE-001 — deterministic parser routing
- CAP-PARSE-002 — embedded PDF text and word geometry extraction
- CAP-PARSE-003 — page-level OCR requirement classification
- CAP-PARSE-005 — XML, JATS, and TEI canonicalization
- CAP-PARSE-007 — text and Markdown canonicalization
- CAP-PARSE-011 — canonical-to-source coordinate mapping

## Supported routes

| Detected media type | Route |
|---|---|
| `application/pdf` | PDF |
| `application/xml` | XML |
| `text/xml` | XML |
| `application/jats+xml` | XML |
| `application/tei+xml` | XML |
| `text/html` | HTML |
| `application/xhtml+xml` | HTML |
| `text/plain` | TEXT |
| `text/markdown` | MARKDOWN |

All other media types fail with `UNSUPPORTED_MEDIA_TYPE`.

## Determinism invariant

For identical immutable source bytes and parser version:

- parser route is identical;
- canonical text is identical;
- segment order is identical;
- segment IDs are identical;
- coordinate mappings are identical;
- canonical document ID is identical;
- serialized canonical document content is identical.

## Source-coordinate invariant

For every segment:

```text
0 <= canonical_start <= canonical_end <= len(document.text)
document.text[canonical_start:canonical_end] == segment.text

Text and Markdown also preserve exact source character offsets.

PDF words preserve:

page number;
word-level bounding box;
canonical character offsets.

XML, JATS, TEI, and HTML preserve a structural element path.

OCR classification

Each PDF page receives exactly one classification:

OCR_NOT_REQUIRED
OCR_RECOMMENDED
OCR_REQUIRED
UNDETERMINED

Current deterministic rules:

zero embedded characters: OCR_REQUIRED;
fewer than 40 characters or 8 words: OCR_RECOMMENDED;
otherwise: OCR_NOT_REQUIRED.

This slice classifies OCR need. It does not execute OCR.

Explicit exclusions
OCR execution;
image extraction;
table reconstruction;
mathematical-expression reconstruction;
DOCX parsing;
spreadsheet parsing;
citation extraction;
semantic section classification;
language detection.
Closure gates
All modules compile.
Parser routing is deterministic.
Unsupported media fails explicitly.
Text and Markdown offsets are exact.
XML/JATS/TEI paths are present.
HTML route produces canonical text.
PDF text and word geometry are extracted.
Blank PDF pages are classified as requiring OCR.
Malformed XML fails explicitly.
Canonical document output is deterministic.
CLI execution emits no runtime warning.
Canonical document schema validation passes.
