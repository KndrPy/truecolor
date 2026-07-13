from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

from analysis.prior_art.ingestion.artifact_intake import (
    ingest_file,
)

from .parse_document import (
    parse_intake_manifest,
)

from .parser_router import (
    ParserRoutingError,
    route_parser,
)


class ParsingTests(
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

    def ingest(
        self,
        path: Path,
        *,
        declared_media_type: str | None = None,
    ):
        return ingest_file(
            path,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
            declared_media_type=(
                declared_media_type
            ),
        )

    def parse(
        self,
        manifest_path: Path,
    ):
        return parse_intake_manifest(
            manifest_path,
            output_root=self.parsed,
        )

    def test_router_is_deterministic(
        self,
    ) -> None:
        first = route_parser(
            "application/pdf"
        )

        second = route_parser(
            "application/pdf"
        )

        self.assertEqual(
            first,
            second,
        )

        self.assertEqual(
            first.route,
            "PDF",
        )

    def test_router_rejects_unknown(
        self,
    ) -> None:
        with self.assertRaises(
            ParserRoutingError
        ):
            route_parser(
                "application/octet-stream"
            )

    def test_text_offsets_are_exact(
        self,
    ) -> None:
        source = (
            self.sources
            / "document.txt"
        )

        source.write_text(
            "First paragraph.\n\n"
            "Second paragraph.\n",
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        document, _ = self.parse(
            result.manifest_path
        )

        for segment in document[
            "segments"
        ]:
            start = segment[
                "canonical_start"
            ]

            end = segment[
                "canonical_end"
            ]

            self.assertEqual(
                document["text"][
                    start:end
                ],
                segment["text"],
            )

            self.assertEqual(
                start,
                segment["source"][
                    "source_start"
                ],
            )

            self.assertEqual(
                end,
                segment["source"][
                    "source_end"
                ],
            )

    def test_markdown_heading_and_list(
        self,
    ) -> None:
        source = (
            self.sources
            / "document.md"
        )

        source.write_text(
            "# Heading\n\n"
            "- First\n"
            "- Second\n",
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        document, _ = self.parse(
            result.manifest_path
        )

        kinds = {
            segment["kind"]
            for segment in document[
                "segments"
            ]
        }

        self.assertIn(
            "HEADING",
            kinds,
        )

        self.assertIn(
            "LIST_ITEM",
            kinds,
        )

    def test_xml_paths_are_present(
        self,
    ) -> None:
        source = (
            self.sources
            / "article.xml"
        )

        source.write_text(
            (
                "<article>"
                "<front>"
                "<article-title>Title</article-title>"
                "</front>"
                "<body><sec><p>Body text</p></sec></body>"
                "</article>"
            ),
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        document, _ = self.parse(
            result.manifest_path
        )

        self.assertTrue(
            document["segments"]
        )

        self.assertTrue(
            all(
                segment["source"][
                    "xml_path"
                ]
                for segment in document[
                    "segments"
                ]
            )
        )

    def test_document_is_deterministic(
        self,
    ) -> None:
        source = (
            self.sources
            / "stable.txt"
        )

        source.write_text(
            "Stable content.\n",
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        first, _ = self.parse(
            result.manifest_path
        )

        second, _ = self.parse(
            result.manifest_path
        )

        self.assertEqual(
            first,
            second,
        )

    @unittest.skipUnless(
        shutil.which("pdftotext")
        and shutil.which("pdfinfo"),
        "Poppler tools unavailable",
    )
    def test_pdf_geometry_and_ocr_assessment(
        self,
    ) -> None:
        if shutil.which("python") is None:
            self.skipTest(
                "Python unavailable"
            )

        generator = (
            self.sources
            / "make_pdf.py"
        )

        pdf_path = (
            self.sources
            / "sample.pdf"
        )

        generator.write_text(
            (
                "from pathlib import Path\n"
                "content = b'''%PDF-1.4\\n"
                "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\\n"
                "2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\\n"
                "3 0 obj<< /Type /Page /Parent 2 0 R "
                "/MediaBox [0 0 612 792] /Contents 4 0 R "
                "/Resources << /Font << /F1 5 0 R >> >> >>endobj\\n"
                "4 0 obj<< /Length 53 >>stream\\n"
                "BT /F1 18 Tf 72 720 Td (TrueColor PDF text) Tj ET\\n"
                "endstream endobj\\n"
                "5 0 obj<< /Type /Font /Subtype /Type1 "
                "/BaseFont /Helvetica >>endobj\\n"
                "xref\\n0 6\\n"
                "0000000000 65535 f \\n"
                "0000000009 00000 n \\n"
                "0000000058 00000 n \\n"
                "0000000115 00000 n \\n"
                "0000000241 00000 n \\n"
                "0000000343 00000 n \\n"
                "trailer<< /Size 6 /Root 1 0 R >>\\n"
                "startxref\\n413\\n%%EOF\\n'''\n"
                f"Path({str(pdf_path)!r}).write_bytes(content)\n"
            ),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "python",
                str(generator),
            ],
            check=True,
        )

        result = self.ingest(
            pdf_path
        )

        document, _ = self.parse(
            result.manifest_path
        )

        self.assertEqual(
            document["parser"][
                "route"
            ],
            "PDF",
        )

        self.assertEqual(
            len(document["pages"]),
            1,
        )

        self.assertEqual(
            len(
                document[
                    "ocr_assessment"
                ]
            ),
            1,
        )

        for segment in document[
            "segments"
        ]:
            self.assertIsNotNone(
                segment["source"][
                    "bbox"
                ]
            )


    def test_html_route_and_canonical_text(
        self,
    ) -> None:
        source = (
            self.sources
            / "article.html"
        )

        source.write_text(
            (
                "<html><body>"
                "<h1>Heading</h1>"
                "<p>First paragraph.</p>"
                "<p>Second paragraph.</p>"
                "</body></html>"
            ),
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        document, _ = self.parse(
            result.manifest_path
        )

        self.assertEqual(
            document["parser"]["route"],
            "HTML",
        )

        self.assertIn(
            "Heading",
            document["text"],
        )

        self.assertIn(
            "First paragraph.",
            document["text"],
        )

        self.assertIn(
            "Second paragraph.",
            document["text"],
        )

        for segment in document[
            "segments"
        ]:
            start = segment[
                "canonical_start"
            ]

            end = segment[
                "canonical_end"
            ]

            self.assertEqual(
                document["text"][
                    start:end
                ],
                segment["text"],
            )

    def test_malformed_xml_fails_explicitly(
        self,
    ) -> None:
        source = (
            self.sources
            / "malformed.xml"
        )

        source.write_text(
            "<article><p>broken</article>",
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        self.assertEqual(
            result.manifest[
                "detected_media_type"
            ],
            "application/xml",
        )

        self.assertEqual(
            result.manifest[
                "media_detection"
            ][
                "method"
            ],
            "STRUCTURAL_TEXT_PROBE",
        )

        with self.assertRaisesRegex(
            ValueError,
            "XML_PARSE_FAILED",
        ):
            self.parse(
                result.manifest_path
            )


    def test_unsupported_media_type_fails_explicitly(
        self,
    ) -> None:
        source = (
            self.sources
            / "binary.bin"
        )

        source.write_bytes(
            b"\x00\x01\x02\x03\x04"
        )

        result = self.ingest(
            source
        )

        with self.assertRaises(
            ParserRoutingError
        ) as raised:
            self.parse(
                result.manifest_path
            )

        self.assertEqual(
            raised.exception.code,
            "UNSUPPORTED_MEDIA_TYPE",
        )

    def test_all_segment_ranges_are_valid(
        self,
    ) -> None:
        source = (
            self.sources
            / "ranges.md"
        )

        source.write_text(
            (
                "# Heading\n\n"
                "Paragraph one.\n\n"
                "- Item one\n"
            ),
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        document, _ = self.parse(
            result.manifest_path
        )

        prior_end = -1

        for segment in document[
            "segments"
        ]:
            start = segment[
                "canonical_start"
            ]

            end = segment[
                "canonical_end"
            ]

            self.assertGreaterEqual(
                start,
                0,
            )

            self.assertGreaterEqual(
                end,
                start,
            )

            self.assertLessEqual(
                end,
                len(document["text"]),
            )

            self.assertGreater(
                start,
                prior_end,
            )

            self.assertEqual(
                document["text"][
                    start:end
                ],
                segment["text"],
            )

            prior_end = end - 1

    def test_cli_executes_without_warning(
        self,
    ) -> None:
        import subprocess
        import sys

        source = (
            self.sources
            / "cli.txt"
        )

        source.write_text(
            "CLI parse content.\n",
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                (
                    "analysis.prior_art."
                    "parsing.parse_document"
                ),
                "--manifest",
                str(
                    result.manifest_path
                ),
                "--output-root",
                str(self.parsed),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stderr,
        )

        self.assertNotIn(
            "RuntimeWarning",
            completed.stderr,
        )

        payload = json.loads(
            completed.stdout
        )

        self.assertEqual(
            payload["status"],
            "PARSED",
        )

        self.assertEqual(
            payload["route"],
            "TEXT",
        )

    @unittest.skipUnless(
        shutil.which("pdftotext")
        and shutil.which("pdfinfo"),
        "Poppler tools unavailable",
    )
    def test_blank_pdf_page_requires_ocr(
        self,
    ) -> None:
        pdf_path = (
            self.sources
            / "blank.pdf"
        )

        pdf_path.write_bytes(
            b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
186
%%EOF
"""
        )

        result = self.ingest(
            pdf_path
        )

        document, _ = self.parse(
            result.manifest_path
        )

        self.assertEqual(
            document[
                "ocr_assessment"
            ][0][
                "classification"
            ],
            "OCR_REQUIRED",
        )

        self.assertIn(
            "NO_EMBEDDED_TEXT",
            document[
                "ocr_assessment"
            ][0][
                "reason_codes"
            ],
        )


if __name__ == "__main__":
    unittest.main()
