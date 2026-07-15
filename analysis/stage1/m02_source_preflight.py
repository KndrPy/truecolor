from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from analysis.stage1.canonical_stage1_contracts import (
    ModuleResult,
    SOURCE_STATES,
    Stage1EvidenceError,
    atomic_write_json,
    atomic_write_jsonl,
    ensure_fitz,
    load_json,
    normalized_text,
    sha256_bytes,
    sha256_file,
    stable_id,
    write_closure,
)

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


class SourcePreflight:
    module_id = "S1-M02"

    @staticmethod
    def infer_source_form(
        path: Path,
        metadata: Mapping[str, str],
        text: str,
    ) -> tuple[str, str]:
        searchable = normalized_text(
            " ".join((path.name, metadata.get("title", ""), text[:12000]))
        ).lower()
        if any(value in searchable for value in ("supplement", "supporting information")):
            return "SUPPLEMENT", "HIGH"
        if any(value in searchable for value in ("corrigendum", "erratum", "correction")):
            return "CORRECTION", "HIGH"
        if any(value in searchable for value in ("preprint", "arxiv", "biorxiv", "medrxiv")):
            return "PREPRINT", "HIGH"
        if any(
            value in searchable
            for value in ("accepted manuscript", "author accepted manuscript")
        ):
            return "ACCEPTED_MANUSCRIPT", "HIGH"
        if DOI_RE.search(text[:20000]) and any(
            value in searchable
            for value in (
                "journal",
                "volume",
                "copyright",
                "sage",
                "elsevier",
                "springer",
                "wiley",
            )
        ):
            return "PUBLISHER_VERSION", "MODERATE"
        return "UNKNOWN", "LOW"

    def run(
        self,
        corpus_root: Path,
        physical_registry: Path,
        version_registry: Path,
        output_root: Path,
        expected_sources: Path | None = None,
    ) -> ModuleResult:
        fitz = ensure_fitz()
        corpus_root = corpus_root.resolve()
        physical = list(load_json(physical_registry).get("records", []))
        versions = list(load_json(version_registry).get("records", []))
        expected = (
            list(load_json(expected_sources).get("records", []))
            if expected_sources
            else []
        )
        version_by_file = {str(item["file_id"]): item for item in versions}
        expected_dois = {
            str(item.get("doi", "")).lower()
            for item in expected
            if item.get("doi")
        }

        sources: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        authority: list[dict[str, Any]] = []
        recovery: list[dict[str, Any]] = []

        for physical_record in physical:
            file_id = str(physical_record["file_id"])
            path = (corpus_root / str(physical_record["relative_path"])).resolve()
            version = version_by_file.get(file_id, {})
            source: dict[str, Any] = {
                "source_integrity_id": stable_id(
                    "SOURCE-INTEGRITY", {"file_id": file_id}
                ),
                "file_id": file_id,
                "version_id": version.get("version_id", ""),
                "work_id": version.get("work_id", ""),
                "relative_path": physical_record["relative_path"],
                "binary_sha256": physical_record.get("binary_sha256", ""),
                "signature_valid": False,
                "page_count": 0,
                "renderable_page_count": 0,
                "encrypted": False,
                "malformed": False,
                "truncated": False,
                "image_only_page_count": 0,
                "duplicate_page_groups": [],
                "source_form": "UNKNOWN",
                "source_form_confidence": "LOW",
                "state": "UNREADABLE",
                "reasons": [],
            }
            if not path.is_file():
                source["reasons"].append("SOURCE_FILE_MISSING")
                recovery.append(
                    {**source, "recovery_action": "RESTORE_SOURCE_FILE"}
                )
                sources.append(source)
                continue

            source["binary_sha256"] = source["binary_sha256"] or sha256_file(path)
            source["signature_valid"] = path.read_bytes()[:8].startswith(b"%PDF-")
            if not source["signature_valid"]:
                source["reasons"].append("INVALID_PDF_SIGNATURE")
                recovery.append(
                    {**source, "recovery_action": "OBTAIN_VALID_PDF"}
                )
                sources.append(source)
                continue

            try:
                document = fitz.open(path)
            except Exception as error:
                source["malformed"] = True
                source["reasons"].append(f"OPEN_FAILED:{type(error).__name__}")
                recovery.append(
                    {**source, "recovery_action": "REPAIR_OR_REACQUIRE"}
                )
                sources.append(source)
                continue

            try:
                source["encrypted"] = bool(document.needs_pass)
                if source["encrypted"]:
                    source["state"] = "ENCRYPTED"
                    source["reasons"].append("PASSWORD_REQUIRED")
                    recovery.append(
                        {
                            **source,
                            "recovery_action": (
                                "REQUEST_PASSWORD_OR_UNENCRYPTED_SOURCE"
                            ),
                        }
                    )
                    sources.append(source)
                    continue

                source["page_count"] = len(document)
                metadata = {
                    str(key): str(value or "")
                    for key, value in (document.metadata or {}).items()
                }
                hashes: dict[str, list[int]] = defaultdict(list)
                text_parts: list[str] = []

                for index in range(len(document)):
                    page = document.load_page(index)
                    renderable = True
                    render_error = ""
                    page_hash = ""
                    try:
                        pixmap = page.get_pixmap(
                            matrix=fitz.Matrix(1.0, 1.0),
                            alpha=False,
                        )
                        page_hash = sha256_bytes(pixmap.samples)
                        hashes[page_hash].append(index + 1)
                        source["renderable_page_count"] += 1
                    except Exception as error:
                        renderable = False
                        render_error = f"{type(error).__name__}:{error}"

                    try:
                        text = page.get_text("text")
                    except Exception as error:
                        text = ""
                        render_error = (
                            render_error
                            or f"TEXT:{type(error).__name__}:{error}"
                        )
                    text_parts.append(text)
                    image_only = (
                        renderable
                        and len(re.findall(r"[A-Za-z]{2,}", text)) < 5
                    )
                    if image_only:
                        source["image_only_page_count"] += 1

                    pages.append(
                        {
                            "page_integrity_id": stable_id(
                                "PAGE-INTEGRITY",
                                {"file_id": file_id, "page": index + 1},
                            ),
                            "file_id": file_id,
                            "page_number": index + 1,
                            "renderable": renderable,
                            "render_error": render_error,
                            "width": float(page.rect.width),
                            "height": float(page.rect.height),
                            "rotation": int(page.rotation),
                            "native_text_characters": len(text),
                            "image_only": image_only,
                            "page_image_sha256": page_hash,
                            "state": "READY" if renderable else "UNREADABLE",
                        }
                    )

                source["duplicate_page_groups"] = sorted(
                    group for group in hashes.values() if len(group) > 1
                )
                text = "\n".join(text_parts)
                (
                    source["source_form"],
                    source["source_form_confidence"],
                ) = self.infer_source_form(path, metadata, text)

                if source["page_count"] == 0:
                    source["state"] = "TRUNCATED"
                    source["truncated"] = True
                    source["reasons"].append("ZERO_PAGES")
                elif source["renderable_page_count"] == 0:
                    source["state"] = "UNREADABLE"
                    source["reasons"].append("NO_RENDERABLE_PAGES")
                elif source["renderable_page_count"] < source["page_count"]:
                    source["state"] = "PARTIALLY_READABLE"
                    source["reasons"].append("ONE_OR_MORE_RENDER_FAILURES")
                elif source["image_only_page_count"] == source["page_count"]:
                    source["state"] = "SOURCE_RECOVERY_REQUIRED"
                    source["reasons"].append("FULL_DOCUMENT_OCR_REQUIRED")
                elif source["image_only_page_count"]:
                    source["state"] = "PARTIALLY_READABLE"
                    source["reasons"].append("SELECTIVE_OCR_REQUIRED")
                elif source["source_form"] in {"PREPRINT", "UNKNOWN"}:
                    source["state"] = "VERSION_REVIEW_REQUIRED"
                    source["reasons"].append(
                        "AUTHORITY_FORM_REQUIRES_REVIEW"
                    )
                else:
                    source["state"] = "READY"

                identifiers = version.get("extracted_identifiers", {})
                dois = [
                    str(value).lower()
                    for value in identifiers.get("dois", [])
                ]
                authority.append(
                    {
                        "authority_candidate_id": stable_id(
                            "AUTHORITY",
                            {
                                "file_id": file_id,
                                "form": source["source_form"],
                            },
                        ),
                        "file_id": file_id,
                        "version_id": version.get("version_id", ""),
                        "work_id": version.get("work_id", ""),
                        "source_form": source["source_form"],
                        "source_form_confidence": source[
                            "source_form_confidence"
                        ],
                        "matched_expected_source": any(
                            doi in expected_dois for doi in dois
                        ),
                        "authority_state": (
                            "CANDIDATE_ONLY_REVIEW_REQUIRED"
                        ),
                    }
                )

                if source["state"] != "READY":
                    recovery.append(
                        {
                            **source,
                            "recovery_action": {
                                "PARTIALLY_READABLE": (
                                    "RUN_SELECTIVE_RECOVERY"
                                ),
                                "UNREADABLE": "REPAIR_OR_REACQUIRE",
                                "ENCRYPTED": (
                                    "REQUEST_PASSWORD_OR_UNENCRYPTED_SOURCE"
                                ),
                                "TRUNCATED": "REACQUIRE_COMPLETE_SOURCE",
                                "NON_SCIENTIFIC": "REVIEW_CLASSIFICATION",
                                "VERSION_REVIEW_REQUIRED": (
                                    "REVIEW_SOURCE_AUTHORITY"
                                ),
                                "SOURCE_RECOVERY_REQUIRED": (
                                    "RUN_ADAPTIVE_OCR"
                                ),
                            }[source["state"]],
                        }
                    )
                sources.append(source)
            finally:
                document.close()

        atomic_write_json(
            output_root / "source_integrity_registry.json",
            {"schema_version": 1, "records": sources},
        )
        atomic_write_jsonl(
            output_root / "page_integrity_registry.jsonl",
            pages,
        )
        atomic_write_json(
            output_root / "source_authority_candidates.json",
            {"schema_version": 1, "records": authority},
        )
        atomic_write_json(
            output_root / "source_recovery_queue.json",
            {"schema_version": 1, "records": recovery},
        )

        if {
            str(item["file_id"]) for item in physical
        } != {str(item["file_id"]) for item in sources}:
            raise Stage1EvidenceError(
                "M02 file representation is not total"
            )
        if any(item["state"] not in SOURCE_STATES for item in sources):
            raise Stage1EvidenceError("M02 emitted an invalid source state")
        if any(
            not item["renderable"] and not item["render_error"]
            for item in pages
        ):
            raise Stage1EvidenceError(
                "M02 silently ignored render failure"
            )

        result = ModuleResult(
            "S1-M02",
            "CLOSED",
            "OPEN",
            (
                "source_integrity_registry.json",
                "page_integrity_registry.jsonl",
                "source_authority_candidates.json",
                "source_recovery_queue.json",
            ),
            {
                "files": len(sources),
                "pages": len(pages),
                "recovery": len(recovery),
            },
            {
                "all_files_explicit": "PASS",
                "all_pages_explicit": "PASS",
                "render_failures_preserved": "PASS",
                "authority_non_autonomous": "PASS",
            },
        )
        write_closure(output_root, result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage 1 M02 source preflight and acquisition integrity."
        )
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--physical-registry", required=True)
    parser.add_argument("--version-registry", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-sources")
    args = parser.parse_args()
    result = SourcePreflight().run(
        Path(args.corpus_root),
        Path(args.physical_registry),
        Path(args.version_registry),
        Path(args.output_root),
        Path(args.expected_sources) if args.expected_sources else None,
    )
    print("TRUECOLOR_STAGE1_S1_M02=PASS")
    print(f"module_state={result.module_state}")
    print(f"stage1_state={result.stage1_state}")
    for key, value in sorted(result.counts.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
