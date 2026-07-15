from analysis.stage1.m13_primary_review import _claims_by_work


def test_nested_provenance_path_resolves_claim_to_work() -> None:
    works = [
        {
            "work_id": "WORK-1",
            "source": {"canonical_path": "corpus/papers/example.pdf"},
        }
    ]
    claims = [
        {
            "claim_id": "CLAIM-1",
            "provenance": {"source_path": "corpus/papers/example.pdf"},
        }
    ]
    assert _claims_by_work(works, claims) == {"WORK-1": ["CLAIM-1"]}


def test_nested_filename_alias_resolves_claim_to_work() -> None:
    works = [
        {
            "work_id": "WORK-1",
            "source": {"file_path": "/archive/example.pdf"},
        }
    ]
    claims = [
        {
            "claim_id": "CLAIM-1",
            "provenance": {"filename": "example.pdf"},
        }
    ]
    assert _claims_by_work(works, claims) == {"WORK-1": ["CLAIM-1"]}


def test_plural_m01_file_ids_resolve_scalar_claim_file_id() -> None:
    works = [
        {
            "work_id": "WORK-1",
            "file_ids": ["FILE-0277fba891723fa38d00"],
            "version_ids": ["VERSION-1"],
        }
    ]
    claims = [
        {
            "claim_id": "CLAIM-1",
            "file_id": "FILE-0277fba891723fa38d00",
        }
    ]
    assert _claims_by_work(works, claims) == {"WORK-1": ["CLAIM-1"]}
