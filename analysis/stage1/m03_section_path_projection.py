from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.stage1.canonical_stage1_contracts import (
    Stage1EvidenceError,
    atomic_write_jsonl,
    load_jsonl,
    normalized_text,
)

SECTION_RE = re.compile(
    r"^(abstract|introduction|background|experimental|materials(?: and methods)?|"
    r"methods?|results(?: and discussion)?|discussion|conclusions?|limitations?|"
    r"future work|references|bibliography|appendix)$",
    re.I,
)


def project_section_paths(document_elements_path: Path) -> None:
    records = load_jsonl(document_elements_path)
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_file[str(record["file_id"])].append(record)

    projected: list[dict[str, Any]] = []
    for file_id in sorted(by_file):
        section_path: list[str] = []
        ordered = sorted(
            by_file[file_id],
            key=lambda item: (
                int(item["page_number"]),
                int(item.get("reading_order", 0)),
                str(item["element_id"]),
            ),
        )
        for raw in ordered:
            item = dict(raw)
            text = normalized_text(str(item.get("raw_text", "")))
            heading = bool(SECTION_RE.fullmatch(text))
            if heading:
                section_path = [text]
                item["role"] = "SECTION_HEADING"
            else:
                item.setdefault("role", "BODY")
            item["section_path"] = list(section_path)
            item["section_path_projection"] = (
                "EXACT_HEADING_MATCH" if heading else "INHERITED_FROM_PRECEDING_EXACT_HEADING"
            )
            projected.append(item)

    if len(projected) != len(records):
        raise Stage1EvidenceError("section-path projection changed element cardinality")
    if any("section_path" not in item for item in projected):
        raise Stage1EvidenceError("section-path projection is not total")
    atomic_write_jsonl(document_elements_path, projected)
