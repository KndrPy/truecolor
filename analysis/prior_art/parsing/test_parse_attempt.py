from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path

from analysis.prior_art.ingestion.artifact_intake import (
    ingest_file,
)

from .parse_attempt import (
    ParseAttemptFailure,
    execute_parse_attempt,
)

from .parse_document import (
    VERSION,
    parse_intake_manifest,
)


class ParseAttemptTests(
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

        self.output = (
            self.root / "parsed"
        )

        self.attempts = (
            self.root / "attempts"
        )

        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ingest_text(
        self,
        text: str = "Parse attempt content.\n",
    ):
        source = (
            self.sources / "source.txt"
        )

        source.write_text(
            text,
            encoding="utf-8",
        )

        return ingest_file(
            source,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

    def execute(
        self,
        manifest_path: Path,
        *,
        prior: str | None = None,
    ):
        return execute_parse_attempt(
            manifest_path=manifest_path,
            output_root=self.output,
            attempt_root=self.attempts,
            parser_version=VERSION,
            prior_parse_attempt_id=prior,
            parse_function=(
                lambda path:
                parse_intake_manifest(
                    path,
                    output_root=(
                        self.output
                    ),
                )
            ),
        )

    def test_success_record_is_persisted(
        self,
    ) -> None:
        intake = self.ingest_text()

        result = self.execute(
            intake.manifest_path
        )

        self.assertEqual(
            result.record["status"],
            "SUCCEEDED",
        )

        self.assertTrue(
            result.record_path.is_file()
        )

        self.assertEqual(
            result.record[
                "state_history"
            ],
            [
                {
                    "state": "STARTED"
                },
                {
                    "state": "SUCCEEDED"
                },
            ],
        )

        self.assertIsNone(
            result.record["error"]
        )

        self.assertTrue(
            result.output_path.is_file()
        )

    def test_attempt_identity_is_deterministic(
        self,
    ) -> None:
        intake = self.ingest_text()

        first = self.execute(
            intake.manifest_path
        )

        second = self.execute(
            intake.manifest_path
        )

        self.assertEqual(
            first.record[
                "parse_attempt_id"
            ],
            second.record[
                "parse_attempt_id"
            ],
        )

        self.assertEqual(
            first.record,
            second.record,
        )

        self.assertEqual(
            first.record_path,
            second.record_path,
        )

    def test_retry_links_prior_attempt(
        self,
    ) -> None:
        intake = self.ingest_text()

        first = self.execute(
            intake.manifest_path
        )

        retry = self.execute(
            intake.manifest_path,
            prior=first.record[
                "parse_attempt_id"
            ],
        )

        self.assertNotEqual(
            first.record[
                "parse_attempt_id"
            ],
            retry.record[
                "parse_attempt_id"
            ],
        )

        self.assertEqual(
            retry.record[
                "prior_parse_attempt_id"
            ],
            first.record[
                "parse_attempt_id"
            ],
        )

    def test_failure_record_is_persisted(
        self,
    ) -> None:
        intake = self.ingest_text()

        manifest = json.loads(
            intake.manifest_path.read_text(
                encoding="utf-8"
            )
        )

        object_path = Path(
            manifest["storage"][
                "object_path"
            ]
        )

        object_path.chmod(
            0o600
        )

        object_path.unlink()

        with self.assertRaises(
            ParseAttemptFailure
        ) as caught:
            self.execute(
                intake.manifest_path
            )

        result = caught.exception.result

        self.assertEqual(
            result.record["status"],
            "FAILED",
        )

        self.assertEqual(
            result.record["error"][
                "code"
            ],
            "SOURCE_OBJECT_MISSING",
        )

        self.assertTrue(
            result.record_path.is_file()
        )

        self.assertIsNone(
            result.record["output_path"]
        )

        self.assertIsNone(
            result.record["document_id"]
        )

    def test_failure_leaves_no_canonical_output(
        self,
    ) -> None:
        intake = self.ingest_text()

        manifest = json.loads(
            intake.manifest_path.read_text(
                encoding="utf-8"
            )
        )

        Path(
            manifest["storage"][
                "object_path"
            ]
        ).unlink()

        with self.assertRaises(
            ParseAttemptFailure
        ):
            self.execute(
                intake.manifest_path
            )

        canonical_files = list(
            self.output.rglob(
                "*.canonical.json"
            )
        )

        self.assertEqual(
            canonical_files,
            [],
        )

    def test_failed_attempt_is_not_reexecuted(
        self,
    ) -> None:
        intake = self.ingest_text()

        invocation_count = 0

        def fail(
            path: Path,
        ):
            nonlocal invocation_count
            del path

            invocation_count += 1

            raise RuntimeError(
                "deterministic failure"
            )

        with self.assertRaises(
            ParseAttemptFailure
        ) as first_failure:
            execute_parse_attempt(
                manifest_path=(
                    intake.manifest_path
                ),
                output_root=self.output,
                attempt_root=self.attempts,
                parser_version=VERSION,
                parse_function=fail,
            )

        first_result = (
            first_failure.exception.result
        )

        first_bytes = (
            first_result.record_path
            .read_bytes()
        )

        with self.assertRaises(
            ParseAttemptFailure
        ) as repeated_failure:
            execute_parse_attempt(
                manifest_path=(
                    intake.manifest_path
                ),
                output_root=self.output,
                attempt_root=self.attempts,
                parser_version=VERSION,
                parse_function=fail,
            )

        repeated_result = (
            repeated_failure.exception.result
        )

        self.assertEqual(
            invocation_count,
            1,
        )

        self.assertEqual(
            first_result.record[
                "parse_attempt_id"
            ],
            repeated_result.record[
                "parse_attempt_id"
            ],
        )

        self.assertEqual(
            first_result.record_path
            .read_bytes(),
            first_bytes,
        )

        self.assertEqual(
            repeated_result.record,
            first_result.record,
        )

    def test_failure_message_is_bounded(
        self,
    ) -> None:
        intake = self.ingest_text()

        def fail(
            path: Path,
        ):
            del path

            raise RuntimeError(
                "x" * 5000
            )

        with self.assertRaises(
            ParseAttemptFailure
        ) as caught:
            execute_parse_attempt(
                manifest_path=(
                    intake.manifest_path
                ),
                output_root=self.output,
                attempt_root=self.attempts,
                parser_version=VERSION,
                parse_function=fail,
            )

        message = (
            caught.exception.result
            .record["error"]["message"]
        )

        self.assertLessEqual(
            len(message),
            1024,
        )

    def test_record_serialization_is_stable(
        self,
    ) -> None:
        intake = self.ingest_text()

        first = self.execute(
            intake.manifest_path
        )

        before = (
            first.record_path.read_bytes()
        )

        second = self.execute(
            intake.manifest_path
        )

        after = (
            second.record_path.read_bytes()
        )

        self.assertEqual(
            before,
            after,
        )

    def test_manifest_identity_is_captured(
        self,
    ) -> None:
        intake = self.ingest_text()

        result = self.execute(
            intake.manifest_path
        )

        self.assertEqual(
            result.record[
                "intake_attempt_id"
            ],
            intake.manifest[
                "intake_attempt_id"
            ],
        )

        self.assertEqual(
            result.record[
                "artifact_id"
            ],
            intake.manifest[
                "artifact_id"
            ],
        )

        self.assertEqual(
            result.record[
                "content_sha256"
            ],
            intake.manifest[
                "content_sha256"
            ],
        )

        self.assertEqual(
            result.record["parser"][
                "route"
            ],
            "TEXT",
        )


if __name__ == "__main__":
    unittest.main()
