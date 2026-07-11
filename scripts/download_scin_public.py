#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


BUCKET = "dx-scin-public-data"
LIST_URL = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
DOWNLOAD_TEMPLATE = (
    "https://storage.googleapis.com/download/storage/v1/"
    f"b/{BUCKET}/o/{{object_name}}?alt=media"
)


def list_objects(session: requests.Session) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        params = {
            "maxResults": 1000,
            "fields": (
                "nextPageToken,"
                "items(name,size,md5Hash,crc32c,updated,contentType,generation)"
            ),
        }

        if page_token:
            params["pageToken"] = page_token

        response = session.get(
            LIST_URL,
            params=params,
            timeout=60,
        )
        response.raise_for_status()

        payload = response.json()
        objects.extend(payload.get("items", []))

        page_token = payload.get("nextPageToken")
        print(
            f"Listed {len(objects):,} objects",
            file=sys.stderr,
        )

        if not page_token:
            break

    return objects


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def download_object(
    session: requests.Session,
    object_name: str,
    expected_size: int,
    destination_root: Path,
    retries: int,
) -> tuple[str, str]:
    destination = destination_root / object_name
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and destination.stat().st_size == expected_size:
        return "exists", sha256_file(destination)

    partial = destination.with_suffix(destination.suffix + ".partial")
    encoded_name = quote(object_name, safe="")
    url = DOWNLOAD_TEMPLATE.format(object_name=encoded_name)

    for attempt in range(1, retries + 1):
        try:
            existing_bytes = partial.stat().st_size if partial.exists() else 0

            headers = {}
            mode = "wb"

            if existing_bytes:
                headers["Range"] = f"bytes={existing_bytes}-"
                mode = "ab"

            with session.get(
                url,
                headers=headers,
                stream=True,
                timeout=(30, 300),
            ) as response:
                if existing_bytes and response.status_code == 200:
                    # Server ignored range request; restart cleanly.
                    existing_bytes = 0
                    mode = "wb"

                response.raise_for_status()

                with partial.open(mode) as output:
                    for chunk in response.iter_content(
                        chunk_size=8 * 1024 * 1024
                    ):
                        if chunk:
                            output.write(chunk)

            actual_size = partial.stat().st_size

            if actual_size != expected_size:
                raise RuntimeError(
                    f"Size mismatch for {object_name}: "
                    f"expected={expected_size}, actual={actual_size}"
                )

            os.replace(partial, destination)
            return "downloaded", sha256_file(destination)

        except Exception as exc:
            print(
                f"Attempt {attempt}/{retries} failed for "
                f"{object_name}: {exc}",
                file=sys.stderr,
            )

            if attempt == retries:
                return "failed", repr(exc)

            time.sleep(min(30, attempt * 3))

    return "failed", "unexpected retry exit"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/mnt/d/truecolor-data/raw/scin/data"),
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=Path("/mnt/d/truecolor-data/manifests"),
    )
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument(
        "--list-only",
        action="store_true",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    args.manifest_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "truecolor-research-acquisition/1.0"
    })

    objects = list_objects(session)

    inventory_json = args.manifest_dir / "scin_public_bucket_inventory.json"
    inventory_json.write_text(json.dumps(objects, indent=2))

    inventory_csv = args.manifest_dir / "scin_public_bucket_inventory.csv"

    with inventory_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "size",
                "contentType",
                "updated",
                "generation",
                "md5Hash",
                "crc32c",
            ],
        )
        writer.writeheader()

        for item in objects:
            writer.writerow({
                key: item.get(key, "")
                for key in writer.fieldnames
            })

    total_bytes = sum(int(item.get("size", 0)) for item in objects)

    print(f"Objects: {len(objects):,}")
    print(f"Bytes: {total_bytes:,}")
    print(f"GiB: {total_bytes / 1024**3:.3f}")
    print(f"Inventory: {inventory_csv}")

    if args.list_only:
        return 0

    result_path = args.manifest_dir / "scin_download_results.csv"

    with result_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "expected_size",
                "status",
                "sha256_or_error",
            ],
        )
        writer.writeheader()

        for index, item in enumerate(objects, start=1):
            name = item["name"]
            expected_size = int(item.get("size", 0))

            status, digest_or_error = download_object(
                session=session,
                object_name=name,
                expected_size=expected_size,
                destination_root=args.output,
                retries=args.retries,
            )

            writer.writerow({
                "name": name,
                "expected_size": expected_size,
                "status": status,
                "sha256_or_error": digest_or_error,
            })
            handle.flush()

            print(
                f"[{index:,}/{len(objects):,}] "
                f"{status}: {name}"
            )

    print(f"Download results: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
