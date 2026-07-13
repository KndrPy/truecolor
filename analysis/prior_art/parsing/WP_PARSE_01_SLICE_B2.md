# WP-PARSE-01 Slice B2

## Closed capability

### CAP-PARSE-004 — OCR execution with page-level provenance

PDF pages without embedded text are rendered deterministically through Poppler and recognized through Tesseract TSV output. OCR words are incorporated into the canonical document with page coordinates, word confidence, engine identity, language, and render resolution.

## Execution contract

- PDF pages are assessed before OCR execution.
- `OCR_REQUIRED` pages execute OCR.
- `OCR_RECOMMENDED` pages retain embedded text and do not execute OCR automatically.
- `OCR_NOT_REQUIRED` pages retain embedded text and do not execute OCR.
- Page rendering uses `pdftoppm`.
- Rendering uses PNG at 300 DPI.
- Recognition uses Tesseract TSV output.
- The configured OCR language is `eng`.
- Temporary rendered images are deleted after each page execution.
- Immutable object-store filenames do not affect OCR execution.

## Canonical provenance

Each OCR-derived segment records:

- PDF page number.
- Bounding box reconciled into PDF page coordinates.
- Extraction method `OCR`.
- Tesseract word confidence.
- OCR engine identity.
- OCR language.
- Render DPI.
- Exact canonical-text character range.

Each OCR assessment records:

- Original OCR classification.
- Execution status.
- OCR and rendering engine versions.
- Language and DPI.
- Render dimensions.
- Recognized word and character counts.
- Mean word confidence.

## Failure contract

The parser fails explicitly when:

- A required binary is unavailable.
- Page rendering fails.
- Tesseract execution fails.
- Rendered PNG output is missing or invalid.
- Tesseract TSV fields or rows are malformed.
- Page or image coordinate scaling is invalid.
- A required OCR page lacks valid PDF dimensions.

## Acceptance criteria

- OCR executes only for pages classified `OCR_REQUIRED`.
- Embedded-text pages do not invoke OCR.
- OCR-derived canonical ranges resolve exactly to segment text.
- OCR bounding boxes remain inside their PDF page dimensions.
- Word confidence remains within 0 through 100.
- OCR execution metadata is present on every OCR-derived segment.
- A real image-only PDF completes intake, parsing, OCR, schema validation, and provenance validation.
- Existing ingestion and parsing regressions remain green.

## Validation evidence

- OCR engine unit and integration tests: 8.
- Existing ingestion and parsing regression tests: 33.
- Real image-only PDF:
  - Embedded text characters: 0.
  - OCR classification: `OCR_REQUIRED`.
  - OCR execution: `SUCCEEDED`.
  - OCR engine: Tesseract.
  - Render engine: Poppler `pdftoppm`.
  - Render resolution: 300 DPI.
  - Recognized words: 17.
  - Mean confidence: approximately 87.80.
  - Coordinate errors: 0.
  - Provenance errors: 0.

## Explicit exclusions

This slice does not implement spelling correction, language-model repair, OCR ensemble voting, handwriting recognition, automatic multilingual selection, confidence-based semantic adjudication, malformed HTML hardening, or parser retry ledgers.
