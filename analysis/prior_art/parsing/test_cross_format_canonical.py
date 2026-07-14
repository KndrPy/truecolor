from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile

from pathlib import Path
from unittest.mock import patch

from jsonschema import (
    Draft202012Validator,
)

from analysis.prior_art.ingestion.artifact_intake import (
    ingest_file,
)

from .canonical_validator import (
    CanonicalInvariantError,
    canonical_bytes,
    prose_projection,
    recompute_document_id,
    validate_canonical_document,
)

from .parse_document import (
    SCHEMA_PATH,
    parse_intake_manifest,
)


SHARED_TEXT = (
    "Heading\n\n"
    "First paragraph.\n\n"
    "Second paragraph."
)


class CrossFormatCanonicalTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.temporary = (
            tempfile.TemporaryDirectory()
        )

        self.root = Path(
            self.temporary.name
        )

        self.sources = (
            self.root / "sources"
        )

        self.store = (
            self.root / "store"
        )

        self.manifests = (
            self.root / "manifests"
        )

        self.parsed = (
            self.root / "parsed"
        )

        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ingest_parse(
        self,
        source: Path,
        *,
        declared_media_type: (
            str | None
        ) = None,
    ) -> tuple[
        dict[str, object],
        Path,
    ]:
        intake = ingest_file(
            source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
            declared_media_type=(
                declared_media_type
            ),
        )

        return parse_intake_manifest(
            intake.manifest_path,
            output_root=self.parsed,
        )

    def assert_valid(
        self,
        document: dict[str, object],
    ) -> None:
        validate_canonical_document(
            document
        )

        self.assertEqual(
            document["document_id"],
            recompute_document_id(
                document
            ),
        )

    def assert_stable(
        self,
        source: Path,
        *,
        declared_media_type: (
            str | None
        ) = None,
    ) -> dict[str, object]:
        first, first_path = (
            self.ingest_parse(
                source,
                declared_media_type=(
                    declared_media_type
                ),
            )
        )

        second, second_path = (
            self.ingest_parse(
                source,
                declared_media_type=(
                    declared_media_type
                ),
            )
        )

        self.assertEqual(
            first,
            second,
        )

        self.assertEqual(
            first_path,
            second_path,
        )

        self.assertEqual(
            first_path.read_bytes(),
            second_path.read_bytes(),
        )

        self.assertEqual(
            canonical_bytes(first),
            canonical_bytes(second),
        )

        self.assert_valid(
            first
        )

        return first

    def write_docx(
        self,
        path: Path,
    ) -> None:
        with zipfile.ZipFile(
            path,
            "w",
            compression=(
                zipfile.ZIP_DEFLATED
            ),
        ) as archive:
            archive.writestr(
                "[Content_Types].xml",
                (
                    '<?xml version="1.0"?>'
                    '<Types xmlns="http://schemas.'
                    'openxmlformats.org/package/'
                    '2006/content-types">'
                    '<Override '
                    'PartName="/word/document.xml" '
                    'ContentType="application/vnd.'
                    'openxmlformats-officedocument.'
                    'wordprocessingml.document.'
                    'main+xml"/>'
                    "</Types>"
                ),
            )

            archive.writestr(
                "word/document.xml",
                (
                    '<?xml version="1.0"?>'
                    '<w:document '
                    'xmlns:w="http://schemas.'
                    'openxmlformats.org/'
                    'wordprocessingml/2006/main">'
                    "<w:body>"
                    "<w:p><w:r><w:t>"
                    "Evidence paragraph"
                    "</w:t></w:r></w:p>"
                    "<w:tbl>"
                    "<w:tr>"
                    "<w:tc><w:p><w:r><w:t>"
                    "Metric"
                    "</w:t></w:r></w:p></w:tc>"
                    "<w:tc><w:p><w:r><w:t>"
                    "Value"
                    "</w:t></w:r></w:p></w:tc>"
                    "</w:tr>"
                    "<w:tr>"
                    "<w:tc><w:p><w:r><w:t>"
                    "Error"
                    "</w:t></w:r></w:p></w:tc>"
                    "<w:tc><w:p><w:r><w:t>"
                    "0.041"
                    "</w:t></w:r></w:p></w:tc>"
                    "</w:tr>"
                    "</w:tbl>"
                    "</w:body>"
                    "</w:document>"
                ),
            )

    def write_pdf(
        self,
        path: Path,
    ) -> None:
        path.write_bytes(
            b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 53 >>stream
BT /F1 18 Tf 72 720 Td (TrueColor PDF text) Tj ET
endstream endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000343 00000 n 
trailer<< /Size 6 /Root 1 0 R >>
startxref
413
%%EOF
"""
        )

    def table_matrix(
        self,
        document: dict[str, object],
    ) -> list[list[object]]:
        table = document[
            "tables"
        ][0]

        return [
            [
                cell["value"]
                for cell in row[
                    "cells"
                ]
            ]
            for row in table[
                "rows"
            ]
        ]

    def test_text_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "shared.txt"
        )

        path.write_text(
            SHARED_TEXT + "\n",
            encoding="utf-8",
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "TEXT",
        )

    def test_markdown_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "shared.md"
        )

        path.write_text(
            (
                "# Heading\n\n"
                "First paragraph.\n\n"
                "Second paragraph.\n"
            ),
            encoding="utf-8",
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "MARKDOWN",
        )

    def test_html_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "shared.html"
        )

        path.write_text(
            (
                "<html><body>"
                "<h1>Heading</h1>"
                "<p>First paragraph.</p>"
                "<p>Second paragraph.</p>"
                "</body></html>"
            ),
            encoding="utf-8",
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "HTML",
        )

    def test_xml_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "shared.xml"
        )

        path.write_text(
            (
                "<article>"
                "<article-title>"
                "Heading"
                "</article-title>"
                "<p>First paragraph.</p>"
                "<p>Second paragraph.</p>"
                "</article>"
            ),
            encoding="utf-8",
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "XML",
        )

    def test_csv_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "matrix.csv"
        )

        path.write_text(
            (
                "name,value\n"
                "alpha,1\n"
                "beta,2\n"
            ),
            encoding="utf-8",
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "CSV",
        )

    def test_tsv_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "matrix.tsv"
        )

        path.write_text(
            (
                "name\tvalue\n"
                "alpha\t1\n"
                "beta\t2\n"
            ),
            encoding="utf-8",
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "TSV",
        )

    def test_docx_route_contract(
        self,
    ) -> None:
        path = (
            self.sources / "evidence.docx"
        )

        self.write_docx(
            path
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "DOCX",
        )

    def test_xlsx_route_contract(
        self,
    ) -> None:
        from openpyxl import Workbook

        path = (
            self.sources / "matrix.xlsx"
        )

        workbook = Workbook()

        sheet = workbook.active
        sheet.title = "Evidence"
        sheet.append(
            ["name", "value"]
        )
        sheet.append(
            ["alpha", 1]
        )
        sheet.append(
            ["beta", 2]
        )

        workbook.save(
            path
        )

        workbook.close()

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "XLSX",
        )

    @unittest.skipUnless(
        shutil.which("pdftotext")
        and shutil.which("pdfinfo"),
        "Poppler tools unavailable",
    )
    def test_embedded_pdf_contract(
        self,
    ) -> None:
        path = (
            self.sources / "embedded.pdf"
        )

        self.write_pdf(
            path
        )

        document = self.assert_stable(
            path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "PDF",
        )

        self.assertEqual(
            document["pages"][0][
                "text_source"
            ],
            "EMBEDDED",
        )

    def test_ocr_pdf_contract(
        self,
    ) -> None:
        path = (
            self.sources / "ocr.pdf"
        )

        path.write_bytes(
            b"%PDF-1.4\n%%EOF\n"
        )

        intake = ingest_file(
            path,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

        artifact_id = intake.manifest[
            "artifact_id"
        ]

        mocked = (
            "OCR text",
            [
                {
                    "segment_id": (
                        "segment:"
                        + "1" * 64
                    ),
                    "kind": "PAGE",
                    "text": "OCR",
                    "canonical_start": 0,
                    "canonical_end": 3,
                    "source": {
                        "page_number": 1,
                        "source_start": None,
                        "source_end": None,
                        "bbox": {
                            "x0": 10.0,
                            "y0": 10.0,
                            "x1": 40.0,
                            "y1": 25.0
                        },
                        "extraction_method": "OCR",
                        "ocr_confidence": 95.0,
                        "ocr_engine": "tesseract",
                        "ocr_language": "eng",
                        "render_dpi": 300
                    }
                },
                {
                    "segment_id": (
                        "segment:"
                        + "2" * 64
                    ),
                    "kind": "PAGE",
                    "text": "text",
                    "canonical_start": 4,
                    "canonical_end": 8,
                    "source": {
                        "page_number": 1,
                        "source_start": None,
                        "source_end": None,
                        "bbox": {
                            "x0": 45.0,
                            "y0": 10.0,
                            "x1": 85.0,
                            "y1": 25.0
                        },
                        "extraction_method": "OCR",
                        "ocr_confidence": 94.0,
                        "ocr_engine": "tesseract",
                        "ocr_language": "eng",
                        "render_dpi": 300
                    }
                }
            ],
            [
                {
                    "page_number": 1,
                    "width": 612.0,
                    "height": 792.0,
                    "text": "OCR text",
                    "word_count": 2,
                    "character_count": 8,
                    "text_source": "OCR",
                    "ocr_mean_confidence": 94.5
                }
            ],
            [
                {
                    "page_number": 1,
                    "classification": "OCR_REQUIRED",
                    "reason_codes": [
                        "NO_EMBEDDED_TEXT"
                    ],
                    "character_count": 0,
                    "word_count": 0,
                    "execution_status": "SUCCEEDED",
                    "engine": "tesseract",
                    "engine_version": "5.3.4",
                    "render_engine": "pdftoppm",
                    "render_engine_version": "24.02.0",
                    "language": "eng",
                    "dpi": 300,
                    "render_width_px": 2550,
                    "render_height_px": 3300,
                    "recognized_word_count": 2,
                    "recognized_character_count": 7,
                    "mean_confidence": 94.5
                }
            ],
        )

        with patch(
            (
                "analysis.prior_art.parsing."
                "parse_document.parse_pdf"
            ),
            return_value=mocked,
        ):
            document, _ = (
                parse_intake_manifest(
                    intake.manifest_path,
                    output_root=(
                        self.parsed
                    ),
                )
            )

        self.assertEqual(
            document["artifact_id"],
            artifact_id,
        )

        self.assert_valid(
            document
        )

        self.assertEqual(
            document["pages"][0][
                "text_source"
            ],
            "OCR",
        )

    def test_prose_formats_share_text(
        self,
    ) -> None:
        text_path = (
            self.sources / "equivalent.txt"
        )

        markdown_path = (
            self.sources / "equivalent.md"
        )

        html_path = (
            self.sources / "equivalent.html"
        )

        xml_path = (
            self.sources / "equivalent.xml"
        )

        text_path.write_text(
            SHARED_TEXT + "\n",
            encoding="utf-8",
        )

        markdown_path.write_text(
            (
                "# Heading\n\n"
                "First paragraph.\n\n"
                "Second paragraph.\n"
            ),
            encoding="utf-8",
        )

        html_path.write_text(
            (
                "<html><body>"
                "<h1>Heading</h1>"
                "<p>First paragraph.</p>"
                "<p>Second paragraph.</p>"
                "</body></html>"
            ),
            encoding="utf-8",
        )

        xml_path.write_text(
            (
                "<article>"
                "<article-title>"
                "Heading"
                "</article-title>"
                "<p>First paragraph.</p>"
                "<p>Second paragraph.</p>"
                "</article>"
            ),
            encoding="utf-8",
        )

        documents = [
            self.ingest_parse(
                path
            )[0]
            for path in [
                text_path,
                markdown_path,
                html_path,
                xml_path,
            ]
        ]

        expected_projection = (
            "Heading",
            "First paragraph.",
            "Second paragraph.",
        )

        self.assertEqual(
            {
                prose_projection(
                    document
                )
                for document
                in documents
            },
            {
                expected_projection
            },
        )

        for document in documents:
            self.assert_valid(
                document
            )

    def test_prose_projection_preserves_semantics(
        self,
    ) -> None:
        expected = (
            "Heading",
            "First paragraph.",
            "Second paragraph.",
        )

        text_document = {
            "parser": {
                "route": "TEXT"
            },
            "text": (
                "Heading\n\n"
                "First paragraph.\n\n"
                "Second paragraph.\n"
            ),
            "segments": [],
        }

        markdown_document = {
            "parser": {
                "route": "MARKDOWN"
            },
            "text": (
                "# Heading\n\n"
                "First paragraph.\n\n"
                "Second paragraph.\n"
            ),
            "segments": [
                {
                    "text": "# Heading"
                },
                {
                    "text": "First paragraph."
                },
                {
                    "text": "Second paragraph."
                },
            ],
        }

        structured_document = {
            "parser": {
                "route": "HTML"
            },
            "text": (
                "Heading\n\n"
                "First paragraph.\n\n"
                "Second paragraph."
            ),
            "segments": [
                {
                    "text": "Heading"
                },
                {
                    "text": "First paragraph."
                },
                {
                    "text": "Second paragraph."
                },
            ],
        }

        self.assertEqual(
            prose_projection(
                text_document
            ),
            expected,
        )

        self.assertEqual(
            prose_projection(
                markdown_document
            ),
            expected,
        )

        self.assertEqual(
            prose_projection(
                structured_document
            ),
            expected,
        )

    def test_tabular_formats_share_matrix(
        self,
    ) -> None:
        from openpyxl import Workbook

        csv_path = (
            self.sources / "equivalent.csv"
        )

        tsv_path = (
            self.sources / "equivalent.tsv"
        )

        xlsx_path = (
            self.sources / "equivalent.xlsx"
        )

        csv_path.write_text(
            (
                "name,value\n"
                "alpha,1\n"
                "beta,2\n"
            ),
            encoding="utf-8",
        )

        tsv_path.write_text(
            (
                "name\tvalue\n"
                "alpha\t1\n"
                "beta\t2\n"
            ),
            encoding="utf-8",
        )

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Evidence"
        sheet.append(
            ["name", "value"]
        )
        sheet.append(
            ["alpha", 1]
        )
        sheet.append(
            ["beta", 2]
        )
        workbook.save(
            xlsx_path
        )
        workbook.close()

        csv_document = (
            self.ingest_parse(
                csv_path
            )[0]
        )

        tsv_document = (
            self.ingest_parse(
                tsv_path
            )[0]
        )

        xlsx_document = (
            self.ingest_parse(
                xlsx_path
            )[0]
        )

        self.assertEqual(
            self.table_matrix(
                csv_document
            ),
            self.table_matrix(
                tsv_document
            ),
        )

        self.assertEqual(
            [
                [
                    str(value)
                    for value in row
                ]
                for row in self.table_matrix(
                    xlsx_document
                )
            ],
            self.table_matrix(
                csv_document
            ),
        )

    def test_validator_rejects_tampered_document_id(
        self,
    ) -> None:
        path = (
            self.sources / "tamper.txt"
        )

        path.write_text(
            "Stable content.\n",
            encoding="utf-8",
        )

        document, _ = (
            self.ingest_parse(
                path
            )
        )

        document["document_id"] = (
            "document:sha256:"
            + "0" * 64
        )

        with self.assertRaises(
            CanonicalInvariantError
        ) as caught:
            validate_canonical_document(
                document
            )

        self.assertIn(
            "DOCUMENT_ID_MISMATCH",
            caught.exception.errors,
        )

    def test_schema_covers_all_registered_routes(
        self,
    ) -> None:
        schema = json.loads(
            SCHEMA_PATH.read_text(
                encoding="utf-8"
            )
        )

        validator = (
            Draft202012Validator(
                schema
            )
        )

        self.assertIsNotNone(
            validator
        )

        routes = set(
            schema[
                "properties"
            ][
                "parser"
            ][
                "properties"
            ][
                "route"
            ][
                "enum"
            ]
        )

        self.assertEqual(
            routes,
            {
                "PDF",
                "XML",
                "HTML",
                "TEXT",
                "MARKDOWN",
                "DOCX",
                "CSV",
                "TSV",
                "XLSX",
            },
        )


if __name__ == "__main__":
    unittest.main()
