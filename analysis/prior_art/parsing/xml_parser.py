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


HTML_EXCLUDED_TAGS = {
    "head",
    "script",
    "style",
    "noscript",
    "template",
}

HTML_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

HTML_HEADING_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}

HTML_SEMANTIC_KINDS = {
    "blockquote": "PARAGRAPH",
    "caption": "PARAGRAPH",
    "figcaption": "PARAGRAPH",
    "li": "LIST_ITEM",
    "p": "PARAGRAPH",
    "pre": "PARAGRAPH",
    "td": "TABLE_CELL",
    "th": "TABLE_CELL",
}

HTML_BLOCK_BOUNDARIES = {
    "address",
    "article",
    "aside",
    "blockquote",
    "body",
    "caption",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}

HTML_FALLBACK_CONTAINERS = {
    "article",
    "aside",
    "body",
    "div",
    "figcaption",
    "figure",
    "footer",
    "header",
    "main",
    "nav",
    "section",
}


class CanonicalHTMLParser(
    HTMLParser
):
    def __init__(self) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self.stack: list[
            dict[str, Any]
        ] = []

        self.root_counters: dict[
            str,
            int
        ] = {}

        self.blocks: list[
            dict[str, Any]
        ] = []

    def next_path(
        self,
        tag: str,
    ) -> str:
        counters = (
            self.stack[-1][
                "child_counters"
            ]
            if self.stack
            else self.root_counters
        )

        counters[tag] = (
            counters.get(
                tag,
                0,
            )
            + 1
        )

        parent_path = (
            self.stack[-1]["path"]
            if self.stack
            else ""
        )

        return (
            f"{parent_path}/"
            f"{tag}[{counters[tag]}]"
        )

    def excluded(self) -> bool:
        return bool(
            self.stack
            and self.stack[-1][
                "excluded"
            ]
        )

    def active_record_index(
        self,
    ) -> int | None:
        for frame in reversed(
            self.stack
        ):
            record_index = frame.get(
                "record_index"
            )

            if record_index is not None:
                return int(
                    record_index
                )

        return None

    def clear_fallback_records(
        self,
    ) -> None:
        for frame in self.stack:
            frame[
                "fallback_record_index"
            ] = None

    def fallback_frame(
        self,
    ) -> dict[str, Any] | None:
        for frame in reversed(
            self.stack
        ):
            if frame["tag"] in (
                HTML_FALLBACK_CONTAINERS
            ):
                return frame

        if self.stack:
            return self.stack[-1]

        return None

    def append_record(
        self,
        *,
        path: str,
        kind: str,
    ) -> int:
        self.blocks.append(
            {
                "path": path,
                "kind": kind,
                "parts": [],
            }
        )

        return len(
            self.blocks
        ) - 1

    def close_top(
        self,
    ) -> None:
        if self.stack:
            self.stack.pop()

    def close_to_tag(
        self,
        tag: str,
    ) -> None:
        matching_index = None

        for index in range(
            len(self.stack) - 1,
            -1,
            -1,
        ):
            if (
                self.stack[index][
                    "tag"
                ]
                == tag
            ):
                matching_index = index
                break

        if matching_index is None:
            return

        while (
            len(self.stack)
            > matching_index
        ):
            self.close_top()

    def close_open_paragraph(
        self,
    ) -> None:
        for index in range(
            len(self.stack) - 1,
            -1,
            -1,
        ):
            tag = self.stack[
                index
            ]["tag"]

            if tag == "p":
                while len(
                    self.stack
                ) > index:
                    self.close_top()

                return

            if tag in {
                "body",
                "div",
                "section",
                "article",
                "main",
                "td",
                "th",
                "li",
            }:
                return

    def close_open_list_item(
        self,
    ) -> None:
        for index in range(
            len(self.stack) - 1,
            -1,
            -1,
        ):
            tag = self.stack[
                index
            ]["tag"]

            if tag == "li":
                while len(
                    self.stack
                ) > index:
                    self.close_top()

                return

            if tag in {
                "ol",
                "ul",
            }:
                return

    def close_open_heading(
        self,
    ) -> None:
        for index in range(
            len(self.stack) - 1,
            -1,
            -1,
        ):
            if (
                self.stack[index][
                    "tag"
                ]
                in HTML_HEADING_TAGS
            ):
                while len(
                    self.stack
                ) > index:
                    self.close_top()

                return

    def handle_starttag(
        self,
        tag: str,
        attrs: list[
            tuple[str, str | None]
        ],
    ) -> None:
        del attrs

        normalized_tag = tag.lower()

        if (
            normalized_tag
            in HTML_BLOCK_BOUNDARIES
        ):
            self.close_open_paragraph()

        if normalized_tag == "li":
            self.close_open_list_item()

        if (
            normalized_tag
            in HTML_HEADING_TAGS
        ):
            self.close_open_heading()

        if (
            normalized_tag
            in HTML_VOID_TAGS
        ):
            self.next_path(
                normalized_tag
            )

            if (
                normalized_tag
                in {
                    "br",
                    "wbr",
                }
                and not self.excluded()
            ):
                record_index = (
                    self.active_record_index()
                )

                if record_index is not None:
                    self.blocks[
                        record_index
                    ]["parts"].append(
                        " "
                    )

            return

        if (
            normalized_tag
            in HTML_BLOCK_BOUNDARIES
        ):
            self.clear_fallback_records()

        path = self.next_path(
            normalized_tag
        )

        excluded = (
            self.excluded()
            or normalized_tag
            in HTML_EXCLUDED_TAGS
        )

        kind = None

        if (
            normalized_tag
            in HTML_HEADING_TAGS
        ):
            kind = "HEADING"
        else:
            kind = (
                HTML_SEMANTIC_KINDS.get(
                    normalized_tag
                )
            )

        record_index = None

        if (
            not excluded
            and kind is not None
            and self.active_record_index()
            is None
        ):
            record_index = (
                self.append_record(
                    path=path,
                    kind=kind,
                )
            )

        self.stack.append(
            {
                "tag": normalized_tag,
                "path": path,
                "excluded": excluded,
                "record_index": (
                    record_index
                ),
                "fallback_record_index": (
                    None
                ),
                "child_counters": {},
            }
        )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[
            tuple[str, str | None]
        ],
    ) -> None:
        normalized_tag = tag.lower()

        self.handle_starttag(
            normalized_tag,
            attrs,
        )

        if (
            normalized_tag
            not in HTML_VOID_TAGS
        ):
            self.handle_endtag(
                normalized_tag
            )

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        self.close_to_tag(
            tag.lower()
        )

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self.excluded():
            return

        value = normalized_text(
            data
        )

        if not value:
            return

        record_index = (
            self.active_record_index()
        )

        if record_index is None:
            frame = self.fallback_frame()

            if frame is None:
                path = "/html[1]"
                record_index = (
                    self.append_record(
                        path=path,
                        kind=(
                            "XML_ELEMENT"
                        ),
                    )
                )
            else:
                fallback_index = (
                    frame.get(
                        "fallback_record_index"
                    )
                )

                if fallback_index is None:
                    fallback_index = (
                        self.append_record(
                            path=frame[
                                "path"
                            ],
                            kind=(
                                "XML_ELEMENT"
                            ),
                        )
                    )

                    frame[
                        "fallback_record_index"
                    ] = fallback_index

                record_index = int(
                    fallback_index
                )

        self.blocks[
            record_index
        ]["parts"].append(
            value
        )

    def finish(
        self,
    ) -> None:
        while self.stack:
            self.close_top()


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

    try:
        parser.feed(source)
        parser.close()
        parser.finish()
    except Exception as exc:
        raise ValueError(
            "HTML_PARSE_FAILED"
        ) from exc

    pieces: list[str] = []
    segments: list[
        dict[str, Any]
    ] = []

    for block in parser.blocks:
        text = normalized_text(
            " ".join(
                block["parts"]
            )
        )

        if not text:
            continue

        if pieces:
            pieces.append(
                "\n\n"
            )

        start = sum(
            len(piece)
            for piece in pieces
        )

        pieces.append(text)

        end = (
            start
            + len(text)
        )

        xml_path = str(
            block["path"]
        )

        kind = str(
            block["kind"]
        )

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
                "kind": kind,
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
