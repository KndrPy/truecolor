from __future__ import annotations

import gzip
import io
import json
import tarfile
import tempfile
import unittest
import zipfile

from pathlib import Path

from .archive_expansion import (
    ArchiveExpansionError,
    expand_archive,
)

from .artifact_intake import (
    ingest_file,
)

from .build_intake_index import (
    build_index,
)

from .intake_metadata import (
    MetadataError,
    record_metadata,
)


class ArchiveExpansionTests(
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

        self.expansions = (
            self.root / "expansions"
        )

        self.metadata = (
            self.root / "metadata"
        )

        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ingest(
        self,
        path: Path,
    ):
        return ingest_file(
            path,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
        )

    def expand(
        self,
        manifest_path: Path,
        **kwargs,
    ):
        return expand_archive(
            manifest_path,
            store_root=self.store,
            manifest_root=(
                self.manifests
            ),
            expansion_root=(
                self.expansions
            ),
            metadata_root=(
                self.metadata
            ),
            **kwargs,
        )

    def test_zip_expands_regular_files(
        self,
    ) -> None:
        archive_path = (
            self.sources / "bundle.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "a.txt",
                "alpha",
            )

            archive.writestr(
                "folder/b.json",
                '{"b": 2}',
            )

        parent = self.ingest(
            archive_path
        )

        expansion, path = self.expand(
            parent.manifest_path
        )

        self.assertTrue(
            path.is_file()
        )

        self.assertEqual(
            expansion[
                "member_count"
            ],
            2,
        )

        self.assertEqual(
            [
                child[
                    "member_path"
                ]
                for child
                in expansion[
                    "children"
                ]
            ],
            [
                "a.txt",
                "folder/b.json",
            ],
        )

        metadata_files = list(
            self.metadata.rglob(
                "*.metadata.json"
            )
        )

        self.assertEqual(
            len(metadata_files),
            2,
        )

    def test_zip_rejects_traversal(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "traversal.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "../escape.txt",
                "escape",
            )

        parent = self.ingest(
            archive_path
        )

        with self.assertRaises(
            ArchiveExpansionError
        ) as raised:
            self.expand(
                parent.manifest_path
            )

        self.assertEqual(
            raised.exception.code,
            "UNSAFE_MEMBER_PATH",
        )

    def test_zip_rejects_symlink(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "symlink.zip"
        )

        info = zipfile.ZipInfo(
            "link"
        )

        info.create_system = 3
        info.external_attr = (
            0o120777 << 16
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                info,
                "target",
            )

        parent = self.ingest(
            archive_path
        )

        with self.assertRaises(
            ArchiveExpansionError
        ) as raised:
            self.expand(
                parent.manifest_path
            )

        self.assertEqual(
            raised.exception.code,
            "LINK_MEMBER_REJECTED",
        )

    def test_tar_rejects_symlink(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "symlink.tar"
        )

        with tarfile.open(
            archive_path,
            "w",
        ) as archive:
            info = tarfile.TarInfo(
                "link"
            )

            info.type = (
                tarfile.SYMTYPE
            )

            info.linkname = "target"

            archive.addfile(info)

        parent = self.ingest(
            archive_path
        )

        with self.assertRaises(
            ArchiveExpansionError
        ) as raised:
            self.expand(
                parent.manifest_path
            )

        self.assertEqual(
            raised.exception.code,
            "LINK_MEMBER_REJECTED",
        )

    def test_gzip_expands_one_child(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "record.txt.gz"
        )

        with gzip.open(
            archive_path,
            "wb",
        ) as handle:
            handle.write(
                b"compressed evidence\n"
            )

        parent = self.ingest(
            archive_path
        )

        expansion, _ = self.expand(
            parent.manifest_path
        )

        self.assertEqual(
            expansion[
                "member_count"
            ],
            1,
        )

        self.assertEqual(
            expansion[
                "children"
            ][0][
                "member_path"
            ],
            "record.txt",
        )

    def test_member_limit_rejected(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "many.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "a.txt",
                "a",
            )

            archive.writestr(
                "b.txt",
                "b",
            )

        parent = self.ingest(
            archive_path
        )

        with self.assertRaises(
            ArchiveExpansionError
        ) as raised:
            self.expand(
                parent.manifest_path,
                max_members=1,
            )

        self.assertEqual(
            raised.exception.code,
            "MEMBER_LIMIT_EXCEEDED",
        )

    def test_identical_children_deduplicate(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "duplicate.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "a.txt",
                "same",
            )

            archive.writestr(
                "b.txt",
                "same",
            )

        parent = self.ingest(
            archive_path
        )

        expansion, _ = self.expand(
            parent.manifest_path
        )

        first, second = (
            expansion[
                "children"
            ]
        )

        self.assertEqual(
            first[
                "child_artifact_id"
            ],
            second[
                "child_artifact_id"
            ],
        )

        self.assertFalse(
            first["deduplicated"]
        )

        self.assertTrue(
            second["deduplicated"]
        )

    def test_metadata_policy_gate(
        self,
    ) -> None:
        source = (
            self.sources
            / "restricted.txt"
        )

        source.write_text(
            "restricted",
            encoding="utf-8",
        )

        result = self.ingest(
            source
        )

        record, path = record_metadata(
            result.manifest_path,
            metadata_root=(
                self.metadata
            ),
            access_status=(
                "AVAILABLE"
            ),
            license_status=(
                "PROHIBITED"
            ),
        )

        self.assertTrue(
            path.is_file()
        )

        self.assertFalse(
            record[
                "processing_allowed"
            ]
        )

    def test_index_is_deterministic(
        self,
    ) -> None:
        first_path = (
            self.sources / "first.txt"
        )

        second_path = (
            self.sources / "second.txt"
        )

        first_path.write_text(
            "same",
            encoding="utf-8",
        )

        second_path.write_text(
            "same",
            encoding="utf-8",
        )

        first = self.ingest(
            first_path
        )

        second = self.ingest(
            second_path
        )

        record_metadata(
            first.manifest_path,
            metadata_root=(
                self.metadata
            ),
            access_status=(
                "AVAILABLE"
            ),
            license_status=(
                "USER_PROVIDED"
            ),
        )

        record_metadata(
            second.manifest_path,
            metadata_root=(
                self.metadata
            ),
            access_status=(
                "AVAILABLE"
            ),
            license_status=(
                "USER_PROVIDED"
            ),
        )

        first_index = build_index(
            self.manifests,
            metadata_root=(
                self.metadata
            ),
        )

        second_index = build_index(
            self.manifests,
            metadata_root=(
                self.metadata
            ),
        )

        self.assertEqual(
            first_index,
            second_index,
        )

        self.assertEqual(
            first_index[
                "artifact_count"
            ],
            1,
        )

        self.assertEqual(
            first_index[
                "attempt_count"
            ],
            2,
        )

        self.assertEqual(
            first_index[
                "artifacts"
            ][0][
                "attempt_count"
            ],
            2,
        )


    def test_zip_allows_explicit_directory_entries(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "directories.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "paper/",
                b"",
            )

            archive.writestr(
                "paper/article.xml",
                "<article/>",
            )

        parent = self.ingest(
            archive_path
        )

        expansion, _ = self.expand(
            parent.manifest_path
        )

        self.assertEqual(
            expansion["member_count"],
            1,
        )

        self.assertEqual(
            expansion["children"][0][
                "member_path"
            ],
            "paper/article.xml",
        )

    def test_duplicate_member_path_is_rejected(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "duplicate-path.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "paper.txt",
                "first",
            )

            archive.writestr(
                "paper.txt",
                "second",
            )

        parent = self.ingest(
            archive_path
        )

        with self.assertRaises(
            ArchiveExpansionError
        ) as raised:
            self.expand(
                parent.manifest_path
            )

        self.assertEqual(
            raised.exception.code,
            "DUPLICATE_MEMBER_PATH",
        )

    def test_failure_before_commit_leaves_no_children(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "late-invalid.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
        ) as archive:
            archive.writestr(
                "valid.txt",
                "valid",
            )

            archive.writestr(
                "../invalid.txt",
                "invalid",
            )

        parent = self.ingest(
            archive_path
        )

        manifests_before = {
            path
            for path in self.manifests.rglob(
                "intake_*.json"
            )
        }

        objects_before = {
            path
            for path in self.store.rglob(
                "*.blob"
            )
        }

        with self.assertRaises(
            ArchiveExpansionError
        ):
            self.expand(
                parent.manifest_path
            )

        manifests_after = {
            path
            for path in self.manifests.rglob(
                "intake_*.json"
            )
        }

        objects_after = {
            path
            for path in self.store.rglob(
                "*.blob"
            )
        }

        self.assertEqual(
            manifests_after,
            manifests_before,
        )

        self.assertEqual(
            objects_after,
            objects_before,
        )

        self.assertEqual(
            list(
                self.metadata.rglob(
                    "*.metadata.json"
                )
            ),
            [],
        )

        self.assertEqual(
            list(
                self.expansions.rglob(
                    "*.json"
                )
            ),
            [],
        )

    def test_nested_expansion_preserves_root_artifact(
        self,
    ) -> None:
        inner_archive = (
            self.sources / "inner.zip"
        )

        with zipfile.ZipFile(
            inner_archive,
            "w",
        ) as archive:
            archive.writestr(
                "paper.txt",
                "nested",
            )

        outer_archive = (
            self.sources / "outer.zip"
        )

        with zipfile.ZipFile(
            outer_archive,
            "w",
        ) as archive:
            archive.writestr(
                "nested/inner.zip",
                inner_archive.read_bytes(),
            )

        outer = self.ingest(
            outer_archive
        )

        outer_expansion, _ = (
            self.expand(
                outer.manifest_path
            )
        )

        inner_manifest = Path(
            outer_expansion[
                "children"
            ][0][
                "child_manifest_path"
            ]
        )

        inner_expansion, _ = (
            self.expand(
                inner_manifest,
                archive_depth=1,
            )
        )

        nested_attempt_id = (
            inner_expansion[
                "children"
            ][0][
                "child_intake_attempt_id"
            ]
        )

        matching_metadata = []

        for metadata_path in (
            self.metadata.rglob(
                "*.metadata.json"
            )
        ):
            payload = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                payload[
                    "intake_attempt_id"
                ]
                == nested_attempt_id
            ):
                matching_metadata.append(
                    payload
                )

        self.assertEqual(
            len(matching_metadata),
            1,
        )

        self.assertEqual(
            matching_metadata[0][
                "lineage"
            ][
                "root_artifact_id"
            ],
            outer.manifest[
                "artifact_id"
            ],
        )

        self.assertEqual(
            matching_metadata[0][
                "lineage"
            ][
                "archive_depth"
            ],
            2,
        )

    def test_compression_ratio_is_rejected_before_commit(
        self,
    ) -> None:
        archive_path = (
            self.sources
            / "ratio.zip"
        )

        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=(
                zipfile.ZIP_DEFLATED
            ),
        ) as archive:
            archive.writestr(
                "highly-compressible.txt",
                "x" * 100000,
            )

        parent = self.ingest(
            archive_path
        )

        manifests_before = {
            path
            for path in self.manifests.rglob(
                "intake_*.json"
            )
        }

        with self.assertRaises(
            ArchiveExpansionError
        ) as raised:
            self.expand(
                parent.manifest_path,
                max_compression_ratio=2.0,
            )

        self.assertEqual(
            raised.exception.code,
            "COMPRESSION_RATIO_EXCEEDED",
        )

        manifests_after = {
            path
            for path in self.manifests.rglob(
                "intake_*.json"
            )
        }

        self.assertEqual(
            manifests_after,
            manifests_before,
        )


if __name__ == "__main__":
    unittest.main()
