from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile

from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from .artifact_intake import (
    IntakeError,
    detect_media_type,
    ingest_file,
    sha256_path,
)

from .validate_artifact_intake import (
    SCHEMA_PATH,
    validate_manifest,
)


class ArtifactIntakeTests(
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

        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_source(
        self,
        name: str,
        payload: bytes,
    ) -> Path:
        path = self.sources / name
        path.write_bytes(payload)
        return path

    def test_pdf_signature_overrides_extension(
        self,
    ) -> None:
        source = self.write_source(
            "misleading.txt",
            (
                b"%PDF-1.7\n"
                b"1 0 obj\n"
                b"<<>>\n"
                b"endobj\n"
            ),
        )

        result = ingest_file(
            source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
            declared_media_type=(
                "text/plain"
            ),
        )

        self.assertEqual(
            result.manifest[
                "detected_media_type"
            ],
            "application/pdf",
        )

        self.assertTrue(
            result.manifest[
                "media_type_mismatch"
            ]
        )

    def test_identical_bytes_deduplicate(
        self,
    ) -> None:
        first_source = (
            self.write_source(
                "first.txt",
                b"same evidence\n",
            )
        )

        second_source = (
            self.write_source(
                "second.txt",
                b"same evidence\n",
            )
        )

        first = ingest_file(
            first_source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

        second = ingest_file(
            second_source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

        self.assertEqual(
            first.object_path,
            second.object_path,
        )

        self.assertFalse(
            first.manifest[
                "storage"
            ][
                "deduplicated"
            ]
        )

        self.assertTrue(
            second.manifest[
                "storage"
            ][
                "deduplicated"
            ]
        )

        manifest_files = list(
            self.manifests.rglob(
                "*.json"
            )
        )

        self.assertEqual(
            len(manifest_files),
            2,
        )

    def test_checksum_mismatch_leaves_no_object(
        self,
    ) -> None:
        source = self.write_source(
            "source.txt",
            b"checksum content",
        )

        with self.assertRaises(
            IntakeError
        ) as raised:
            ingest_file(
                source,
                store_root=self.store,
                manifest_root=(
                    self.manifests
                ),
                expected_sha256=(
                    "0" * 64
                ),
            )

        self.assertEqual(
            raised.exception.code,
            "CHECKSUM_MISMATCH",
        )

        objects = list(
            self.store.glob(
                "objects/**/*"
            )
        )

        files = [
            path
            for path in objects
            if path.is_file()
        ]

        self.assertEqual(
            files,
            [],
        )

    def test_size_limit_fails_without_object(
        self,
    ) -> None:
        source = self.write_source(
            "large.bin",
            b"x" * 1025,
        )

        with self.assertRaises(
            IntakeError
        ) as raised:
            ingest_file(
                source,
                store_root=self.store,
                manifest_root=(
                    self.manifests
                ),
                max_bytes=1024,
            )

        self.assertEqual(
            raised.exception.code,
            "SIZE_LIMIT_EXCEEDED",
        )

        self.assertFalse(
            any(
                path.is_file()
                for path in (
                    self.store
                    .glob(
                        "objects/**/*"
                    )
                )
            )
        )

    def test_zero_byte_artifact_is_explicit(
        self,
    ) -> None:
        source = self.write_source(
            "empty.txt",
            b"",
        )

        result = ingest_file(
            source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

        self.assertEqual(
            result.manifest[
                "detected_media_type"
            ],
            "application/x-empty",
        )

        self.assertEqual(
            result.manifest[
                "byte_length"
            ],
            0,
        )

    def test_json_and_jsonl_detection(
        self,
    ) -> None:
        json_path = self.write_source(
            "record.txt",
            b'{"a": 1}\n',
        )

        jsonl_path = self.write_source(
            "records.txt",
            (
                b'{"a": 1}\n'
                b'{"a": 2}\n'
            ),
        )

        self.assertEqual(
            detect_media_type(
                json_path
            ).media_type,
            "application/json",
        )

        self.assertEqual(
            detect_media_type(
                jsonl_path
            ).media_type,
            "application/x-ndjson",
        )

    def test_docx_detected_by_archive_structure(
        self,
    ) -> None:
        source = (
            self.sources
            / "document.bin"
        )

        with zipfile.ZipFile(
            source,
            "w",
        ) as archive:
            archive.writestr(
                "[Content_Types].xml",
                "<Types/>",
            )

            archive.writestr(
                "word/document.xml",
                "<document/>",
            )

        detection = detect_media_type(
            source
        )

        self.assertEqual(
            detection.media_type,
            (
                "application/"
                "vnd.openxmlformats-"
                "officedocument."
                "wordprocessingml."
                "document"
            ),
        )

        self.assertEqual(
            detection.method,
            "ARCHIVE_STRUCTURE",
        )

    def test_manifest_schema_and_object_integrity(
        self,
    ) -> None:
        source = self.write_source(
            "paper.xml",
            (
                b'<?xml version="1.0"?>'
                b"<article><title>"
                b"Test"
                b"</title></article>"
            ),
        )

        result = ingest_file(
            source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

        schema = json.loads(
            SCHEMA_PATH.read_text(
                encoding="utf-8"
            )
        )

        validator = (
            Draft202012Validator(
                schema,
                format_checker=(
                    FormatChecker()
                ),
            )
        )

        schema_errors = list(
            validator.iter_errors(
                result.manifest
            )
        )

        self.assertEqual(
            schema_errors,
            [],
        )

        self.assertEqual(
            validate_manifest(
                result.manifest_path
            ),
            [],
        )

        self.assertEqual(
            sha256_path(
                result.object_path
            ),
            hashlib.sha256(
                source.read_bytes()
            ).hexdigest(),
        )


    def test_module_cli_executes_without_runpy_warning(
        self,
    ) -> None:
        import subprocess
        import sys

        source = self.write_source(
            "cli.xml",
            b"<article><title>CLI</title></article>\n",
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                (
                    "analysis.prior_art.ingestion."
                    "artifact_intake"
                ),
                "--source",
                str(source),
                "--store-root",
                str(self.store),
                "--manifest-root",
                str(self.manifests),
                "--declared-media-type",
                "application/xml",
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
            "STORED_IMMUTABLY",
        )

        self.assertEqual(
            payload[
                "detected_media_type"
            ],
            "application/xml",
        )


    def test_malformed_xml_is_still_classified_as_xml(
        self,
    ) -> None:
        source = self.write_source(
            "malformed.xml",
            (
                b'<?xml version="1.0"?>'
                b"<article><p>broken</article>"
            ),
        )

        detection = detect_media_type(
            source
        )

        self.assertEqual(
            detection.media_type,
            "application/xml",
        )

        self.assertEqual(
            detection.method,
            "STRUCTURAL_TEXT_PROBE",
        )

        self.assertLess(
            detection.confidence,
            0.98,
        )

        self.assertIn(
            (
                "Document is not well-formed; "
                "validation deferred to XML parser"
            ),
            detection.evidence,
        )


    def test_csv_detected_as_csv(
        self,
    ) -> None:
        source = self.write_source(
            "records.csv",
            (
                b"name,value\n"
                b"alpha,1\n"
                b"beta,2\n"
            ),
        )

        detection = detect_media_type(
            source
        )

        self.assertEqual(
            detection.media_type,
            "text/csv",
        )

        self.assertEqual(
            detection.method,
            "TEXT_HEURISTIC",
        )

    def test_tsv_detected_as_tab_separated_values(
        self,
    ) -> None:
        source = self.write_source(
            "records.tsv",
            (
                b"name\tvalue\n"
                b"alpha\t1\n"
                b"beta\t2\n"
            ),
        )

        detection = detect_media_type(
            source
        )

        self.assertEqual(
            detection.media_type,
            "text/tab-separated-values",
        )

        self.assertEqual(
            detection.method,
            "TEXT_HEURISTIC",
        )

    def test_tsv_detection_does_not_require_suffix(
        self,
    ) -> None:
        source = self.write_source(
            "records.data",
            (
                b"name\tvalue\n"
                b"alpha\t1\n"
                b"beta\t2\n"
            ),
        )

        detection = detect_media_type(
            source
        )

        self.assertEqual(
            detection.media_type,
            "text/tab-separated-values",
        )

    def test_xlsx_detected_by_archive_structure(
        self,
    ) -> None:
        source = (
            self.sources
            / "workbook.bin"
        )

        with zipfile.ZipFile(
            source,
            "w",
        ) as archive:
            archive.writestr(
                "[Content_Types].xml",
                "<Types/>",
            )

            archive.writestr(
                "xl/workbook.xml",
                "<workbook/>",
            )

            archive.writestr(
                "xl/worksheets/sheet1.xml",
                "<worksheet/>",
            )

        detection = detect_media_type(
            source
        )

        self.assertEqual(
            detection.media_type,
            (
                "application/"
                "vnd.openxmlformats-"
                "officedocument."
                "spreadsheetml."
                "sheet"
            ),
        )

        self.assertEqual(
            detection.method,
            "ARCHIVE_STRUCTURE",
        )


if __name__ == "__main__":
    unittest.main()
