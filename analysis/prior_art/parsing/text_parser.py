from __future__ import annotations

import hashlib
import re

from pathlib import Path
from typing import Any


VERSION = "1.0.0"


def normalize_newlines(
    text: str,
) -> str:
    return (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def decode_utf8(
    path: Path,
) -> str:
    payload = path.read_bytes()

    try:
        return payload.decode(
            "utf-8-sig"
        )
    except UnicodeDecodeError as exc:
        raise ValueError(
            "SOURCE_NOT_UTF8"
        ) from exc


def segment_id(
    *,
    artifact_id: str,
    kind: str,
    start: int,
    end: int,
    text: str,
) -> str:
    basis = (
        f"{artifact_id}\n"
        f"{kind}\n"
        f"{start}\n"
        f"{end}\n"
        f"{text}"
    ).encode("utf-8")

    digest = hashlib.sha256(
        basis
    ).hexdigest()

    return f"segment:{digest}"


def parse_text(
    path: Path,
    *,
    artifact_id: str,
    markdown: bool,
) -> tuple[
    str,
    list[dict[str, Any]],
]:
    original = normalize_newlines(
        decode_utf8(path)
    )

    canonical = original

    segments: list[
        dict[str, Any]
    ] = []

    pattern = re.compile(
        r"(?:^|\n)([^\n]+(?:\n(?!\n)[^\n]+)*)",
        re.MULTILINE,
    )

    for match in pattern.finditer(
        canonical
    ):
        raw = match.group(1)

        start = match.start(1)
        end = match.end(1)

        if not raw.strip():
            continue

        kind = "PARAGRAPH"

        stripped = raw.lstrip()

        if markdown:
            if re.match(
                r"^#{1,6}\s+",
                stripped,
            ):
                kind = "HEADING"
            elif re.match(
                r"^(?:[-*+]|\d+[.)])\s+",
                stripped,
            ):
                kind = "LIST_ITEM"

        segments.append(
            {
                "segment_id": (
                    segment_id(
                        artifact_id=(
                            artifact_id
                        ),
                        kind=kind,
                        start=start,
                        end=end,
                        text=raw,
                    )
                ),
                "kind": kind,
                "text": raw,
                "canonical_start": (
                    start
                ),
                "canonical_end": (
                    end
                ),
                "source": {
                    "page_number": None,
                    "source_start": (
                        start
                    ),
                    "source_end": end,
                    "bbox": None,
                    "xml_path": None,
                },
            }
        )

    return canonical, segments
