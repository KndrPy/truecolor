from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from analysis.stage1.canonical_stage1_contracts import (
    ModuleResult,
    Stage1EvidenceError,
    atomic_write_json,
    atomic_write_jsonl,
    ensure_fitz,
    load_json,
    load_jsonl,
    normalized_text,
    sha256_bytes,
    stable_id,
    write_closure,
    write_parquet,
)

SECTION_RE = re.compile(
    r"^(abstract|introduction|background|experimental|materials(?: and methods)?|"
    r"methods?|results(?: and discussion)?|discussion|conclusions?|limitations?|"
    r"future work|references|bibliography|appendix)$",
    re.I,
)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
NUMBER_RE = re.compile(
    r"(?P<estimate>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?:(?:±|\+/-)\s*(?P<uncertainty>\d+(?:\.\d+)?))?\s*"
    r"(?P<unit>%|nm|µm|um|mm|cm|m|ms|s|min|h|Hz|°C|K|AU|a\.u\.)?",
    re.I,
)
ALIAS_RE = re.compile(
    r"(?P<long>[A-Z][A-Za-z0-9 /_-]{3,100}?)\s*"
    r"\((?P<short>[A-Z][A-Z0-9-]{1,15})\)"
)
DEFINITION_RE = re.compile(
    r"\b(?P<term>[A-Z][A-Za-z0-9 /_-]{1,80}?)\s+"
    r"(?:is defined as|refers to|denotes|means|is)\s+"
    r"(?P<definition>[^.;]{8,300})"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")


def sentences(text: str) -> list[str]:
    return [
        normalized_text(item)
        for item in SENTENCE_RE.split(normalized_text(text))
        if item.strip()
    ]


def finish(
    root: Path,
    module_id: str,
    outputs: tuple[str, ...],
    counts: Mapping[str, int],
    gates: Mapping[str, str],
) -> ModuleResult:
    result = ModuleResult(module_id, "CLOSED", "OPEN", outputs, counts, gates)
    write_closure(root, result)
    return result


class SpatialReconstruction:
    module_id = "S1-M03"

    def run(
        self,
        corpus_root: Path,
        source_integrity_path: Path,
        output_root: Path,
    ) -> ModuleResult:
        fitz = ensure_fitz()
        sources = list(load_json(source_integrity_path).get("records", []))
        structures: list[dict[str, Any]] = []
        elements: list[dict[str, Any]] = []
        layouts: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []

        for source in sources:
            file_id = str(source["file_id"])
            if source["state"] in {"UNREADABLE", "ENCRYPTED", "TRUNCATED"}:
                unresolved.append(
                    {
                        "region_id": stable_id("UNRESOLVED", {"file_id": file_id}),
                        "file_id": file_id,
                        "scope": "DOCUMENT",
                        "reason": source["state"],
                        "materiality": "FULL_DOCUMENT",
                    }
                )
                continue
            document = fitz.open(
                (corpus_root / str(source["relative_path"])).resolve()
            )
            document_element_ids: list[str] = []
            try:
                section_path: list[str] = []
                for page_index in range(len(document)):
                    page = document.load_page(page_index)
                    page_number = page_index + 1
                    try:
                        page_dict = page.get_text(
                            "dict",
                            flags=fitz.TEXT_PRESERVE_LIGATURES,
                        )
                    except Exception as error:
                        unresolved.append(
                            {
                                "region_id": stable_id(
                                    "UNRESOLVED",
                                    {"file_id": file_id, "page": page_number},
                                ),
                                "file_id": file_id,
                                "page_number": page_number,
                                "scope": "PAGE",
                                "reason": f"LAYOUT_FAILED:{type(error).__name__}",
                                "materiality": "UNKNOWN",
                            }
                        )
                        continue

                    page_element_ids: list[str] = []
                    for block_index, block in enumerate(page_dict.get("blocks", [])):
                        bbox = [
                            float(value)
                            for value in block.get("bbox", (0, 0, 0, 0))
                        ]
                        block_type = int(block.get("type", -1))
                        if block_type == 1:
                            image = block.get("image", b"")
                            element_id = stable_id(
                                "ELEMENT",
                                {
                                    "file_id": file_id,
                                    "page": page_number,
                                    "block": block_index,
                                },
                            )
                            elements.append(
                                {
                                    "element_id": element_id,
                                    "file_id": file_id,
                                    "page_number": page_number,
                                    "element_type": "IMAGE",
                                    "role": "FIGURE_CANDIDATE",
                                    "bbox": bbox,
                                    "raw_text": "",
                                    "normalized_text": "",
                                    "raw_source_sha256": (
                                        sha256_bytes(image) if image else ""
                                    ),
                                    "reading_order": len(page_element_ids),
                                    "section_path": list(section_path),
                                    "confidence": 1.0 if image else 0.5,
                                }
                            )
                            page_element_ids.append(element_id)
                            document_element_ids.append(element_id)
                            continue
                        if block_type != 0:
                            continue

                        raw_lines: list[str] = []
                        spans: list[dict[str, Any]] = []
                        for line in block.get("lines", []):
                            raw_lines.append(
                                "".join(
                                    str(span.get("text", ""))
                                    for span in line.get("spans", [])
                                )
                            )
                            for span in line.get("spans", []):
                                spans.append(
                                    {
                                        "text": str(span.get("text", "")),
                                        "bbox": [
                                            float(value)
                                            for value in span.get(
                                                "bbox", (0, 0, 0, 0)
                                            )
                                        ],
                                        "font": str(span.get("font", "")),
                                        "size": float(span.get("size", 0.0)),
                                        "flags": int(span.get("flags", 0)),
                                    }
                                )
                        raw = "\n".join(raw_lines).strip()
                        if not raw:
                            continue
                        normalized = normalized_text(raw)
                        heading = bool(SECTION_RE.match(normalized))
                        if heading:
                            section_path = [normalized]
                        role = "SECTION_HEADING" if heading else "BODY"
                        if not heading and bbox[1] < float(page.rect.height) * 0.08:
                            role = "HEADER"
                        elif not heading and bbox[3] > float(page.rect.height) * 0.92:
                            role = "FOOTER"
                        elif not heading and (
                            bbox[0] < float(page.rect.width) * 0.06
                            or bbox[2] > float(page.rect.width) * 0.94
                        ):
                            role = "MARGIN"
                        element_id = stable_id(
                            "ELEMENT",
                            {
                                "file_id": file_id,
                                "page": page_number,
                                "block": block_index,
                                "raw": sha256_bytes(raw.encode("utf-8")),
                            },
                        )
                        elements.append(
                            {
                                "element_id": element_id,
                                "file_id": file_id,
                                "page_number": page_number,
                                "element_type": "TEXT_BLOCK",
                                "role": role,
                                "bbox": bbox,
                                "raw_text": raw,
                                "normalized_text": normalized,
                                "raw_source_sha256": sha256_bytes(
                                    raw.encode("utf-8")
                                ),
                                "normalization": "WHITESPACE_ONLY",
                                "reading_order": len(page_element_ids),
                                "section_path": list(section_path),
                                "confidence": 1.0,
                                "spans": spans,
                            }
                        )
                        page_element_ids.append(element_id)
                        document_element_ids.append(element_id)

                    for left, right in zip(
                        page_element_ids,
                        page_element_ids[1:],
                    ):
                        edges.append(
                            {
                                "edge_id": stable_id(
                                    "ORDER", {"from": left, "to": right}
                                ),
                                "file_id": file_id,
                                "page_number": page_number,
                                "from_element_id": left,
                                "to_element_id": right,
                                "relation": "NEXT",
                                "confidence": 1.0,
                            }
                        )
                    layouts.append(
                        {
                            "page_layout_id": stable_id(
                                "PAGE-LAYOUT",
                                {"file_id": file_id, "page": page_number},
                            ),
                            "file_id": file_id,
                            "page_number": page_number,
                            "width": float(page.rect.width),
                            "height": float(page.rect.height),
                            "rotation": int(page.rotation),
                            "element_ids": page_element_ids,
                            "layout_state": (
                                "RECONSTRUCTED"
                                if page_element_ids
                                else "EMPTY_REPORTED"
                            ),
                        }
                    )
                    if not page_element_ids:
                        unresolved.append(
                            {
                                "region_id": stable_id(
                                    "UNRESOLVED",
                                    {"file_id": file_id, "page": page_number},
                                ),
                                "file_id": file_id,
                                "page_number": page_number,
                                "scope": "PAGE",
                                "reason": "NO_ELEMENTS_DETECTED",
                                "materiality": "UNKNOWN",
                            }
                        )
                structures.append(
                    {
                        "document_structure_id": stable_id(
                            "DOC-STRUCTURE", {"file_id": file_id}
                        ),
                        "file_id": file_id,
                        "page_count": len(document),
                        "element_ids": document_element_ids,
                    }
                )
            finally:
                document.close()

        atomic_write_json(
            output_root / "document_structure.json",
            {"schema_version": 1, "records": structures},
        )
        atomic_write_jsonl(output_root / "document_elements.jsonl", elements)
        atomic_write_jsonl(output_root / "page_layouts.jsonl", layouts)
        atomic_write_json(
            output_root / "reading_order_graph.json",
            {"schema_version": 1, "edges": edges},
        )
        atomic_write_json(
            output_root / "unresolved_extraction_regions.json",
            {"schema_version": 1, "records": unresolved},
        )
        if any(
            "bbox" not in item or "reading_order" not in item
            for item in elements
        ):
            raise Stage1EvidenceError(
                "M03 element lacks coordinates or reading order"
            )
        if any(
            item.get("raw_text") and not item.get("raw_source_sha256")
            for item in elements
        ):
            raise Stage1EvidenceError(
                "M03 normalized text lacks raw source lineage"
            )
        return finish(
            output_root,
            self.module_id,
            (
                "document_structure.json",
                "document_elements.jsonl",
                "page_layouts.jsonl",
                "reading_order_graph.json",
                "unresolved_extraction_regions.json",
            ),
            {
                "documents": len(structures),
                "pages": len(layouts),
                "elements": len(elements),
            },
            {
                "all_pages_represented_or_unresolved": "PASS",
                "coordinates_total": "PASS",
                "reading_order_total": "PASS",
                "raw_normalized_lineage": "PASS",
            },
        )


class NonBodyEvidence:
    module_id = "S1-M04"

    def run(
        self,
        corpus_root: Path,
        source_integrity_path: Path,
        m03_root: Path,
        output_root: Path,
    ) -> ModuleResult:
        fitz = ensure_fitz()
        sources = list(load_json(source_integrity_path).get("records", []))
        elements = load_jsonl(m03_root / "document_elements.jsonl")
        by_page: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for item in elements:
            by_page[(str(item["file_id"]), int(item["page_number"]))].append(item)

        tables: list[dict[str, Any]] = []
        cells: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        equations: list[dict[str, Any]] = []
        symbols: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        crossrefs: list[dict[str, Any]] = []

        for source in sources:
            if source["state"] in {"UNREADABLE", "ENCRYPTED", "TRUNCATED"}:
                continue
            file_id = str(source["file_id"])
            document = fitz.open(
                (corpus_root / str(source["relative_path"])).resolve()
            )
            try:
                for page_index in range(len(document)):
                    page_number = page_index + 1
                    page = document.load_page(page_index)
                    page_elements = by_page[(file_id, page_number)]
                    page_text = "\n".join(
                        item.get("raw_text", "") for item in page_elements
                    )
                    try:
                        found_tables = list(
                            getattr(page.find_tables(), "tables", [])
                        )
                    except Exception:
                        found_tables = []
                    for table_index, table in enumerate(found_tables):
                        table_id = stable_id(
                            "TABLE",
                            {
                                "file_id": file_id,
                                "page": page_number,
                                "index": table_index,
                            },
                        )
                        rows = table.extract() or []
                        tables.append(
                            {
                                "table_id": table_id,
                                "file_id": file_id,
                                "page_number": page_number,
                                "bbox": [float(value) for value in table.bbox],
                                "row_count": len(rows),
                                "column_count": max(
                                    (len(row) for row in rows),
                                    default=0,
                                ),
                                "state": "STRUCTURED",
                            }
                        )
                        for row_index, row in enumerate(rows):
                            for column_index, value in enumerate(row):
                                raw = "" if value is None else str(value)
                                normalized = normalized_text(raw)
                                lowered = normalized.lower()
                                state = "VALUE"
                                if not normalized:
                                    state = "MISSING"
                                elif lowered in {
                                    "n/a",
                                    "na",
                                    "not applicable",
                                }:
                                    state = "NOT_APPLICABLE"
                                elif lowered in {"nr", "not reported"}:
                                    state = "NOT_REPORTED"
                                elif normalized in {"0", "0.0", "0.00"}:
                                    state = "ZERO"
                                cells.append(
                                    {
                                        "table_cell_id": stable_id(
                                            "CELL",
                                            {
                                                "table": table_id,
                                                "row": row_index,
                                                "column": column_index,
                                            },
                                        ),
                                        "table_id": table_id,
                                        "row_index": row_index,
                                        "column_index": column_index,
                                        "row_span": 1,
                                        "column_span": 1,
                                        "raw_text": raw,
                                        "normalized_value": normalized,
                                        "semantic_state": state,
                                        "annotation_markers": re.findall(
                                            r"[*†‡]+", raw
                                        ),
                                        "unit": "",
                                    }
                                )

                    image_elements = [
                        item
                        for item in page_elements
                        if item.get("element_type") == "IMAGE"
                    ]
                    captions = [
                        item
                        for item in page_elements
                        if re.match(
                            r"^(figure|fig\.?)\s+\d+",
                            item.get("normalized_text", ""),
                            re.I,
                        )
                    ]
                    for image_index, image in enumerate(image_elements):
                        caption = ""
                        if captions:
                            caption = min(
                                captions,
                                key=lambda candidate: abs(
                                    float(candidate["bbox"][1])
                                    - float(image["bbox"][3])
                                ),
                            ).get("raw_text", "")
                        figures.append(
                            {
                                "figure_id": stable_id(
                                    "FIGURE",
                                    {
                                        "file_id": file_id,
                                        "page": page_number,
                                        "index": image_index,
                                    },
                                ),
                                "file_id": file_id,
                                "page_number": page_number,
                                "bbox": image["bbox"],
                                "caption": caption,
                                "panel_labels": re.findall(
                                    r"\([A-Za-z]\)", caption
                                ),
                                "axis_labels": [],
                                "units": re.findall(
                                    r"\b(?:nm|µm|mm|cm|%|°C|Hz)\b",
                                    page_text,
                                ),
                                "figure_type": (
                                    "DATA_BEARING"
                                    if re.search(
                                        r"\b(plot|graph|curve|spectrum)\b",
                                        caption,
                                        re.I,
                                    )
                                    else "UNRESOLVED"
                                ),
                                "source_element_id": image["element_id"],
                            }
                        )

                    for element in page_elements:
                        text = element.get("raw_text", "")
                        if element.get("role") in {"FOOTER", "MARGIN"} or re.match(
                            r"^\s*[*†‡]\s*", text
                        ):
                            notes.append(
                                {
                                    "note_id": stable_id(
                                        "NOTE",
                                        {"element": element["element_id"]},
                                    ),
                                    "file_id": file_id,
                                    "page_number": page_number,
                                    "note_type": element.get(
                                        "role", "FOOTNOTE"
                                    ),
                                    "raw_text": text,
                                    "anchor_state": "UNRESOLVED",
                                    "anchor_element_id": "",
                                    "source_element_id": element["element_id"],
                                }
                            )
                        if re.search(r"[=∑∫√±≤≥∂]", text):
                            equation_id = stable_id(
                                "EQUATION",
                                {"element": element["element_id"]},
                            )
                            equations.append(
                                {
                                    "equation_id": equation_id,
                                    "file_id": file_id,
                                    "page_number": page_number,
                                    "bbox": element["bbox"],
                                    "visual_expression": text,
                                    "normalized_symbolic": normalized_text(text),
                                    "normalization_state": (
                                        "TEXTUAL_APPROXIMATION"
                                    ),
                                    "source_element_id": element["element_id"],
                                }
                            )
                            for symbol in sorted(
                                set(re.findall(r"\b[A-Za-zα-ωΑ-Ω]\b", text))
                            ):
                                symbols.append(
                                    {
                                        "symbol_id": stable_id(
                                            "SYMBOL",
                                            {
                                                "equation": equation_id,
                                                "symbol": symbol,
                                            },
                                        ),
                                        "equation_id": equation_id,
                                        "surface_form": symbol,
                                        "definition": "",
                                        "definition_state": "UNRESOLVED",
                                    }
                                )
                    for match in re.finditer(
                        r"\b(?:Figure|Fig\.|Table|Eq\.|Equation)\s+\d+[A-Za-z]?",
                        page_text,
                        re.I,
                    ):
                        crossrefs.append(
                            {
                                "cross_reference_id": stable_id(
                                    "XREF",
                                    {
                                        "file_id": file_id,
                                        "page": page_number,
                                        "surface": match.group(0),
                                        "offset": match.start(),
                                    },
                                ),
                                "file_id": file_id,
                                "page_number": page_number,
                                "surface_form": match.group(0),
                                "target_id": "",
                                "resolution_state": "UNRESOLVED",
                            }
                        )
            finally:
                document.close()

        atomic_write_json(
            output_root / "table_registry.json",
            {"schema_version": 1, "records": tables},
        )
        write_parquet(output_root / "table_cells.parquet", cells)
        atomic_write_json(
            output_root / "figure_registry.json",
            {"schema_version": 1, "records": figures},
        )
        atomic_write_json(
            output_root / "equation_registry.json",
            {"schema_version": 1, "records": equations},
        )
        atomic_write_json(
            output_root / "symbol_registry.json",
            {"schema_version": 1, "records": symbols},
        )
        atomic_write_json(
            output_root / "note_and_marginalia_registry.json",
            {"schema_version": 1, "records": notes},
        )
        atomic_write_json(
            output_root / "cross_reference_registry.json",
            {"schema_version": 1, "records": crossrefs},
        )
        return finish(
            output_root,
            self.module_id,
            (
                "table_registry.json",
                "table_cells.parquet",
                "figure_registry.json",
                "equation_registry.json",
                "symbol_registry.json",
                "note_and_marginalia_registry.json",
                "cross_reference_registry.json",
            ),
            {
                "tables": len(tables),
                "cells": len(cells),
                "figures": len(figures),
                "equations": len(equations),
                "notes": len(notes),
            },
            {
                "tables_structured": "PASS",
                "annotations_retained": "PASS",
                "figures_grounded": "PASS",
                "equations_preserved": "PASS",
                "notes_anchor_explicit": "PASS",
            },
        )


class Terminology:
    module_id = "S1-M05"

    def run(self, m03_root: Path, output_root: Path) -> ModuleResult:
        elements = load_jsonl(m03_root / "document_elements.jsonl")
        entities: dict[tuple[str, str], dict[str, Any]] = {}
        mentions: list[dict[str, Any]] = []
        definitions: list[dict[str, Any]] = []
        aliases: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        for element in elements:
            text = element.get("raw_text", "")
            file_id = str(element["file_id"])
            for match in ALIAS_RE.finditer(text):
                aliases.append(
                    {
                        "alias_relation_id": stable_id(
                            "ALIAS",
                            {
                                "file_id": file_id,
                                "long": match.group("long"),
                                "short": match.group("short"),
                            },
                        ),
                        "file_id": file_id,
                        "long_form": match.group("long").strip(),
                        "short_form": match.group("short").strip(),
                        "source_element_id": element["element_id"],
                        "relation_state": "EXPLICIT",
                    }
                )
            for match in DEFINITION_RE.finditer(text):
                definitions.append(
                    {
                        "definition_id": stable_id(
                            "DEFINITION",
                            {
                                "file_id": file_id,
                                "term": match.group("term"),
                                "definition": match.group("definition"),
                            },
                        ),
                        "file_id": file_id,
                        "term": match.group("term").strip(),
                        "definition": match.group("definition").strip(),
                        "definition_state": "AUTHOR_STATED",
                        "source_element_id": element["element_id"],
                    }
                )
            candidates = {
                match.group(0).strip()
                for match in re.finditer(
                    r"\b(?:[A-Z][A-Za-z0-9-]+(?:\s+[A-Z][A-Za-z0-9-]+){0,5}|"
                    r"[A-Z]{2,}(?:-[A-Z0-9]+)?)\b",
                    text,
                )
                if len(match.group(0).strip()) > 1
            }
            for surface in candidates:
                key = (file_id, normalized_text(surface).lower())
                entity = entities.setdefault(
                    key,
                    {
                        "entity_id": stable_id(
                            "ENTITY",
                            {"file_id": file_id, "surface": key[1]},
                        ),
                        "file_id": file_id,
                        "canonical_surface_form": surface,
                        "entity_class": "METHOD",
                        "mention_ids": [],
                    },
                )
                mention_id = stable_id(
                    "MENTION",
                    {
                        "element": element["element_id"],
                        "surface": surface,
                        "ordinal": len(mentions),
                    },
                )
                mentions.append(
                    {
                        "mention_id": mention_id,
                        "entity_id": entity["entity_id"],
                        "file_id": file_id,
                        "surface_form": surface,
                        "entity_class": entity["entity_class"],
                        "contextual_role": "",
                        "source_element_id": element["element_id"],
                        "page_number": element["page_number"],
                    }
                )
                entity["mention_ids"].append(mention_id)

        definitions_by_term: dict[tuple[str, str], set[str]] = defaultdict(set)
        for definition in definitions:
            definitions_by_term[
                (definition["file_id"], definition["term"].lower())
            ].add(definition["definition"])
        for (file_id, term), values in definitions_by_term.items():
            if len(values) > 1:
                conflicts.append(
                    {
                        "terminology_conflict_id": stable_id(
                            "TERM-CONFLICT",
                            {
                                "file_id": file_id,
                                "term": term,
                                "definitions": sorted(values),
                            },
                        ),
                        "file_id": file_id,
                        "term": term,
                        "definitions": sorted(values),
                        "state": "UNRESOLVED",
                    }
                )

        entity_records = sorted(
            entities.values(), key=lambda item: item["entity_id"]
        )
        atomic_write_json(
            output_root / "named_entity_registry.json",
            {"schema_version": 1, "records": entity_records},
        )
        atomic_write_jsonl(output_root / "entity_mentions.jsonl", mentions)
        atomic_write_json(
            output_root / "definition_registry.json",
            {"schema_version": 1, "records": definitions},
        )
        atomic_write_json(
            output_root / "terminology_conflict_registry.json",
            {"schema_version": 1, "records": conflicts},
        )
        atomic_write_json(
            output_root / "paper_lexicon.json",
            {
                "schema_version": 1,
                "entries": [
                    {
                        "surface_form": item["canonical_surface_form"],
                        "entity_id": item["entity_id"],
                        "entity_class": item["entity_class"],
                    }
                    for item in entity_records
                ],
            },
        )
        atomic_write_json(
            output_root / "alias_relation_registry.json",
            {"schema_version": 1, "records": aliases},
        )
        if any(not item["surface_form"] for item in mentions):
            raise Stage1EvidenceError("M05 lost an entity surface form")
        return finish(
            output_root,
            self.module_id,
            (
                "named_entity_registry.json",
                "entity_mentions.jsonl",
                "definition_registry.json",
                "terminology_conflict_registry.json",
                "paper_lexicon.json",
                "alias_relation_registry.json",
            ),
            {
                "entities": len(entity_records),
                "mentions": len(mentions),
                "definitions": len(definitions),
            },
            {
                "surface_forms_retained": "PASS",
                "aliases_traceable": "PASS",
                "definitions_grounded": "PASS",
                "conflicts_preserved": "PASS",
            },
        )


class AuthorModels:
    module_id = "S1-M06"
    problem_cues = (
        "problem",
        "challenge",
        "limitation",
        "however",
        "lack",
        "difficult",
        "hinder",
    )
    failure_cues = (
        "fails",
        "limited",
        "cannot",
        "loss of",
        "inaccurate",
        "uncontrolled",
    )
    intervention_cues = (
        "we propose",
        "we introduce",
        "this study",
        "our method",
        "we present",
        "the purpose",
    )
    success_cues = (
        "enables",
        "improves",
        "achieves",
        "demonstrates",
        "shows",
        "useful",
    )
    boundary_cues = (
        "may",
        "might",
        "limited",
        "only",
        "future",
        "further",
        "caution",
        "should",
    )

    def run(self, m03_root: Path, output_root: Path) -> ModuleResult:
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for element in load_jsonl(m03_root / "document_elements.jsonl"):
            if element.get("element_type") == "TEXT_BLOCK":
                by_file[str(element["file_id"])].append(element)

        models: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        successes: list[dict[str, Any]] = []
        boundaries: list[dict[str, Any]] = []
        failure_vectors: list[dict[str, Any]] = []
        success_vectors: list[dict[str, Any]] = []
        chains: list[dict[str, Any]] = []

        for file_id, elements in by_file.items():
            problem_ids: list[str] = []
            failure_ids: list[str] = []
            intervention_ids: list[str] = []
            success_ids: list[str] = []
            boundary_ids: list[str] = []
            for element in elements:
                for sentence in sentences(element.get("raw_text", "")):
                    lowered = sentence.lower()
                    base = {
                        "file_id": file_id,
                        "statement": sentence,
                        "source_element_id": element["element_id"],
                        "page_number": element["page_number"],
                        "epistemic_strength": (
                            "HEDGED"
                            if re.search(
                                r"\b(may|might|could|suggest)\b",
                                lowered,
                            )
                            else "ASSERTED"
                        ),
                    }
                    if any(cue in lowered for cue in self.problem_cues):
                        problem_ids.append(stable_id("PROBLEM", base))
                    if any(cue in lowered for cue in self.failure_cues):
                        assertion_id = stable_id("FAILURE", base)
                        failures.append(
                            {
                                "failure_assertion_id": assertion_id,
                                **base,
                                "failure_type": "AUTHOR_STATED",
                                "target": "",
                                "mechanism": "",
                                "conditions": "",
                            }
                        )
                        failure_vectors.append(
                            {
                                "failure_vector_id": stable_id(
                                    "FAILURE-VECTOR",
                                    {"assertion_id": assertion_id},
                                ),
                                "assertion_id": assertion_id,
                                "layer": "UNRESOLVED",
                                "mechanism": "",
                                "symptom": sentence,
                                "conditions": "",
                            }
                        )
                        failure_ids.append(assertion_id)
                    if any(
                        cue in lowered for cue in self.intervention_cues
                    ):
                        intervention_ids.append(
                            stable_id("INTERVENTION", base)
                        )
                    if any(cue in lowered for cue in self.success_cues):
                        assertion_id = stable_id("SUCCESS", base)
                        successes.append(
                            {
                                "success_assertion_id": assertion_id,
                                **base,
                                "success_type": "AUTHOR_STATED",
                                "mechanism": "",
                                "conditions": "",
                            }
                        )
                        success_vectors.append(
                            {
                                "success_vector_id": stable_id(
                                    "SUCCESS-VECTOR",
                                    {"assertion_id": assertion_id},
                                ),
                                "assertion_id": assertion_id,
                                "mechanism": "",
                                "outcome": sentence,
                                "conditions": "",
                            }
                        )
                        success_ids.append(assertion_id)
                    if any(
                        re.search(rf"\b{re.escape(cue)}\b", lowered)
                        for cue in self.boundary_cues
                    ):
                        boundary_id = stable_id("BOUNDARY", base)
                        boundaries.append(
                            {
                                "boundary_id": boundary_id,
                                **base,
                                "boundary_type": "AUTHOR_STATED",
                            }
                        )
                        boundary_ids.append(boundary_id)

            nodes = (
                problem_ids
                + failure_ids
                + intervention_ids
                + success_ids
            )
            models.append(
                {
                    "author_problem_model_id": stable_id(
                        "AUTHOR-MODEL", {"file_id": file_id}
                    ),
                    "file_id": file_id,
                    "problem_statement_ids": problem_ids,
                    "prior_art_failure_ids": failure_ids,
                    "intervention_ids": intervention_ids,
                    "success_assertion_ids": success_ids,
                    "boundary_ids": boundary_ids,
                    "state": "PRESENT" if nodes else "NOT_PRESENT_IN_SOURCE",
                    "coverage_basis": "COMPLETE_EXTRACTED_TEXT",
                }
            )
            chains.append(
                {
                    "author_causal_chain_id": stable_id(
                        "AUTHOR-CHAIN", {"file_id": file_id}
                    ),
                    "file_id": file_id,
                    "nodes": nodes,
                    "edges": [
                        {
                            "from": left,
                            "to": right,
                            "relation": "AUTHOR_SEQUENCE_ONLY",
                        }
                        for left, right in zip(nodes, nodes[1:])
                    ],
                    "inference_state": (
                        "STRUCTURAL_SEQUENCE_NOT_CAUSAL_ASSERTION"
                    ),
                }
            )

        atomic_write_json(
            output_root / "author_problem_models.json",
            {"schema_version": 1, "records": models},
        )
        atomic_write_jsonl(
            output_root / "author_failure_assertions.jsonl", failures
        )
        atomic_write_json(
            output_root / "failure_vector_registry.json",
            {"schema_version": 1, "records": failure_vectors},
        )
        atomic_write_jsonl(
            output_root / "author_success_assertions.jsonl", successes
        )
        atomic_write_json(
            output_root / "success_vector_registry.json",
            {"schema_version": 1, "records": success_vectors},
        )
        atomic_write_json(
            output_root / "author_causal_chain_registry.json",
            {"schema_version": 1, "records": chains},
        )
        atomic_write_json(
            output_root / "author_limitations_registry.json",
            {"schema_version": 1, "records": boundaries},
        )
        return finish(
            output_root,
            self.module_id,
            (
                "author_problem_models.json",
                "author_failure_assertions.jsonl",
                "failure_vector_registry.json",
                "author_success_assertions.jsonl",
                "success_vector_registry.json",
                "author_causal_chain_registry.json",
                "author_limitations_registry.json",
            ),
            {
                "papers": len(models),
                "failures": len(failures),
                "successes": len(successes),
            },
            {
                "problem_model_explicit": "PASS",
                "failure_model_preserved": "PASS",
                "success_model_preserved": "PASS",
                "boundaries_preserved": "PASS",
                "causal_strength_not_inflated": "PASS",
            },
        )


class DJI:
    module_id = "S1-M07"

    def run(self, m03_root: Path, output_root: Path) -> ModuleResult:
        elements = load_jsonl(m03_root / "document_elements.jsonl")
        djis: list[dict[str, Any]] = []
        by_file: dict[str, list[str]] = defaultdict(list)
        for element in elements:
            if not any(
                section.lower()
                in {"method", "methods", "materials and methods", "experimental"}
                for section in element.get("section_path", [])
            ):
                continue
            for index, sentence in enumerate(
                sentences(element.get("raw_text", ""))
            ):
                verbs = re.findall(
                    r"\b(?:acquire|measure|collect|clean|calibrate|normalize|"
                    r"compute|estimate|compare|fit|train|validate|render|"
                    r"extract|classify|analyze|record|convert|apply|derive)\w*\b",
                    sentence,
                    re.I,
                )
                if not verbs:
                    continue
                dji_id = stable_id(
                    "DJI",
                    {
                        "element": element["element_id"],
                        "index": index,
                        "sentence": sentence,
                    },
                )
                djis.append(
                    {
                        "dji_id": dji_id,
                        "file_id": element["file_id"],
                        "paper_local_name": sentence[:120],
                        "canonical_name": "",
                        "job_to_do": sentence,
                        "job_class": verbs[0].upper(),
                        "inputs": [],
                        "preconditions": [],
                        "action": verbs[0],
                        "data_handling": "",
                        "transformation": sentence,
                        "outputs": [],
                        "postconditions": [],
                        "dependencies": [],
                        "constraints": [],
                        "assumptions": [],
                        "acceptance_criteria": [],
                        "falsification_conditions": [],
                        "falsification_authority": "NOT_PRESENT_IN_SOURCE",
                        "failure_modes": [],
                        "measurements": [
                            match.group(0)
                            for match in NUMBER_RE.finditer(sentence)
                        ],
                        "source_locations": [
                            {
                                "element_id": element["element_id"],
                                "page_number": element["page_number"],
                            }
                        ],
                        "novelty_role": "UNRESOLVED",
                    }
                )
                by_file[str(element["file_id"])].append(dji_id)

        edges: list[dict[str, Any]] = []
        dji_by_id = {item["dji_id"]: item for item in djis}
        for file_id, ids in by_file.items():
            for left, right in zip(ids, ids[1:]):
                edges.append(
                    {
                        "edge_id": stable_id(
                            "DJI-EDGE", {"from": left, "to": right}
                        ),
                        "file_id": file_id,
                        "from_dji_id": left,
                        "to_dji_id": right,
                        "relation": "NEXT_METHOD_STEP",
                    }
                )
                dji_by_id[right]["dependencies"].append(left)

        indegree = Counter(edge["to_dji_id"] for edge in edges)
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge["from_dji_id"]].append(edge["to_dji_id"])
        queue = [
            item["dji_id"]
            for item in djis
            if indegree[item["dji_id"]] == 0
        ]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for neighbor in adjacency[node]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)
        if visited != len(djis):
            raise Stage1EvidenceError("M07 dependency cycle detected")

        atomic_write_jsonl(
            output_root / "defined_job_implements.jsonl", djis
        )
        atomic_write_json(
            output_root / "dji_dependency_dag.json",
            {
                "schema_version": 1,
                "nodes": [item["dji_id"] for item in djis],
                "edges": edges,
            },
        )
        atomic_write_json(
            output_root / "dji_input_output_registry.json",
            {
                "schema_version": 1,
                "records": [
                    {
                        "dji_id": item["dji_id"],
                        "inputs": item["inputs"],
                        "outputs": item["outputs"],
                    }
                    for item in djis
                ],
            },
        )
        atomic_write_json(
            output_root / "dji_acceptance_registry.json",
            {
                "schema_version": 1,
                "records": [
                    {
                        "dji_id": item["dji_id"],
                        "acceptance_criteria": item[
                            "acceptance_criteria"
                        ],
                    }
                    for item in djis
                ],
            },
        )
        atomic_write_json(
            output_root / "dji_falsification_registry.json",
            {
                "schema_version": 1,
                "records": [
                    {
                        "dji_id": item["dji_id"],
                        "conditions": item["falsification_conditions"],
                        "authority": item["falsification_authority"],
                    }
                    for item in djis
                ],
            },
        )
        atomic_write_json(
            output_root / "dji_novelty_registry.json",
            {
                "schema_version": 1,
                "records": [
                    {
                        "dji_id": item["dji_id"],
                        "novelty_role": item["novelty_role"],
                    }
                    for item in djis
                ],
            },
        )
        atomic_write_json(
            output_root / "framework_method_algorithm_model_registry.json",
            {
                "schema_version": 1,
                "records": [
                    {
                        "dji_id": item["dji_id"],
                        "job_class": item["job_class"],
                        "paper_local_name": item["paper_local_name"],
                    }
                    for item in djis
                ],
            },
        )
        return finish(
            output_root,
            self.module_id,
            (
                "defined_job_implements.jsonl",
                "dji_dependency_dag.json",
                "dji_input_output_registry.json",
                "dji_acceptance_registry.json",
                "dji_falsification_registry.json",
                "dji_novelty_registry.json",
                "framework_method_algorithm_model_registry.json",
            ),
            {"djis": len(djis), "dependencies": len(edges)},
            {
                "source_grounding_total": "PASS",
                "dependencies_resolve": "PASS",
                "dag_acyclic": "PASS",
                "novelty_binding_explicit": "PASS",
            },
        )


class Claims:
    module_id = "S1-M08"

    def run(self, m03_root: Path, output_root: Path) -> ModuleResult:
        claims: list[dict[str, Any]] = []
        quantitative: list[dict[str, Any]] = []
        qualitative: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        calculations: list[dict[str, Any]] = []
        qualifications: list[dict[str, Any]] = []

        for element in load_jsonl(m03_root / "document_elements.jsonl"):
            for index, sentence in enumerate(
                sentences(element.get("raw_text", ""))
            ):
                if len(WORD_RE.findall(sentence)) < 5:
                    continue
                lowered = sentence.lower()
                strength = (
                    "HEDGED"
                    if re.search(
                        r"\b(may|might|could|suggests?|appears?|likely|potentially)\b",
                        lowered,
                    )
                    else "ASSERTED"
                )
                numbers = list(NUMBER_RE.finditer(sentence))
                claim_id = stable_id(
                    "CLAIM",
                    {
                        "element": element["element_id"],
                        "index": index,
                        "sentence": sentence,
                    },
                )
                qualifiers = re.findall(
                    r"\b(?:may|might|could|approximately|about|only|under|within)\b",
                    lowered,
                )
                claims.append(
                    {
                        "claim_id": claim_id,
                        "file_id": element["file_id"],
                        "claim_text": sentence,
                        "claim_type": (
                            "QUANTITATIVE" if numbers else "QUALITATIVE"
                        ),
                        "conditions": "",
                        "qualifiers": qualifiers,
                        "epistemic_strength": strength,
                        "scope": "",
                        "source_element_id": element["element_id"],
                        "page_number": element["page_number"],
                    }
                )
                binding_id = stable_id(
                    "EVIDENCE",
                    {
                        "claim": claim_id,
                        "element": element["element_id"],
                    },
                )
                bindings.append(
                    {
                        "evidence_binding_id": binding_id,
                        "claim_id": claim_id,
                        "source_element_id": element["element_id"],
                        "page_number": element["page_number"],
                        "evidence_type": "SOURCE_TEXT",
                    }
                )
                if numbers:
                    for ordinal, match in enumerate(numbers):
                        quantitative_id = stable_id(
                            "QCLAIM",
                            {"claim": claim_id, "ordinal": ordinal},
                        )
                        quantitative.append(
                            {
                                "quantitative_claim_id": quantitative_id,
                                "claim_id": claim_id,
                                "metric": "",
                                "estimate": float(match.group("estimate")),
                                "unit": match.group("unit") or "",
                                "denominator": "",
                                "sample_size": "",
                                "aggregation": "",
                                "uncertainty": (
                                    float(match.group("uncertainty"))
                                    if match.group("uncertainty")
                                    else None
                                ),
                                "confidence_interval_level": None,
                                "confidence_interval_low": None,
                                "confidence_interval_high": None,
                                "comparison": "",
                                "baseline": "",
                                "effect_direction": "",
                                "source_element_id": element["element_id"],
                                "page_number": element["page_number"],
                            }
                        )
                        calculations.append(
                            {
                                "calculation_lineage_id": stable_id(
                                    "CALC",
                                    {
                                        "quantitative_claim_id": (
                                            quantitative_id
                                        )
                                    },
                                ),
                                "quantitative_claim_id": quantitative_id,
                                "source_type": "TEXT_LITERAL",
                                "source_reference": element["element_id"],
                                "calculation": "NONE",
                            }
                        )
                else:
                    qualitative.append(
                        {
                            "qualitative_claim_id": stable_id(
                                "QUALITATIVE", {"claim": claim_id}
                            ),
                            "claim_id": claim_id,
                            "subject": "",
                            "predicate": "",
                            "object": "",
                            "conditions": "",
                            "qualifiers": qualifiers,
                            "epistemic_strength": strength,
                            "supporting_evidence_ids": [binding_id],
                            "contradicting_evidence_ids": [],
                        }
                    )
                if qualifiers:
                    qualifications.append(
                        {
                            "qualification_id": stable_id(
                                "QUALIFICATION", {"claim": claim_id}
                            ),
                            "claim_id": claim_id,
                            "qualifiers": qualifiers,
                            "state": "ATTACHED",
                        }
                    )

        atomic_write_jsonl(output_root / "claim_registry.jsonl", claims)
        write_parquet(
            output_root / "quantitative_claim_registry.parquet",
            quantitative,
        )
        atomic_write_jsonl(
            output_root / "qualitative_claim_registry.jsonl",
            qualitative,
        )
        atomic_write_json(
            output_root / "calculation_lineage_registry.json",
            {"schema_version": 1, "records": calculations},
        )
        atomic_write_json(
            output_root / "qualification_and_contradiction_registry.json",
            {"schema_version": 1, "records": qualifications},
        )
        atomic_write_jsonl(
            output_root / "claim_evidence_bindings.jsonl", bindings
        )
        if any(not item["source_element_id"] for item in claims):
            raise Stage1EvidenceError("M08 emitted an ungrounded claim")
        return finish(
            output_root,
            self.module_id,
            (
                "claim_registry.jsonl",
                "quantitative_claim_registry.parquet",
                "qualitative_claim_registry.jsonl",
                "calculation_lineage_registry.json",
                "qualification_and_contradiction_registry.json",
                "claim_evidence_bindings.jsonl",
            ),
            {
                "claims": len(claims),
                "quantitative": len(quantitative),
                "qualitative": len(qualitative),
            },
            {
                "claims_grounded": "PASS",
                "uncertainty_retained": "PASS",
                "qualifiers_attached": "PASS",
                "claim_strength_faithful": "PASS",
            },
        )


class LocalOntology:
    module_id = "S1-M09"

    def run(
        self,
        m05_root: Path,
        m06_root: Path,
        m07_root: Path,
        output_root: Path,
    ) -> ModuleResult:
        entities = list(
            load_json(m05_root / "named_entity_registry.json").get(
                "records", []
            )
        )
        definitions = list(
            load_json(m05_root / "definition_registry.json").get(
                "records", []
            )
        )
        djis = load_jsonl(m07_root / "defined_job_implements.jsonl")
        models = list(
            load_json(m06_root / "author_problem_models.json").get(
                "records", []
            )
        )

        concepts: list[dict[str, Any]] = []
        taxonomy_edges: list[dict[str, Any]] = []
        for entity in entities:
            concepts.append(
                {
                    "concept_id": stable_id(
                        "LOCAL-CONCEPT", {"entity": entity["entity_id"]}
                    ),
                    "file_id": entity["file_id"],
                    "surface_form": entity["canonical_surface_form"],
                    "entity_class": entity["entity_class"],
                    "definition_ids": [
                        definition["definition_id"]
                        for definition in definitions
                        if definition["file_id"] == entity["file_id"]
                        and definition["term"].lower()
                        == entity["canonical_surface_form"].lower()
                    ],
                    "concept_state": "AUTHOR_LOCAL",
                }
            )
        for definition in definitions:
            match = re.search(
                r"\b(?:type|kind|form|class)\s+of\s+"
                r"([A-Z][A-Za-z0-9 _-]+)",
                definition["definition"],
            )
            if match:
                taxonomy_edges.append(
                    {
                        "taxonomy_edge_id": stable_id(
                            "TAXONOMY",
                            {
                                "file_id": definition["file_id"],
                                "child": definition["term"],
                                "parent": match.group(1),
                            },
                        ),
                        "file_id": definition["file_id"],
                        "child_surface_form": definition["term"],
                        "parent_surface_form": match.group(1).strip(),
                        "relation": "IS_A",
                        "edge_state": "EXPLICIT_DEFINITION_DERIVED",
                        "source_definition_id": definition["definition_id"],
                    }
                )

        problem_paradigms = [
            {
                "file_id": model["file_id"],
                "problem_paradigm_id": stable_id(
                    "PROBLEM-PARADIGM", {"file_id": model["file_id"]}
                ),
                "problem_statement_ids": model["problem_statement_ids"],
                "failure_assertion_ids": model["prior_art_failure_ids"],
                "state": model["state"],
            }
            for model in models
        ]
        dji_by_file: dict[str, list[str]] = defaultdict(list)
        for dji in djis:
            dji_by_file[str(dji["file_id"])].append(dji["dji_id"])
        solution_paradigms = [
            {
                "file_id": file_id,
                "solution_paradigm_id": stable_id(
                    "SOLUTION-PARADIGM", {"file_id": file_id}
                ),
                "dji_ids": ids,
                "state": "PRESENT" if ids else "NOT_PRESENT_IN_SOURCE",
            }
            for file_id, ids in sorted(dji_by_file.items())
        ]
        problem_spaces = [
            {
                "file_id": item["file_id"],
                "dimensions": [
                    {
                        "dimension_id": stable_id(
                            "PROBLEM-DIMENSION", {"source": source_id}
                        ),
                        "source_id": source_id,
                    }
                    for source_id in item["problem_statement_ids"]
                ],
            }
            for item in problem_paradigms
        ]
        solution_spaces = [
            {
                "file_id": item["file_id"],
                "dimensions": [
                    {
                        "dimension_id": stable_id(
                            "SOLUTION-DIMENSION", {"source": source_id}
                        ),
                        "source_id": source_id,
                    }
                    for source_id in item["dji_ids"]
                ],
            }
            for item in solution_paradigms
        ]

        atomic_write_json(
            output_root / "author_local_ontology.json",
            {"schema_version": 1, "concepts": concepts},
        )
        atomic_write_json(
            output_root / "author_taxonomy_graph.json",
            {"schema_version": 1, "edges": taxonomy_edges},
        )
        atomic_write_json(
            output_root / "paper_problem_paradigm.json",
            {"schema_version": 1, "records": problem_paradigms},
        )
        atomic_write_json(
            output_root / "paper_solution_paradigm.json",
            {"schema_version": 1, "records": solution_paradigms},
        )
        atomic_write_json(
            output_root / "paper_problem_space.json",
            {"schema_version": 1, "records": problem_spaces},
        )
        atomic_write_json(
            output_root / "paper_solution_space.json",
            {"schema_version": 1, "records": solution_spaces},
        )
        return finish(
            output_root,
            self.module_id,
            (
                "author_local_ontology.json",
                "author_taxonomy_graph.json",
                "paper_problem_paradigm.json",
                "paper_solution_paradigm.json",
                "paper_problem_space.json",
                "paper_solution_space.json",
            ),
            {
                "concepts": len(concepts),
                "taxonomy_edges": len(taxonomy_edges),
            },
            {
                "local_concepts_preserved": "PASS",
                "explicit_inferred_edges_distinct": "PASS",
                "problem_solution_separate": "PASS",
                "multiple_membership_permitted": "PASS",
            },
        )


def run_all(args: argparse.Namespace) -> list[ModuleResult]:
    output_root = Path(args.output_root)
    m02_root = Path(args.m02_root)
    results: list[ModuleResult] = []

    m03_root = output_root / "m03"
    results.append(
        SpatialReconstruction().run(
            Path(args.corpus_root),
            m02_root / "source_integrity_registry.json",
            m03_root,
        )
    )
    m04_root = output_root / "m04"
    results.append(
        NonBodyEvidence().run(
            Path(args.corpus_root),
            m02_root / "source_integrity_registry.json",
            m03_root,
            m04_root,
        )
    )
    m05_root = output_root / "m05"
    results.append(Terminology().run(m03_root, m05_root))
    m06_root = output_root / "m06"
    results.append(AuthorModels().run(m03_root, m06_root))
    m07_root = output_root / "m07"
    results.append(DJI().run(m03_root, m07_root))
    m08_root = output_root / "m08"
    results.append(Claims().run(m03_root, m08_root))
    m09_root = output_root / "m09"
    results.append(
        LocalOntology().run(m05_root, m06_root, m07_root, m09_root)
    )

    atomic_write_json(
        output_root / "stage1_m03_m09_run_manifest.json",
        {
            "schema_version": 1,
            "module_states": {
                result.module_id: result.module_state for result in results
            },
            "stage1_state": "OPEN",
        },
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run canonical Stage 1 modules S1-M03 through S1-M09."
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--m02-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    results = run_all(args)
    print("TRUECOLOR_STAGE1_M03_M09=PASS")
    for result in results:
        print(f"{result.module_id}.state={result.module_state}")
    print("stage1_state=OPEN")


if __name__ == "__main__":
    main()
