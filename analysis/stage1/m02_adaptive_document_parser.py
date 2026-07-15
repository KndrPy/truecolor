from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

MODULE_ID = "S1-M02"
POLICY_VERSION = "1"


class M02ParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParserPolicy:
    native_min_chars_per_page: int = 80
    printable_ratio_minimum: float = 0.95
    corruption_ratio_maximum: float = 0.02
    lexical_token_minimum: int = 20
    page_coverage_minimum: float = 0.90
    full_ocr_trigger_fraction: float = 0.40
    initial_ocr_dpi: int = 200
    retry_ocr_dpi: int = 300
    maximum_workers: int = 2
    command_timeout_seconds: int = 180


@dataclass(frozen=True)
class TextQuality:
    character_count: int
    printable_ratio: float
    corruption_ratio: float
    lexical_token_count: int
    usable: bool


@dataclass(frozen=True)
class PageResult:
    page_number: int
    state: str
    strategy: str
    text: str
    quality: TextQuality
    attempts: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class Toolchain:
    pdfinfo: str
    pdftotext: str
    pdftoppm: str
    tesseract: str
    ocrmypdf: str | None

    @classmethod
    def detect(cls) -> "Toolchain":
        required = {name: shutil.which(name) for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract")}
        missing = sorted(name for name, path in required.items() if not path)
        if missing:
            raise M02ParseError("required local parsing tools absent: " + ", ".join(missing))
        return cls(
            pdfinfo=str(required["pdfinfo"]),
            pdftotext=str(required["pdftotext"]),
            pdftoppm=str(required["pdftoppm"]),
            tesseract=str(required["tesseract"]),
            ocrmypdf=shutil.which("ocrmypdf"),
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_text(text: str, policy: ParserPolicy) -> TextQuality:
    characters = [char for char in text if not char.isspace()]
    count = len(characters)
    printable = sum(char.isprintable() for char in characters)
    corrupt = text.count("\ufffd") + text.count("�")
    tokens = [token for token in text.replace("\n", " ").split(" ") if any(ch.isalpha() for ch in token)]
    printable_ratio = printable / count if count else 0.0
    corruption_ratio = corrupt / count if count else 1.0
    usable = (
        count >= policy.native_min_chars_per_page
        and printable_ratio >= policy.printable_ratio_minimum
        and corruption_ratio <= policy.corruption_ratio_maximum
        and len(tokens) >= policy.lexical_token_minimum
    )
    return TextQuality(
        character_count=count,
        printable_ratio=round(printable_ratio, 6),
        corruption_ratio=round(corruption_ratio, 6),
        lexical_token_count=len(tokens),
        usable=usable,
    )


class CommandRunner:
    def run(self, command: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "OMP_NUM_THREADS": "1"},
        )


class AdaptiveDocumentParser:
    def __init__(
        self,
        policy: ParserPolicy | None = None,
        toolchain: Toolchain | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.policy = policy or ParserPolicy()
        self.toolchain = toolchain or Toolchain.detect()
        self.runner = runner or CommandRunner()

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return self.runner.run(command, self.policy.command_timeout_seconds)

    def _page_count(self, source: Path) -> int:
        result = self._run((self.toolchain.pdfinfo, source.as_posix()))
        if result.returncode != 0:
            raise M02ParseError("pdfinfo failed: " + result.stderr.strip())
        for line in result.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":", 1)[1].strip())
        raise M02ParseError("pdfinfo did not report page count")

    def _native_page(self, source: Path, page: int) -> tuple[str, Mapping[str, Any]]:
        command = (
            self.toolchain.pdftotext,
            "-f",
            str(page),
            "-l",
            str(page),
            "-layout",
            source.as_posix(),
            "-",
        )
        started = time.perf_counter()
        result = self._run(command)
        return result.stdout, {
            "strategy": "NATIVE_LAYOUT",
            "returncode": result.returncode,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "stderr": result.stderr[-2000:],
        }

    def _alternate_page(self, source: Path, page: int) -> tuple[str, Mapping[str, Any]]:
        started = time.perf_counter()
        try:
            import fitz  # type: ignore
        except ImportError:
            return "", {
                "strategy": "ALTERNATE_NATIVE_PYMUPDF",
                "returncode": 127,
                "elapsed_seconds": 0.0,
                "stderr": "PyMuPDF unavailable",
            }
        try:
            with fitz.open(source) as document:
                text = document.load_page(page - 1).get_text("text")
            return text, {
                "strategy": "ALTERNATE_NATIVE_PYMUPDF",
                "returncode": 0,
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "stderr": "",
            }
        except Exception as error:
            return "", {
                "strategy": "ALTERNATE_NATIVE_PYMUPDF",
                "returncode": 1,
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "stderr": f"{type(error).__name__}: {error}"[-2000:],
            }

    def _ocr_page(self, source: Path, page: int, dpi: int, psm: int) -> tuple[str, Mapping[str, Any]]:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="truecolor-m02-") as temporary:
            prefix = Path(temporary) / "page"
            render = self._run(
                (
                    self.toolchain.pdftoppm,
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-r",
                    str(dpi),
                    "-gray",
                    "-png",
                    source.as_posix(),
                    prefix.as_posix(),
                )
            )
            image = prefix.with_suffix(".png")
            if render.returncode != 0 or not image.is_file():
                return "", {
                    "strategy": f"OCR_{dpi}_DPI_PSM_{psm}",
                    "returncode": render.returncode or 1,
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                    "stderr": render.stderr[-2000:],
                }
            ocr = self._run(
                (
                    self.toolchain.tesseract,
                    image.as_posix(),
                    "stdout",
                    "--dpi",
                    str(dpi),
                    "--psm",
                    str(psm),
                    "-l",
                    "eng",
                )
            )
            return ocr.stdout, {
                "strategy": f"OCR_{dpi}_DPI_PSM_{psm}",
                "returncode": ocr.returncode,
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "stderr": ocr.stderr[-2000:],
            }

    def parse_page(self, source: Path, page: int) -> PageResult:
        attempts: list[Mapping[str, Any]] = []
        text, attempt = self._native_page(source, page)
        attempts.append(attempt)
        quality = evaluate_text(text, self.policy)
        if quality.usable:
            return PageResult(page, "RECOVERED_NATIVE", "NATIVE_LAYOUT", text, quality, tuple(attempts))

        text, attempt = self._alternate_page(source, page)
        attempts.append(attempt)
        quality = evaluate_text(text, self.policy)
        if quality.usable:
            return PageResult(page, "RECOVERED_ALTERNATE", "ALTERNATE_NATIVE_PYMUPDF", text, quality, tuple(attempts))

        text, attempt = self._ocr_page(source, page, self.policy.initial_ocr_dpi, 3)
        attempts.append(attempt)
        quality = evaluate_text(text, self.policy)
        if quality.usable:
            return PageResult(page, "RECOVERED_OCR", attempt["strategy"], text, quality, tuple(attempts))

        text, attempt = self._ocr_page(source, page, self.policy.retry_ocr_dpi, 6)
        attempts.append(attempt)
        quality = evaluate_text(text, self.policy)
        state = "RECOVERED_OCR" if quality.usable else "UNRESOLVED"
        return PageResult(page, state, attempt["strategy"], text, quality, tuple(attempts))

    def parse(self, source: Path, output_root: Path) -> Mapping[str, Any]:
        source = source.resolve()
        output_root = output_root.resolve()
        if not source.is_file():
            raise M02ParseError(f"source PDF absent: {source}")
        if source.read_bytes()[:5] != b"%PDF-":
            raise M02ParseError("source does not have a PDF signature")

        source_hash = sha256_file(source)
        policy_hash = hashlib.sha256(
            json.dumps(asdict(self.policy), sort_keys=True).encode("utf-8")
        ).hexdigest()
        cache_key = hashlib.sha256(
            f"{source_hash}:{POLICY_VERSION}:{policy_hash}".encode("utf-8")
        ).hexdigest()
        document_root = output_root / source_hash
        document_root.mkdir(parents=True, exist_ok=True)
        manifest_path = document_root / "m02_parse_manifest.json"
        text_path = document_root / "document.txt"
        if manifest_path.is_file() and text_path.is_file():
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") == cache_key:
                return {**cached, "cache_state": "HIT"}

        started = time.perf_counter()
        page_count = self._page_count(source)
        pages = [self.parse_page(source, page) for page in range(1, page_count + 1)]
        usable_count = sum(page.quality.usable for page in pages)
        coverage = usable_count / page_count if page_count else 0.0
        unresolved = [page.page_number for page in pages if not page.quality.usable]
        strategies = {page.strategy for page in pages}
        if not unresolved:
            if strategies == {"NATIVE_LAYOUT"}:
                document_state = "RECOVERED_NATIVE"
            elif any(strategy.startswith("OCR_") for strategy in strategies):
                document_state = "RECOVERED_HYBRID" if len(strategies) > 1 else "RECOVERED_OCR"
            else:
                document_state = "RECOVERED_ALTERNATE"
        elif usable_count:
            document_state = "PARTIALLY_RECOVERED"
        else:
            document_state = "UNRESOLVED"

        merged = "\n".join(
            f"\n\f\n[PAGE {page.page_number}]\n{page.text.rstrip()}\n" for page in pages
        )
        temporary = text_path.with_suffix(".tmp")
        temporary.write_text(merged, encoding="utf-8")
        os.replace(temporary, text_path)

        manifest = {
            "schema": "qudipi.stage1.m02-adaptive-document-parse",
            "schema_version": 1,
            "module_id": MODULE_ID,
            "source_path": source.as_posix(),
            "source_sha256": source_hash,
            "cache_key": cache_key,
            "policy": asdict(self.policy),
            "toolchain": asdict(self.toolchain),
            "page_count": page_count,
            "usable_page_count": usable_count,
            "page_coverage": round(coverage, 6),
            "unresolved_pages": unresolved,
            "document_state": document_state,
            "scientificity": "UNRESOLVED_PENDING_CONTENT_ANALYSIS",
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "output_text": text_path.name,
            "output_text_sha256": sha256_file(text_path),
            "pages": [
                {
                    "page_number": page.page_number,
                    "state": page.state,
                    "strategy": page.strategy,
                    "quality": asdict(page.quality),
                    "attempts": list(page.attempts),
                }
                for page in pages
            ],
            "cache_state": "MISS",
        }
        temp_manifest = manifest_path.with_suffix(".tmp")
        temp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp_manifest, manifest_path)
        self._record_cache(output_root / "m02_cache.sqlite3", manifest)
        return manifest

    @staticmethod
    def _record_cache(database: Path, manifest: Mapping[str, Any]) -> None:
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_cache (
                    cache_key TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    document_state TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO parse_cache
                (cache_key, source_sha256, document_state, manifest_path)
                VALUES (?, ?, ?, ?)
                """,
                (
                    manifest["cache_key"],
                    manifest["source_sha256"],
                    manifest["document_state"],
                    str(Path(manifest["source_sha256"]) / "m02_parse_manifest.json"),
                ),
            )
            connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run adaptive local-first Stage 1 M02 parsing.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = AdaptiveDocumentParser().parse(Path(args.input), Path(args.output_root))
    print("QUDIPI_STAGE1_S1_M02=PASS")
    print(f"document_state={result['document_state']}")
    print(f"page_count={result['page_count']}")
    print(f"usable_page_count={result['usable_page_count']}")
    print(f"unresolved_pages={len(result['unresolved_pages'])}")
    print(f"cache_state={result['cache_state']}")


if __name__ == "__main__":
    main()
