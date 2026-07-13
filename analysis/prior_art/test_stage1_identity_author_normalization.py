from analysis.prior_art.resolve_stage1_identities import (
    author_overlap,
    europe_pmc_authors,
)


def test_europe_pmc_structured_author_order() -> None:
    item = {
        "authorList": {
            "author": [
                {
                    "fullName": "Minakawa M",
                    "firstName": "Masafumi",
                    "lastName": "Minakawa",
                    "initials": "M",
                },
                {
                    "fullName": "Wares MA",
                    "firstName": "Md Abdul",
                    "lastName": "Wares",
                    "initials": "MA",
                },
            ]
        }
    }

    observed = europe_pmc_authors(item)

    assert observed == [
        "Masafumi Minakawa",
        "Md Abdul Wares",
    ]


def test_crossref_europe_pmc_author_overlap() -> None:
    crossref = [
        "Masafumi Minakawa",
        "Md. Abdul Wares",
        "Kazuya Nakano",
        "Hideaki Haneishi",
        "Yoshihisa Aizu",
        "Yoshio Hayasaki",
        "Tetsuo Ikeda",
        "Hajime Nagahara",
        "Izumi Nishidate",
    ]

    europe_pmc = [
        "Masafumi Minakawa",
        "Md Abdul Wares",
        "Kazuya Nakano",
        "Hideaki Haneishi",
        "Yoshihisa Aizu",
        "Yoshio Hayasaki",
        "Tetsuo Ikeda",
        "Hajime Nagahara",
        "Izumi Nishidate",
    ]

    assert author_overlap(
        crossref,
        europe_pmc,
    ) == 1.0


def test_abbreviated_surname_first_authors() -> None:
    assert author_overlap(
        [
            "Jung G",
            "Kim S",
            "Lee J",
            "Yoo S.",
        ],
        [
            "Geunho Jung",
            "Semin Kim",
            "Jongha Lee",
            "Sangwook Yoo",
        ],
    ) == 1.0


def test_compound_abbreviated_surname() -> None:
    assert author_overlap(
        [
            "Di Spiezio Sardo A",
            "Watrowski R",
        ],
        [
            "Attilio Di Spiezio Sardo",
            "Rafał Watrowski",
        ],
    ) == 1.0
