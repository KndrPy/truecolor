from __future__ import annotations

from dataclasses import dataclass


class ParserRoutingError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParserRoute:
    route: str
    parser_name: str


ROUTES = {
    "application/pdf": ParserRoute(
        route="PDF",
        parser_name="pdftotext-bbox",
    ),
    "application/xml": ParserRoute(
        route="XML",
        parser_name="stdlib-xml",
    ),
    "text/xml": ParserRoute(
        route="XML",
        parser_name="stdlib-xml",
    ),
    "application/jats+xml": ParserRoute(
        route="XML",
        parser_name="stdlib-xml",
    ),
    "application/tei+xml": ParserRoute(
        route="XML",
        parser_name="stdlib-xml",
    ),
    "text/html": ParserRoute(
        route="HTML",
        parser_name="stdlib-html",
    ),
    "application/xhtml+xml": ParserRoute(
        route="HTML",
        parser_name="stdlib-html",
    ),
    "text/plain": ParserRoute(
        route="TEXT",
        parser_name="canonical-text",
    ),
    "text/markdown": ParserRoute(
        route="MARKDOWN",
        parser_name="canonical-markdown",
    ),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ParserRoute(
        route="DOCX",
        parser_name="stdlib-docx",
    ),
    "text/csv": ParserRoute(
        route="CSV",
        parser_name="stdlib-csv",
    ),
    "text/tab-separated-values": ParserRoute(
        route="TSV",
        parser_name="stdlib-tsv",
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ParserRoute(
        route="XLSX",
        parser_name="openpyxl-xlsx",
    ),
}


def route_parser(
    media_type: str,
) -> ParserRoute:
    normalized = (
        media_type
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    route = ROUTES.get(
        normalized
    )

    if route is None:
        raise ParserRoutingError(
            "UNSUPPORTED_MEDIA_TYPE",
            normalized,
        )

    return route
