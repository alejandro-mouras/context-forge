#!/bin/bash
# ─── Transcribe audio/video files via local Whisper server ──────────
#
# Usage:
#   ./transcribe.sh <input-file> [output-dir]
#
# Examples:
#   ./transcribe.sh meeting.m4a
#   ./transcribe.sh demo.mp4 output/
#   WHISPER_LANG=es ./transcribe.sh product-sync.m4a
#
# Environment:
#   WHISPER_HOST     — PC IP or hostname (default: 192.168.1.100)
#   WHISPER_PORT     — Server port (default: 8765)
#   WHISPER_LANG     — Language hint (default: auto-detect)
#   WHISPER_API_KEY  — API key for authentication (required)

set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────
WHISPER_HOST="${WHISPER_HOST:-192.168.1.100}"
WHISPER_PORT="${WHISPER_PORT:-8765}"
WHISPER_LANG="${WHISPER_LANG:-}"
WHISPER_API_KEY="${WHISPER_API_KEY:?Error: WHISPER_API_KEY is not set}"
SERVER_URL="http://${WHISPER_HOST}:${WHISPER_PORT}"

INPUT_FILE="${1:?Usage: $0 <input-file> [output-dir]}"
OUTPUT_DIR="${2:-.}"

# ─── Validation ──────────────────────────────────────────────────────
if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: File not found: $INPUT_FILE"
    exit 1
fi

if ! curl -sf "${SERVER_URL}/health" > /dev/null 2>&1; then
    echo "Error: Whisper server not reachable at ${SERVER_URL}"
    echo "Is the PC on? Is the server running?"
    exit 1
fi

# ─── Transcribe ──────────────────────────────────────────────────────
FILENAME=$(basename "$INPUT_FILE")
BASENAME="${FILENAME%.*}"
DATE=$(date +%Y-%m-%d)
OUTPUT_FILE="${OUTPUT_DIR}/${DATE}-${BASENAME}.md"

mkdir -p "$OUTPUT_DIR"

PARAMS="format=markdown"
if [ -n "$WHISPER_LANG" ]; then
    PARAMS="${PARAMS}&language=${WHISPER_LANG}"
fi

START_TIME=$(date +%s)

curl -s -X POST "${SERVER_URL}/transcribe?${PARAMS}" \
    -H "Authorization: Bearer ${WHISPER_API_KEY}" \
    -F "file=@${INPUT_FILE}" \
    -o "$OUTPUT_FILE"

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo "Done in ${ELAPSED}s"
echo "Saved to: ${OUTPUT_FILE}"
