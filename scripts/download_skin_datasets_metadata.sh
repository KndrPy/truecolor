#!/usr/bin/env bash

set -u

DATA_ROOT="${DATA_ROOT:-/mnt/d/truecolor-data}"
RAW="$DATA_ROOT/raw"
MANIFESTS="$DATA_ROOT/manifests"
LICENSES="$DATA_ROOT/licenses"
ACCESS="$DATA_ROOT/access_records"

mkdir -p "$RAW" "$MANIFESTS" "$LICENSES" "$ACCESS"

clone_or_update() {
    repo_url="$1"
    destination="$2"

    if [ -d "$destination/.git" ]; then
        echo "UPDATE: $destination"
        git -C "$destination" pull --ff-only || true
    elif [ -e "$destination" ]; then
        echo "SKIP: destination exists but is not a Git repository: $destination"
    else
        echo "CLONE: $repo_url"
        git clone --depth 1 "$repo_url" "$destination" || true
    fi
}

download_file() {
    url="$1"
    destination="$2"

    mkdir -p "$(dirname "$destination")"

    if [ -s "$destination" ]; then
        echo "EXISTS: $destination"
        return 0
    fi

    echo "DOWNLOAD: $url"
    curl \
      --fail \
      --location \
      --retry 5 \
      --retry-delay 3 \
      --continue-at - \
      --output "$destination" \
      "$url" || {
        echo "FAILED: $url"
        rm -f "$destination"
        return 1
    }
}

echo "============================================================"
echo "Fitzpatrick17k repository and URL metadata"
echo "============================================================"

clone_or_update \
  "https://github.com/mattgroh/fitzpatrick17k.git" \
  "$RAW/fitzpatrick17k/source"

echo "============================================================"
echo "Corrected Skin Image Datasets / CleanPatrick metadata"
echo "============================================================"

clone_or_update \
  "https://github.com/kakumarabhishek/Corrected-Skin-Image-Datasets.git" \
  "$RAW/cleanpatrick/source"

echo "============================================================"
echo "SCIN code, schema, access notebook and license"
echo "============================================================"

clone_or_update \
  "https://github.com/google-research-datasets/scin.git" \
  "$RAW/scin/source"

echo "============================================================"
echo "PASSION evaluation code — NOT the restricted image archive"
echo "============================================================"

clone_or_update \
  "https://github.com/Digital-Dermatology/PASSION-Evaluation.git" \
  "$RAW/passion/evaluation_code"

cat > "$ACCESS/passion.txt" <<'EOF'
Dataset images require access through the official PASSION website.
The dataset is non-commercial and may not be reposted.
Do not record or commit the direct dataset download URL.
EOF

echo "============================================================"
echo "FairFace code and metadata repository"
echo "============================================================"

clone_or_update \
  "https://github.com/joojs/fairface.git" \
  "$RAW/fairface/source"

echo "============================================================"
echo "Dataset access records"
echo "============================================================"

cat > "$ACCESS/chroma_fit.txt" <<'EOF'
CHROMA-FIT is a priority measured-skin-tone dataset.
Locate the official dataset release or request access from the authors.
Do not use unofficial mirrors and do not assume redistribution permission.
EOF

cat > "$ACCESS/ddi.txt" <<'EOF'
Obtain DDI through Stanford AIMI / Redivis.
Preserve the accepted terms, dataset DOI and download receipt.
Do not republish the image files.
EOF

cat > "$ACCESS/ddi2.txt" <<'EOF'
Obtain DDI-2 through the official Stanford dataset portal.
Preserve the accepted terms and download receipt.
Do not republish the image files.
EOF

cat > "$ACCESS/mst_e.txt" <<'EOF'
Obtain MST-E from the official Google Skin Tone site.
Preserve the downloaded license and version metadata.
Do not use third-party mirrors.
EOF

echo "============================================================"
echo "Generate local checksums"
echo "============================================================"

find "$RAW" \
  -type f \
  -not -path '*/.git/*' \
  -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$MANIFESTS/open_metadata_sha256.txt"

find "$RAW" \
  -type f \
  -not -path '*/.git/*' \
  -printf '%s\t%p\n' \
  | sort -n \
  > "$MANIFESTS/open_metadata_inventory.tsv"

echo "COMPLETE"
du -h --max-depth=3 "$RAW" | sort -h
