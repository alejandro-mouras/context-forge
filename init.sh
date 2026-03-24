#!/bin/bash
# ─── Context Forge — Project Initialization ─────────────────────────
#
# Run this once after cloning the repo:
#   chmod +x init.sh && ./init.sh
#
# What it does:
#   1. Checks system dependencies (python3, pandoc, curl, claude)
#   2. Creates Python venv and installs packages
#   3. Creates .env from .env.example (if not exists)
#   4. Creates input/output/processing directory structure
#   5. Makes all scripts executable
#   6. Verifies everything is ready

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════"
echo "  Context Forge — Initialization"
echo "═══════════════════════════════════════════════"
echo ""

# ─── 1. Check system dependencies ───────────────────────────────────
echo "Checking dependencies..."

MISSING=0

if command -v python3 &> /dev/null; then
    ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"
else
    fail "python3 not found"
    MISSING=1
fi

if command -v pandoc &> /dev/null; then
    ok "pandoc $(pandoc --version | head -1 | cut -d' ' -f2)"
else
    fail "pandoc not found — install with: brew install pandoc"
    MISSING=1
fi

if command -v curl &> /dev/null; then
    ok "curl available"
else
    fail "curl not found"
    MISSING=1
fi

if command -v claude &> /dev/null; then
    ok "claude CLI available"
else
    warn "claude CLI not found — needed to run the pipeline agents"
fi

if [ "$MISSING" -eq 1 ]; then
    echo ""
    fail "Missing required dependencies. Install them and re-run."
    exit 1
fi

# ─── 2. Python venv ─────────────────────────────────────────────────
echo ""
echo "Setting up Python environment..."

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    ok "Created .venv"
else
    ok ".venv already exists"
fi

source .venv/bin/activate

if python3 -c "import yaml" 2>/dev/null; then
    ok "PyYAML installed"
else
    pip install -q pyyaml
    ok "Installed PyYAML"
fi

# ─── 3. Configuration files ──────────────────────────────────────────
echo ""
echo "Configuring environment..."

if [ ! -f ".env" ]; then
    cp .env.example .env
    warn "Created .env from .env.example — edit it with your Whisper server values"
else
    ok ".env already exists"
fi

if [ ! -f "config.yaml" ]; then
    cp config.yaml.example config.yaml
    warn "Created config.yaml from template — set active_feature to your feature name"
else
    ok "config.yaml already exists"
fi

# ─── 4. Directory structure ─────────────────────────────────────────
echo ""
echo "Creating directory structure..."

dirs=(
    "input/audio"
    "input/video"
    "input/docs"
    "input/text"
    "input/images"
    "processing/normalized"
    "processing/summarized"
    "output"
)

for dir in "${dirs[@]}"; do
    mkdir -p "$dir"
done
ok "All directories created"

# ─── 5. Script permissions ──────────────────────────────────────────
echo ""
echo "Setting script permissions..."

chmod +x scripts/*.sh 2>/dev/null || true
ok "All scripts are executable"

# ─── 6. Verify ──────────────────────────────────────────────────────
echo ""
echo "Verifying orchestrator..."

if .venv/bin/python -c "import orchestrator" 2>/dev/null; then
    ok "orchestrator.py loads successfully"
else
    fail "orchestrator.py failed to load"
    exit 1
fi

# ─── Done ────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo -e "  ${GREEN}Ready!${NC}"
echo "═══════════════════════════════════════════════"
echo ""
echo "  Activate the venv:  source .venv/bin/activate"
echo "  Run the pipeline:   python orchestrator.py --scan"
echo "  Or a single file:   python orchestrator.py input/text/file.md"
echo ""
echo "  Don't forget to edit .env with your Whisper server config"
echo "  if you plan to process audio/video files."
echo ""
