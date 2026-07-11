#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(8 * 1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dataset",
        required=True,
    )
    parser.add_argument(
        "--url",
        required=True,
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--manifest-dir",
        default=Path(
            "/mnt/d/truecolor-data/manifests"
        ),
        type=Path,
    )
    parser.add_argument(
        "--allowed-domain",
        action="append",
        required=True,
    )

    args = parser.parse_args()

    args.output.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.manifest_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    allowed_domains = {
        domain.lower()
        for domain in args.allowed_domain
    }

    initial_domain = (
        urlparse(args.url)
        .netloc
        .lower()
    )

    if initial_domain not in allowed_domains:
        raise RuntimeError(
            f"Initial domain {initial_domain!r} "
            f"is not in allowed domains "
            f"{sorted(allowed_domains)}"
        )

    print()
    print("A browser window will open.")
    print("Complete any required login or agreement.")
    print("Click the official dataset download button.")
    print("The script will capture the resulting file.")
    print()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
        )

        context = browser.new_context(
            accept_downloads=True,
        )

        page = context.new_page()

        captured_download = None

        def on_download(download):
            nonlocal captured_download
            captured_download = download

        page.on("download", on_download)
        page.goto(
            args.url,
            wait_until="domcontentloaded",
            timeout=120_000,
        )

        input(
            "After the official download has started, "
            "return here and press Enter..."
        )

        if captured_download is None:
            browser.close()

            raise RuntimeError(
                "No browser download event was captured. "
                "Confirm that the site initiated a file download."
            )

        suggested_name = (
            captured_download.suggested_filename
            or f"{args.dataset}_download"
        )

        temporary_path = Path(
            captured_download.path()
        )

        destination = (
            args.output / suggested_name
        )

        shutil.copy2(
            temporary_path,
            destination,
        )

        source_url = captured_download.url
        source_domain = (
            urlparse(source_url)
            .netloc
            .lower()
        )

        # The final file may be served by an official cloud CDN.
        # Record it, but do not print or commit gated URLs.
        receipt = {
            "dataset": args.dataset,
            "downloaded_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "landing_page": args.url,
            "source_domain": source_domain,
            "filename": destination.name,
            "size_bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "direct_download_url_recorded": False,
            "notes": (
                "Downloaded interactively from the "
                "official dataset landing page."
            ),
        }

        receipt_path = (
            args.manifest_dir
            / f"{args.dataset}_download_receipt.json"
        )

        receipt_path.write_text(
            json.dumps(
                receipt,
                indent=2,
            )
        )

        browser.close()

    print("Downloaded:", destination)
    print("Receipt:", receipt_path)
    print("SHA-256:", receipt["sha256"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
