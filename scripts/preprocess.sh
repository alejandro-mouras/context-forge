#!/bin/bash
# ─── Pre-processor: Normalize any input into clean markdown + images ─
#
# Usage:
#   ./preprocess.sh <input-file> [output-dir]
#
# Handles all input types:
#   Audio/Video → transcribe via Whisper server → markdown transcript
#   DOCX/PPTX  → extract text via pandoc + images from zip → markdown + images/
#   Markdown    → extract base64 images to files, clean references → markdown + images/
#   PDF/ODT/RTF → extract text via pandoc → markdown
#   Images      → wrap in markdown with image reference → markdown + images/
#   Plain text  → copy as-is → markdown
#
# Input filenames MUST start with YYYYMMDD_ prefix (e.g., 20260321_Silver PRD.md)
#
# Output:
#   {output-dir}/YYYY-MM-DD-{name}.md        (date from filename prefix)
#   {output-dir}/YYYY-MM-DD-{name}-images/   (if images found)
#
# Dependencies: pandoc (brew install pandoc), curl (for Whisper)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi
INPUT_FILE="${1:?Usage: $0 <input-file> [output-dir]}"
OUTPUT_DIR="${2:-processing/normalized}"

# ─── Validation ──────────────────────────────────────────────────────
if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: File not found: $INPUT_FILE"
    exit 1
fi

FILENAME=$(basename "$INPUT_FILE")
BASENAME="${FILENAME%.*}"
EXTENSION="${FILENAME##*.}"
EXTENSION_LOWER=$(echo "$EXTENSION" | tr '[:upper:]' '[:lower:]')

# ─── Validate YYYYMMDD_ prefix ─────────────────────────────────────
if [[ "$BASENAME" =~ ^([0-9]{8})_(.*) ]]; then
    DATE_RAW="${BASH_REMATCH[1]}"
    NAME_PART="${BASH_REMATCH[2]}"
    # Convert YYYYMMDD to YYYY-MM-DD
    DATE="${DATE_RAW:0:4}-${DATE_RAW:4:2}-${DATE_RAW:6:2}"
else
    echo "Error: Input filename must start with YYYYMMDD_ prefix"
    echo "  Got: $FILENAME"
    echo "  Expected: YYYYMMDD_description.ext (e.g., 20260321_my-document.md)"
    exit 1
fi

OUTPUT_FILE="${OUTPUT_DIR}/${DATE}-${NAME_PART}.md"
IMAGES_DIR="${OUTPUT_DIR}/${DATE}-${NAME_PART}-images"

mkdir -p "$OUTPUT_DIR"

START_TIME=$(date +%s)

# ─── Route by type ───────────────────────────────────────────────────

case "$EXTENSION_LOWER" in
    # Audio/Video → Whisper transcription
    mp3|wav|m4a|ogg|flac|wma|aac|opus|mp4|mov|webm|mkv|avi)
        echo "Type: audio/video → Whisper transcription"
        "$SCRIPT_DIR/transcribe.sh" "$INPUT_FILE" "$OUTPUT_DIR"
        # transcribe.sh names output as YYYY-MM-DD-{basename}.md, matches our convention
        ;;

    # DOCX/PPTX → pandoc text + zip image extraction
    docx|pptx)
        echo "Type: document (${EXTENSION_LOWER}) → pandoc + image extraction"
        if ! command -v pandoc &> /dev/null; then
            echo "Error: pandoc is not installed. Run: brew install pandoc"
            exit 1
        fi
        pandoc "$INPUT_FILE" -t markdown --wrap=none -o "$OUTPUT_FILE"

        # Extract images from zip structure
        TEMP_DIR=$(mktemp -d)
        unzip -q "$INPUT_FILE" -d "$TEMP_DIR" 2>/dev/null || true
        MEDIA_DIR=""
        if [ -d "$TEMP_DIR/word/media" ]; then
            MEDIA_DIR="$TEMP_DIR/word/media"
        elif [ -d "$TEMP_DIR/ppt/media" ]; then
            MEDIA_DIR="$TEMP_DIR/ppt/media"
        fi
        if [ -n "$MEDIA_DIR" ] && [ "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ]; then
            mkdir -p "$IMAGES_DIR"
            cp "$MEDIA_DIR"/* "$IMAGES_DIR/"
        fi
        rm -rf "$TEMP_DIR"
        ;;

    # PDF/ODT/RTF/EPUB/HTML → pandoc text only
    pdf|odt|rtf|epub|html)
        echo "Type: document (${EXTENSION_LOWER}) → pandoc"
        if ! command -v pandoc &> /dev/null; then
            echo "Error: pandoc is not installed. Run: brew install pandoc"
            exit 1
        fi
        pandoc "$INPUT_FILE" -t markdown --wrap=none -o "$OUTPUT_FILE"
        ;;

    # Markdown → extract base64 images, clean references
    md)
        echo "Type: markdown → base64 image extraction"
        # Extract base64 images and replace with file references
        python3 - "$INPUT_FILE" "$OUTPUT_FILE" "$IMAGES_DIR" << 'PYEOF'
import re, base64, sys, os
from pathlib import Path

input_file = sys.argv[1]
output_file = sys.argv[2]
images_dir = sys.argv[3]

with open(input_file, 'r') as f:
    content = f.read()

# Match reference-style image definitions: [imageN]: <data:image/png;base64,...>
pattern = r'\[([^\]]+)\]:\s*<data:image/([^;]+);base64,([^>]+)>'
image_count = 0

def replace_image(match):
    global image_count
    image_count += 1
    ref_name = match.group(1)
    img_format = match.group(2)
    img_data = match.group(3)

    os.makedirs(images_dir, exist_ok=True)
    img_filename = f"{ref_name}.{img_format}"
    img_path = os.path.join(images_dir, img_filename)

    with open(img_path, 'wb') as f:
        f.write(base64.b64decode(img_data))

    return f'[{ref_name}]: {img_path}'

cleaned = re.sub(pattern, replace_image, content)

with open(output_file, 'w') as f:
    f.write(cleaned)

print(f"Extracted {image_count} base64 image(s)")
PYEOF
        ;;

    # Images → wrap in markdown with image reference (for diagrams, flowcharts, etc.)
    png|jpg|jpeg|svg)
        echo "Type: image → wrap as markdown"
        mkdir -p "$IMAGES_DIR"
        cp "$INPUT_FILE" "$IMAGES_DIR/${FILENAME}"
        cat > "$OUTPUT_FILE" << EOF
# Diagram: ${NAME_PART}

![${NAME_PART}](${IMAGES_DIR}/${FILENAME})
EOF
        ;;

    # Plain text → copy as markdown
    txt)
        echo "Type: plain text → copy"
        cp "$INPUT_FILE" "$OUTPUT_FILE"
        ;;

    *)
        echo "Error: Unsupported file type: .${EXTENSION_LOWER}"
        exit 1
        ;;
esac

# ─── Report ──────────────────────────────────────────────────────────
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

if [ -f "$OUTPUT_FILE" ]; then
    FILE_SIZE=$(wc -c < "$OUTPUT_FILE" | tr -d ' ')
    echo "Done in ${ELAPSED}s"
    echo "Text: ${OUTPUT_FILE} (${FILE_SIZE} bytes)"
else
    echo "Done in ${ELAPSED}s"
fi

IMAGE_COUNT=0
if [ -d "$IMAGES_DIR" ] && [ "$(ls -A "$IMAGES_DIR" 2>/dev/null)" ]; then
    IMAGE_COUNT=$(ls -1 "$IMAGES_DIR" | wc -l | tr -d ' ')
    echo "Images: ${IMAGES_DIR}/ (${IMAGE_COUNT} files)"
else
    echo "Images: none"
fi
