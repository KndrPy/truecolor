from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET

from html.parser import HTMLParser
from pathlib import Path
from typing import Any


BLOCK_TAGS = {
    "abstract",
    "article-title",
    "body",
    "caption",
    "div",
    "fig",
    "head",
    "heading",
    "item",
    "label",
    "li",
    "list-item",
    "p",
    "paragraph",
    "ref",
    "sec",
    "section",
    "table",
    "td",
    "th",
    "title",
}


def local_name(
    tag: str,
) -> str:
    return (
        tag.rsplit("}", 1)[-1]
        .lower()
    )


def segment_id(
    *,
    artifact_id: str,
    xml_path: str,
    text: str,
    start: int,
    end: int,
) -> str:
    basis = (
        f"{artifact_id}\n"
        f"{xml_path}\n"
        f"{start}\n"
        f"{end}\n"
        f"{text}"
    ).encode("utf-8")

    return (
        "segment:"
        + hashlib.sha256(
            basis
        ).hexdigest()
    )


def normalized_text(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def parse_xml(
    path: Path,
    *,
    artifact_id: str,
) -> tuple[
    str,
    list[dict[str, Any]],
]:
    try:
        root = ET.parse(
            path
        ).getroot()
    except ET.ParseError as exc:
        raise ValueError(
            "XML_PARSE_FAILED"
        ) from exc

    pieces: list[str] = []
    segments: list[
        dict[str, Any]
    ] = []

    def walk(
        element: ET.Element,
        path_parts: list[str],
    ) -> None:
        name = local_name(
            element.tag
        )

        current_path = (
            "/"
            + "/".join(
                path_parts + [name]
            )
        )

        text = normalized_text(
            " ".join(
                element.itertext()
            )
        )

        if (
            name in BLOCK_TAGS
            and text
        ):
            start = sum(
                len(piece)
                for piece in pieces
            )

            if pieces:
                pieces.append("\n\n")
                start += 2

            pieces.append(text)
            end = start + len(text)

            kind = (
                "HEADING"
                if name in {
                    "article-title",
                    "head",
                    "heading",
                    "title",
                }
                else "XML_ELEMENT"
            )

            segments.append(
                {
                    "segment_id": (
                        segment_id(
                            artifact_id=(
                                artifact_id
                            ),
                            xml_path=(
                                current_path
                            ),
                            text=text,
                            start=start,
                            end=end,
                        )
                    ),
                    "kind": kind,
                    "text": text,
                    "canonical_start": (
                        start
                    ),
                    "canonical_end": (
                        end
                    ),
                    "source": {
                        "page_number": None,
                        "source_start": None,
                        "source_end": None,
                        "bbox": None,
                        "xml_path": (
                            current_path
                        ),
                    },
                }
            )

            return

        counters: dict[
            str,
            int,
        ] = {}

        for child in list(
            element
        ):
            child_name = local_name(
                child.tag
            )

            counters[
                child_name
            ] = (
                counters.get(
                    child_name,
                    0,
                )
                + 1
            )

            walk(
                child,
                path_parts
                + [
                    (
                        f"{name}["
                        f"{counters[child_name]}"
                        "]"
                    )
                ],
            )

    walk(
        root,
        [],
    )

    return "".join(
        pieces
    ), segments


class CanonicalHTMLParser(
    HTMLParser
):
    def __init__(self) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self.stack: list[
            str
        ] = []

        self.blocks: list[
            tuple[str, str]
        ] = []

        self.current: list[
            str
        ] = []

        self.current_path: str | None = (
            None
        )

    def handle_starttag(
        self,
        tag: str,
        attrs: list[
            tuple[str, str | None]
        ],
    ) -> None:
        self.stack.append(
            tag.lower()
        )

        if tag.lower() in BLOCK_TAGS:
            self.flush()

            self.current_path = (
                "/"
                + "/".join(
                    self.stack
                )
            )

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        if tag.lower() in BLOCK_TAGS:
            self.flush()

        if self.stack:
            self.stack.pop()

    def handle_data(
        self,
        data: str,
    ) -> None:
        value = normalized_text(
            html.unescape(data)
        )

        if value:
            self.current.append(
                value
            )

    def flush(self) -> None:
        value = normalized_text(
            " ".join(
                self.current
            )
        )

        if value:
            self.blocks.append(
                (
                    self.current_path
                    or "/html",
                    value,
                )
            )

        self.current = []


def parse_html(
    path: Path,
    *,
    artifact_id: str,
) -> tuple[
    str,
    list[dict[str, Any]],
]:
    parser = CanonicalHTMLParser()

    try:
        source = path.read_text(
            encoding="utf-8-sig"
        )
    except UnicodeDecodeError as exc:
        raise ValueError(
            "SOURCE_NOT_UTF8"
        ) from exc

    parser.feed(source)
    parser.flush()

    pieces: list[str] = []
    segments: list[
        dict[str, Any]
    ] = []

    for xml_path, text in (
        parser.blocks
    ):
        start = sum(
            len(piece)
            for piece in pieces
        )

        if pieces:
            pieces.append("\n\n")
            start += 2

        pieces.append(text)
        end = start + len(text)

        segments.append(
            {
                "segment_id": (
                    segment_id(
                        artifact_id=(
                            artifact_id
                        ),
                        xml_path=(
                            xml_path
                        ),
                        text=text,
                        start=start,
                        end=end,
                    )
                ),
                "kind": (
                    "XML_ELEMENT"
                ),
                "text": text,
                "canonical_start": (
                    start
                ),
                "canonical_end": end,
                "source": {
                    "page_number": None,
                    "source_start": None,
                    "source_end": None,
                    "bbox": None,
                    "xml_path": xml_path,
                },
            }
        )

    return "".join(
        pieces
    ), segments
