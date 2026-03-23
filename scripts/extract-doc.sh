#!/bin/bash
# ─── Extract text and images from documents ─────────────────────────
#
# Usage:
#   ./extract-doc.sh <input-file> [output-dir]
#
# Examples:
#   ./extract-doc.sh document.docx
#   ./extract-doc.sh presentation.pptx processing/extracted/
#
# Output:
#   - {output-dir}/YYYY-MM-DD-{basename}.md     (extracted text)
#   - {output-dir}/YYYY-MM-DD-{basename}-images/ (extracted images, if any)
#
# Supported formats: docx, pdf, pptx, odt, rtf, epub, html
# Requires: pandoc (brew install pandoc)

set -euo pipefail

INPUT_FILE="${1:?Usage: $0 <input-file> [output-dir]}"
OUTPUT_DIR="${2:-.}"

# ─── Validation ──────────────────────────────────────────────────────
if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: File not found: $INPUT_FILE"
    exit 1
fi

if ! command -v pandoc &> /dev/null; then
    echo "Error: pandoc is not installed. Run: brew install pandoc"
    exit 1
fi

# ─── Setup ───────────────────────────────────────────────────────────
FILENAME=$(basename "$INPUT_FILE")
BASENAME="${FILENAME%.*}"
EXTENSION="${FILENAME##*.}"
DATE=$(date +%Y-%m-%d)
OUTPUT_FILE="${OUTPUT_DIR}/${DATE}-${BASENAME}.md"
IMAGES_DIR="${OUTPUT_DIR}/${DATE}-${BASENAME}-images"

mkdir -p "$OUTPUT_DIR"

START_TIME=$(date +%s)

# ─── Extract text via pandoc ─────────────────────────────────────────
pandoc "$INPUT_FILE" -t markdown --wrap=none -o "$OUTPUT_FILE"

# ─── Extract images from docx/pptx (they're zip files) ──────────────
IMAGE_COUNT=0
EXTENSION_LOWER=$(echo "$EXTENSION" | tr '[:upper:]' '[:lower:]')

if [[ "$EXTENSION_LOWER" == "docx" || "$EXTENSION_LOWER" == "pptx" ]]; then
    TEMP_DIR=$(mktemp -d)
    unzip -q "$INPUT_FILE" -d "$TEMP_DIR" 2>/dev/null || true

    # docx stores images in word/media/, pptx in ppt/media/
    MEDIA_DIR=""
    if [ -d "$TEMP_DIR/word/media" ]; then
        MEDIA_DIR="$TEMP_DIR/word/media"
    elif [ -d "$TEMP_DIR/ppt/media" ]; then
        MEDIA_DIR="$TEMP_DIR/ppt/media"
    fi

    if [ -n "$MEDIA_DIR" ] && [ "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ]; then
        mkdir -p "$IMAGES_DIR"
        cp "$MEDIA_DIR"/* "$IMAGES_DIR/"
        IMAGE_COUNT=$(ls -1 "$IMAGES_DIR" | wc -l | tr -d ' ')
    fi

    rm -rf "$TEMP_DIR"
fi

# ─── Report ──────────────────────────────────────────────────────────
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
FILE_SIZE=$(wc -c < "$OUTPUT_FILE" | tr -d ' ')

echo "Done in ${ELAPSED}s"
echo "Text: ${OUTPUT_FILE} (${FILE_SIZE} bytes)"
if [ "$IMAGE_COUNT" -gt 0 ]; then
    echo "Images: ${IMAGES_DIR}/ (${IMAGE_COUNT} files)"
else
    echo "Images: none"
fi
