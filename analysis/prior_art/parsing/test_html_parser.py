from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from .xml_parser import parse_html


ARTIFACT_ID = (
    "artifact:sha256:"
    + "a" * 64
)


class HTMLParserTests(
    unittest.TestCase
):
    def parse_source(
        self,
        source: str,
    ) -> tuple[
        str,
        list[dict[str, object]],
    ]:
        with tempfile.TemporaryDirectory() as directory:
            path = (
                Path(directory)
                / "source.html"
            )

            path.write_text(
                source,
                encoding="utf-8",
            )

            return parse_html(
                path,
                artifact_id=(
                    ARTIFACT_ID
                ),
            )

    def test_semantic_kinds_and_order(
        self,
    ) -> None:
        text, segments = (
            self.parse_source(
                (
                    "<html><body>"
                    "<h1>Heading</h1>"
                    "<p>First paragraph.</p>"
                    "<ul>"
                    "<li>First item</li>"
                    "<li>Second item</li>"
                    "</ul>"
                    "</body></html>"
                )
            )
        )

        self.assertEqual(
            text,
            (
                "Heading\n\n"
                "First paragraph.\n\n"
                "First item\n\n"
                "Second item"
            ),
        )

        self.assertEqual(
            [
                segment["kind"]
                for segment
                in segments
            ],
            [
                "HEADING",
                "PARAGRAPH",
                "LIST_ITEM",
                "LIST_ITEM",
            ],
        )

    def test_excluded_content_is_absent(
        self,
    ) -> None:
        text, _ = self.parse_source(
            (
                "<html>"
                "<head>"
                "<title>Hidden title</title>"
                "<style>hidden-style</style>"
                "<script>hidden-script</script>"
                "</head>"
                "<body>"
                "<noscript>hidden-noscript</noscript>"
                "<template>hidden-template</template>"
                "<p>Visible content</p>"
                "</body>"
                "</html>"
            )
        )

        self.assertEqual(
            text,
            "Visible content",
        )

    def test_sibling_paths_are_indexed(
        self,
    ) -> None:
        _, segments = self.parse_source(
            (
                "<html><body>"
                "<div>"
                "<p>One</p>"
                "<p>Two</p>"
                "</div>"
                "<div>"
                "<p>Three</p>"
                "</div>"
                "</body></html>"
            )
        )

        paths = [
            segment["source"][
                "xml_path"
            ]
            for segment in segments
        ]

        self.assertEqual(
            paths,
            [
                (
                    "/html[1]/body[1]/"
                    "div[1]/p[1]"
                ),
                (
                    "/html[1]/body[1]/"
                    "div[1]/p[2]"
                ),
                (
                    "/html[1]/body[1]/"
                    "div[2]/p[1]"
                ),
            ],
        )

        self.assertEqual(
            len(paths),
            len(set(paths)),
        )

    def test_mismatched_closing_tag_recovers(
        self,
    ) -> None:
        text, segments = self.parse_source(
            (
                "<html><body>"
                "<div>"
                "<p>First</div>"
                "<p>Second</p>"
                "</body></html>"
            )
        )

        self.assertEqual(
            text,
            "First\n\nSecond",
        )

        self.assertEqual(
            [
                segment["kind"]
                for segment
                in segments
            ],
            [
                "PARAGRAPH",
                "PARAGRAPH",
            ],
        )

    def test_unmatched_closing_tag_does_not_pop(
        self,
    ) -> None:
        text, segments = self.parse_source(
            (
                "<html><body>"
                "<div>"
                "<p>Before</span> After</p>"
                "</div>"
                "</body></html>"
            )
        )

        self.assertEqual(
            text,
            "Before After",
        )

        self.assertEqual(
            len(segments),
            1,
        )

        self.assertEqual(
            segments[0]["kind"],
            "PARAGRAPH",
        )

    def test_void_break_preserves_word_boundary(
        self,
    ) -> None:
        text, segments = self.parse_source(
            (
                "<html><body>"
                "<p>Alpha<br>Beta"
                "<img src='x'>Gamma</p>"
                "</body></html>"
            )
        )

        self.assertEqual(
            text,
            "Alpha Beta Gamma",
        )

        self.assertEqual(
            len(segments),
            1,
        )

    def test_nested_semantic_tags_do_not_duplicate(
        self,
    ) -> None:
        text, segments = self.parse_source(
            (
                "<html><body>"
                "<ul>"
                "<li><p>Nested item</p></li>"
                "</ul>"
                "<table><tr>"
                "<td><p>Cell value</p></td>"
                "</tr></table>"
                "</body></html>"
            )
        )

        self.assertEqual(
            text,
            (
                "Nested item\n\n"
                "Cell value"
            ),
        )

        self.assertEqual(
            [
                segment["kind"]
                for segment
                in segments
            ],
            [
                "LIST_ITEM",
                "TABLE_CELL",
            ],
        )

        self.assertEqual(
            text.count(
                "Nested item"
            ),
            1,
        )

        self.assertEqual(
            text.count(
                "Cell value"
            ),
            1,
        )

    def test_entities_and_inline_text_normalize(
        self,
    ) -> None:
        text, _ = self.parse_source(
            (
                "<html><body>"
                "<p>"
                "Research&nbsp;&amp; "
                "<strong>Development</strong>"
                "</p>"
                "</body></html>"
            )
        )

        self.assertEqual(
            text,
            "Research & Development",
        )

    def test_repeated_parse_is_deterministic(
        self,
    ) -> None:
        source = (
            "<html><body>"
            "<h2>Heading</h2>"
            "<p>Content</p>"
            "<ul><li>Item</li></ul>"
            "</body></html>"
        )

        first = self.parse_source(
            source
        )

        second = self.parse_source(
            source
        )

        self.assertEqual(
            first,
            second,
        )

    def test_ranges_resolve_exactly(
        self,
    ) -> None:
        text, segments = self.parse_source(
            (
                "<html><body>"
                "<h1>Heading</h1>"
                "<p>Paragraph</p>"
                "</body></html>"
            )
        )

        for segment in segments:
            start = segment[
                "canonical_start"
            ]

            end = segment[
                "canonical_end"
            ]

            self.assertEqual(
                text[start:end],
                segment["text"],
            )


if __name__ == "__main__":
    unittest.main()
