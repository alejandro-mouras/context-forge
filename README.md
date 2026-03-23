# Context Forge

Orchestrator-driven pipeline that transforms audio, video, documents, and text into structured markdown context. Uses a unified 4-step pipeline — 2 LLM agents + 2 scripts.

## How It Works

```
Any input (audio/video/docs/text/markdown)
    → Pre-processor (script — no LLM)
        Normalizes to clean markdown + extracted images
    → Classifier Agent (haiku — 1 turn)
        Quick categorization: technical, product, business, or planning
    → Summarizer Agent (opus)
        Structured extraction + image interpretation, depth guided by category
    → Structurer (Python — no LLM)
        Copies to output/{feature}/{category}/, updates indexes
    → Output: structured markdown in output/{feature}/
```

Only the classifier and summarizer use LLM. The rest is scripts and Python.

All inputs follow the same pipeline. The pre-processor routes by file type:

| Input type | Pre-processor action |
|------------|---------------------|
| Audio/Video | Transcribe via Whisper server |
| DOCX/PPTX | Extract text via pandoc + images from zip |
| Markdown | Extract base64 images to files |
| PDF/ODT/RTF | Extract text via pandoc |
| Plain text | Copy as-is |

## Feature Profiles

Context Forge is **not tied to any specific project**. Each project defines a profile in `features/` that configures tags, terminology, and output categories. See `features/README.md` for how to create one.

## Directory Structure

| Directory | Purpose |
|-----------|---------|
| `agents/` | Agent definitions (classifier + summarizer) |
| `features/` | Feature profiles (one yaml per project, not committed) |
| `scripts/` | Pre-processor and utility scripts |
| `input/` | Drop zone for raw files (audio, video, docs, text) |
| `processing/` | Intermediates (normalized, summarized, tracker log) |
| `output/{feature}/` | Final structured markdown, organized by feature |

## Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| **Classifier** | haiku | Quick content categorization (1 turn) — determines extraction depth |
| **Summarizer** | opus | Text extraction + image interpretation → structured markdown |

The structurer step is pure Python in `orchestrator.py` — no LLM needed for file copy and index updates.

## Prerequisites

| Dependency | Required by | Install |
|------------|-------------|---------|
| **Python 3.10+** | orchestrator.py | Pre-installed on macOS |
| **PyYAML** | orchestrator.py | Auto-installed by `init.sh` |
| **pandoc 3.x** | preprocess.sh (docs) | `brew install pandoc` |
| **curl** | preprocess.sh (audio/video) | Pre-installed on macOS |
| **Claude Code CLI** | classifier, summarizer | [Install guide](https://docs.anthropic.com/en/docs/claude-code) |
| **Whisper server** | preprocess.sh (audio/video) | Running on network PC ([details](.env.example)) |

## Setup

```bash
# 1. Install pandoc (if not already installed)
brew install pandoc

# 2. Run the init script (creates venv, installs deps, sets up directories)
chmod +x init.sh && ./init.sh

# 3. Edit .env with your Whisper server values (for audio/video processing)
nano .env

# 4. Run the pipeline
source .venv/bin/activate
python orchestrator.py input/text/file.md          # process a single file
python orchestrator.py --scan                       # process all new files in input/
python orchestrator.py --scan --force               # reprocess everything

# Resume from a specific pipeline step (skip pre-processing)
python orchestrator.py --from-step classify processing/normalized/file.md
python orchestrator.py --from-step summarize processing/normalized/file.md
python orchestrator.py --from-step structure processing/summarized/file.md
```

## Processing Tracker

The orchestrator tracks processed files in `processing/processed.log` to avoid reprocessing. Files are identified by path + SHA-256 hash — modified files are reprocessed automatically. Use `--force` to bypass.

## Architecture

See [orchestrator-architecture.md](orchestrator-architecture.md) for the full design — pipeline, agents, CLI flags, data flow, content categories, and image handling.
