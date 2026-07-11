#!/usr/bin/env bash

# Intentionally no `set -e`: one failed source must not terminate the shell
# or prevent the remaining datasets from downloading.

DATA_ROOT="${DATA_ROOT:-/mnt/d/truecolor-data}"
RAW="$DATA_ROOT/raw"
MANIFESTS="$DATA_ROOT/manifests"
PAPERS="$DATA_ROOT/papers"

mkdir -p \
  "$RAW/issa" \
  "$RAW/nist" \
  "$RAW/camera_css" \
  "$RAW/cie" \
  "$RAW/hyper_skin" \
  "$MANIFESTS" \
  "$PAPERS"

download_file() {
    url="$1"
    output="$2"

    mkdir -p "$(dirname "$output")"

    if [ -s "$output" ]; then
        echo "EXISTS: $output"
        return 0
    fi

    echo "DOWNLOAD: $url"
    curl \
      --fail \
      --location \
      --retry 5 \
      --retry-delay 3 \
      --continue-at - \
      --output "$output" \
      "$url"

    status=$?
    if [ "$status" -ne 0 ]; then
        echo "FAILED: $url"
        rm -f "$output"
        return "$status"
    fi

    echo "WROTE: $output"
}

echo
echo "============================================================"
echo "1. International Skin Spectra Archive — ISSA"
echo "============================================================"

python3 - "$RAW/issa" <<'PY'
import json
import pathlib
import sys
import urllib.request

out_dir = pathlib.Path(sys.argv[1])
out_dir.mkdir(parents=True, exist_ok=True)

article_id = "28228571"
api_url = f"https://api.figshare.com/v2/articles/{article_id}"

request = urllib.request.Request(
    api_url,
    headers={"User-Agent": "truecolor-research-downloader/1.0"},
)

with urllib.request.urlopen(request, timeout=60) as response:
    record = json.load(response)

(out_dir / "figshare_record.json").write_text(
    json.dumps(record, indent=2),
    encoding="utf-8",
)

print("Title:", record.get("title"))
print("Version:", record.get("version"))
print("Files:", len(record.get("files", [])))

for item in record.get("files", []):
    filename = item["name"]
    target = out_dir / filename
    expected_size = item.get("size")

    if target.exists() and expected_size and target.stat().st_size == expected_size:
        print("EXISTS:", target)
        continue

    print("DOWNLOAD:", filename)
    request = urllib.request.Request(
        item["download_url"],
        headers={"User-Agent": "truecolor-research-downloader/1.0"},
    )

    temporary = target.with_suffix(target.suffix + ".part")

    with urllib.request.urlopen(request, timeout=180) as source:
        with temporary.open("wb") as destination:
            while True:
                block = source.read(8 * 1024 * 1024)
                if not block:
                    break
                destination.write(block)

    if expected_size and temporary.stat().st_size != expected_size:
        raise RuntimeError(
            f"Size mismatch for {filename}: "
            f"{temporary.stat().st_size} != {expected_size}"
        )

    temporary.replace(target)
    print("WROTE:", target)
PY

echo
echo "============================================================"
echo "2. Jiang camera spectral sensitivity database"
echo "============================================================"

download_file \
  "https://zenodo.org/records/3245883/files/camspec_database.txt?download=1" \
  "$RAW/camera_css/camspec_database.txt"

download_file \
  "https://zenodo.org/records/3245883/files/camlist%26equipment.txt?download=1" \
  "$RAW/camera_css/camera_equipment.txt"

echo
echo "============================================================"
echo "3. Official CIE colorimetric data"
echo "============================================================"

download_file \
  "https://files.cie.co.at/CIE_xyz_1931_2deg.csv" \
  "$RAW/cie/CIE_xyz_1931_2deg.csv"

download_file \
  "https://files.cie.co.at/CIE_xyz_1931_2deg.csv_metadata.json" \
  "$RAW/cie/CIE_xyz_1931_2deg_metadata.json"

download_file \
  "https://files.cie.co.at/CIE_std_illum_D65.csv" \
  "$RAW/cie/CIE_std_illum_D65.csv"

download_file \
  "https://files.cie.co.at/CIE_std_illum_D65.csv_metadata.json" \
  "$RAW/cie/CIE_std_illum_D65_metadata.json"

echo
echo "============================================================"
echo "4. NIST publication"
echo "============================================================"

download_file \
  "https://nvlpubs.nist.gov/nistpubs/jres/122/jres.122.026.pdf" \
  "$PAPERS/NIST_JRES_122_026_skin_reflectance.pdf"

echo
echo "============================================================"
echo "5. Hyper-Skin public code and access instructions"
echo "============================================================"

if [ -d "$RAW/hyper_skin/Hyper-Skin-2023/.git" ]; then
    echo "UPDATE: Hyper-Skin-2023"
    git -C "$RAW/hyper_skin/Hyper-Skin-2023" pull --ff-only || true
else
    git clone \
      --depth 1 \
      "https://github.com/hyperspectral-skin/Hyper-Skin-2023.git" \
      "$RAW/hyper_skin/Hyper-Skin-2023" || true
fi

echo
echo "============================================================"
echo "6. Verify authoritative checksums"
echo "============================================================"

if [ -s "$RAW/camera_css/camspec_database.txt" ]; then
    actual="$(md5sum "$RAW/camera_css/camspec_database.txt" | awk '{print $1}')"
    expected="dcf7ce9ec9f2c87b87014f5cc46f8c15"
    printf 'camspec_database.txt: %s\n' "$actual"

    if [ "$actual" != "$expected" ]; then
        echo "WARNING: camera CSS MD5 does not match published value."
    fi
fi

if [ -s "$RAW/cie/CIE_xyz_1931_2deg.csv" ]; then
    actual="$(md5sum "$RAW/cie/CIE_xyz_1931_2deg.csv" | awk '{print $1}')"
    expected="17cca777db64b17170f06f67ce9d3ab7"
    printf 'CIE_xyz_1931_2deg.csv: %s\n' "$actual"

    if [ "$actual" != "$expected" ]; then
        echo "WARNING: CIE observer MD5 does not match published value."
    fi
fi

if [ -s "$RAW/cie/CIE_std_illum_D65.csv" ]; then
    actual="$(md5sum "$RAW/cie/CIE_std_illum_D65.csv" | awk '{print $1}')"
    expected="03d4eb9b837c60671627c946fb534deb"
    printf 'CIE_std_illum_D65.csv: %s\n' "$actual"

    if [ "$actual" != "$expected" ]; then
        echo "WARNING: CIE D65 MD5 does not match published value."
    fi
fi

echo
echo "============================================================"
echo "7. Generate reproducibility manifests"
echo "============================================================"

find "$DATA_ROOT" \
  -type f \
  ! -name '*.part' \
  ! -path '*/.git/*' \
  -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$MANIFESTS/SHA256SUMS.txt"

python3 - "$DATA_ROOT" "$MANIFESTS/file_inventory.csv" <<'PY'
import csv
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])

with output.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["relative_path", "size_bytes"])

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if ".git" in path.parts or path.name.endswith(".part"):
            continue

        writer.writerow([path.relative_to(root), path.stat().st_size])
PY

echo
echo "============================================================"
echo "Download pass complete"
echo "============================================================"

du -sh "$DATA_ROOT"
find "$RAW" \
  -maxdepth 3 \
  -type f \
  ! -path '*/.git/*' \
  -printf '%10s  %p\n' \
  | sort -n
