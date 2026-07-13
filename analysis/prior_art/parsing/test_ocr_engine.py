from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from analysis.prior_art.parsing.ocr_engine import (
    OCRExecutionError,
    OCRWord,
    canonical_ocr_text,
    parse_tesseract_tsv,
    pdf_bbox_from_ocr_word,
    png_dimensions,
)


class OCREngineTests(
    unittest.TestCase
):
    def test_tesseract_tsv_words_are_parsed(
        self,
    ) -> None:
        payload = (
            "level\tpage_num\tblock_num\t"
            "par_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\t"
            "conf\ttext\n"
            "1\t1\t0\t0\t0\t0\t"
            "0\t0\t1000\t1000\t-1\t\n"
            "5\t1\t1\t1\t1\t1\t"
            "100\t200\t300\t80\t96.5\tHello\n"
            "5\t1\t1\t1\t1\t2\t"
            "450\t200\t200\t80\t91\tOCR\n"
        )

        words = parse_tesseract_tsv(
            payload
        )

        self.assertEqual(
            len(words),
            2,
        )

        self.assertEqual(
            words[0].text,
            "Hello",
        )

        self.assertEqual(
            words[1].confidence,
            91.0,
        )

    def test_negative_confidence_rows_are_ignored(
        self,
    ) -> None:
        payload = (
            "level\tpage_num\tblock_num\t"
            "par_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\t"
            "conf\ttext\n"
            "5\t1\t1\t1\t1\t1\t"
            "10\t10\t20\t20\t-1\tNoise\n"
        )

        self.assertEqual(
            parse_tesseract_tsv(
                payload
            ),
            (),
        )

    def test_missing_tsv_fields_fail_explicitly(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            OCRExecutionError,
            "text",
        ):
            parse_tesseract_tsv(
                "level\tconf\n5\t90\n"
            )

    def test_canonical_text_preserves_lines(
        self,
    ) -> None:
        words = (
            OCRWord(
                text="Hello",
                confidence=95.0,
                left=0,
                top=0,
                width=10,
                height=10,
                block_number=1,
                paragraph_number=1,
                line_number=1,
                word_number=1,
            ),
            OCRWord(
                text="world",
                confidence=94.0,
                left=20,
                top=0,
                width=10,
                height=10,
                block_number=1,
                paragraph_number=1,
                line_number=1,
                word_number=2,
            ),
            OCRWord(
                text="Next",
                confidence=93.0,
                left=0,
                top=20,
                width=10,
                height=10,
                block_number=1,
                paragraph_number=1,
                line_number=2,
                word_number=1,
            ),
        )

        self.assertEqual(
            canonical_ocr_text(
                words
            ),
            "Hello world\nNext",
        )

    def test_pixel_bbox_maps_to_pdf_coordinates(
        self,
    ) -> None:
        word = OCRWord(
            text="A",
            confidence=90.0,
            left=300,
            top=600,
            width=150,
            height=120,
            block_number=1,
            paragraph_number=1,
            line_number=1,
            word_number=1,
        )

        bbox = pdf_bbox_from_ocr_word(
            word,
            page_width=612.0,
            page_height=792.0,
            image_width=2550,
            image_height=3300,
        )

        self.assertAlmostEqual(
            bbox["x0"],
            72.0,
            places=5,
        )

        self.assertAlmostEqual(
            bbox["y0"],
            144.0,
            places=5,
        )

        self.assertAlmostEqual(
            bbox["x1"],
            108.0,
            places=5,
        )

        self.assertAlmostEqual(
            bbox["y1"],
            172.8,
            places=5,
        )

    def test_png_dimensions_read_ihdr(
        self,
    ) -> None:
        payload = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\r"
            b"IHDR"
            b"\x00\x00\x03\xe8"
            b"\x00\x00\x07\xd0"
            b"\x08\x02\x00\x00\x00"
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = (
                Path(temporary)
                / "image.png"
            )

            path.write_bytes(
                payload
            )

            self.assertEqual(
                png_dimensions(path),
                (
                    1000,
                    2000,
                ),
            )


    def test_pdf_required_page_executes_ocr(
        self,
    ) -> None:
        import xml.etree.ElementTree as ET

        from unittest.mock import patch

        from analysis.prior_art.parsing.ocr_engine import (
            OCRPageResult,
        )

        from analysis.prior_art.parsing.pdf_parser import (
            parse_pdf,
        )

        page_xml = ET.fromstring(
            (
                '<doc>'
                '<page width="612" height="792">'
                '</page>'
                '</doc>'
            )
        )

        result = OCRPageResult(
            page_number=1,
            dpi=300,
            language="eng",
            engine="tesseract",
            engine_version="tesseract 5.3.4",
            render_engine="pdftoppm",
            render_engine_version=(
                "pdftoppm version 24.02.0"
            ),
            image_width=2550,
            image_height=3300,
            words=(
                OCRWord(
                    text="Prior",
                    confidence=96.0,
                    left=300,
                    top=600,
                    width=180,
                    height=90,
                    block_number=1,
                    paragraph_number=1,
                    line_number=1,
                    word_number=1,
                ),
                OCRWord(
                    text="art",
                    confidence=94.0,
                    left=500,
                    top=600,
                    width=120,
                    height=90,
                    block_number=1,
                    paragraph_number=1,
                    line_number=1,
                    word_number=2,
                ),
            ),
            mean_confidence=95.0,
            text="Prior art",
        )

        with (
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.page_count",
                return_value=1,
            ),
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.extract_page_text",
                return_value="",
            ),
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.extract_bbox_xml",
                return_value=page_xml,
            ),
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.execute_page_ocr",
                return_value=result,
            ) as execute,
        ):
            (
                text,
                segments,
                pages,
                assessments,
            ) = parse_pdf(
                Path("immutable.blob"),
                artifact_id=(
                    "artifact:sha256:"
                    + "a" * 64
                ),
            )

        execute.assert_called_once()

        self.assertEqual(
            text,
            "Prior art",
        )

        self.assertEqual(
            len(segments),
            2,
        )

        self.assertEqual(
            pages[0]["text_source"],
            "OCR",
        )

        self.assertEqual(
            pages[0][
                "ocr_mean_confidence"
            ],
            95.0,
        )

        self.assertEqual(
            assessments[0][
                "execution_status"
            ],
            "SUCCEEDED",
        )

        self.assertEqual(
            assessments[0][
                "recognized_word_count"
            ],
            2,
        )

        self.assertEqual(
            segments[0]["source"][
                "extraction_method"
            ],
            "OCR",
        )

        self.assertEqual(
            segments[0]["source"][
                "ocr_confidence"
            ],
            96.0,
        )

        self.assertEqual(
            text[
                segments[1][
                    "canonical_start"
                ]:
                segments[1][
                    "canonical_end"
                ]
            ],
            "art",
        )

    def test_pdf_embedded_page_skips_ocr(
        self,
    ) -> None:
        import xml.etree.ElementTree as ET

        from unittest.mock import patch

        from analysis.prior_art.parsing.pdf_parser import (
            parse_pdf,
        )

        page_xml = ET.fromstring(
            (
                '<doc>'
                '<page width="612" height="792">'
                '<word '
                'xMin="10" yMin="20" '
                'xMax="50" yMax="40">'
                'Embedded'
                '</word>'
                '<word '
                'xMin="60" yMin="20" '
                'xMax="90" yMax="40">'
                'text'
                '</word>'
                '</page>'
                '</doc>'
            )
        )

        embedded_text = (
            "Embedded text with enough words "
            "to prevent OCR execution on this "
            "page during deterministic parsing."
        )

        with (
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.page_count",
                return_value=1,
            ),
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.extract_page_text",
                return_value=embedded_text,
            ),
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.extract_bbox_xml",
                return_value=page_xml,
            ),
            patch(
                "analysis.prior_art.parsing."
                "pdf_parser.execute_page_ocr",
            ) as execute,
        ):
            (
                text,
                segments,
                pages,
                assessments,
            ) = parse_pdf(
                Path("immutable.blob"),
                artifact_id=(
                    "artifact:sha256:"
                    + "b" * 64
                ),
            )

        execute.assert_not_called()

        self.assertEqual(
            text,
            "Embedded text",
        )

        self.assertEqual(
            pages[0]["text_source"],
            "EMBEDDED",
        )

        self.assertEqual(
            assessments[0][
                "execution_status"
            ],
            "NOT_RUN",
        )

        self.assertTrue(
            all(
                segment["source"][
                    "extraction_method"
                ]
                == "EMBEDDED"
                for segment in segments
            )
        )


if __name__ == "__main__":
    unittest.main()
