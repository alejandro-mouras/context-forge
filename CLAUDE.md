# Context Forge

## What This Is

Orchestrator-driven pipeline that transforms audio, video, documents, and text into structured markdown context. Uses a unified 4-step pipeline: pre-process (script) → classify (agent) → summarize (agent) → structure (agent).

Not tied to any specific project. Each project defines a feature profile in `features/`.

## Architecture

See `orchestrator-architecture.md` for full details.

### Unified Pipeline

```
Any input → Pre-processor (script) → Classifier (haiku agent) → Summarizer (opus agent) → Context Structurer (sonnet agent)
```

- **Pre-processor**: A shell script (no LLM). Normalizes any input format into clean markdown + extracted images. Routes by file extension: audio/video → Whisper, docx/pptx → pandoc + zip image extraction, markdown → base64 image extraction, pdf/odt → pandoc, txt → copy.
- **Classifier**: Haiku agent (1 turn, fast). Reads the first 500 lines of normalized content and determines the content category: `technical`, `product`, `business`, or `planning`. This category controls the summarizer's extraction depth.
- **Summarizer**: Opus agent. Reads normalized markdown + interprets images as structured text. Extraction depth varies by content category — technical content gets near-verbatim preservation of APIs, schemas, and architecture; business content gets high compression focused on numbers and decisions.
- **Context Structurer**: Sonnet agent. Categorizes output, writes to `output/{feature}/{category}/`, updates indexes.

All agents are invoked via `claude -p` CLI (subscription, not API).

### Content Categories (Classifier → Summarizer)

| Category | Compression | What Gets Preserved |
|----------|-------------|---------------------|
| `technical` | Low (2:1-3:1) | APIs, schemas, endpoints, state machines, patterns, architecture decisions, tech debt, risks, acceptance criteria |
| `product` | Medium (4:1-5:1) | Requirements, user stories, metrics, success criteria, scope, flows |
| `business` | High (8:1-10:1) | Numbers, deals, partnerships, competitive intel, market data |
| `planning` | Medium-high (5:1-8:1) | Timelines, milestones, assignments, dependencies, blockers |

## Directory Structure

```
context-forge/
├── orchestrator.py          # Pipeline logic — pre-process → classify → summarize → structure
├── config.yaml              # Global config (active feature, supported extensions) — not committed
├── config.yaml.example      # Template for config.yaml
├── agents/                  # Agent definitions (3 agents)
│   ├── classifier/          # Quick content categorization (haiku)
│   ├── summarizer/          # Text extraction + image interpretation (opus)
│   └── context-structurer/  # Categorize, index, cross-reference (sonnet)
├── features/                # Feature profiles — not committed (see features/README.md)
├── scripts/                 # Utility scripts
│   ├── preprocess.sh        # Unified pre-processor (routes all input types)
│   ├── transcribe.sh        # Whisper API client (called by preprocess.sh)
│   ├── extract-doc.sh       # Pandoc extraction (called by preprocess.sh)
│   ├── watch-input.sh       # File watcher (placeholder)
│   └── sync-to-consumer.sh  # Output sync (placeholder)
├── input/                   # Drop zone (audio/, video/, docs/, text/)
├── processing/              # Intermediates (normalized/, summarized/, processed.log)
├── output/                  # Final output by feature — not committed
├── init.sh                  # Project initialization script
├── .venv/                   # Python virtual environment
├── .env                     # Environment variables — not committed
└── .env.example
```

## Setup

```bash
brew install pandoc    # if not already installed
chmod +x init.sh && ./init.sh
```

`init.sh` handles: dependency checks, venv creation, PyYAML install, .env and config.yaml setup, directory creation, script permissions.

## Running the Pipeline

```bash
source .venv/bin/activate

# Process a single file
python orchestrator.py input/text/document.md

# Process all new files in input/
python orchestrator.py --scan

# Reprocess everything (ignore processed.log)
python orchestrator.py --scan --force

# Resume from a specific step (skip pre-processing)
python orchestrator.py --from-step classify processing/normalized/file.md
python orchestrator.py --from-step summarize processing/normalized/file.md
python orchestrator.py --from-step structure processing/summarized/file.md
```

### `--from-step` flag

Allows resuming the pipeline from any step. Useful when:
- Pre-processing already ran (e.g., Whisper transcription took 5 min, don't repeat it)
- An agent failed mid-pipeline and you want to retry from that step
- You want to re-summarize with a different feature profile without re-preprocessing

Valid steps: `classify`, `summarize`, `structure`. Input file must be from the corresponding `processing/` directory.

## Processing Tracker

The orchestrator tracks processed files in `processing/processed.log` (TSV: timestamp, path, SHA-256 hash).

- `--scan` skips files already processed (same path + same hash)
- Modified files (hash changes) are reprocessed automatically
- `--force` bypasses the check and reprocesses everything

## Current State

**Implemented**:
- `orchestrator.py` — unified 4-step pipeline, processing tracker
- `scripts/preprocess.sh` — routes all input types, extracts base64 images from markdown, extracts images from docx/pptx zips
- `scripts/transcribe.sh` — Whisper API client (called by preprocess.sh for audio/video)
- `scripts/extract-doc.sh` — pandoc extraction (called by preprocess.sh for docs)
- All agent configs and system prompts (classifier, summarizer, context-structurer)

**Placeholders**: `watch-input.sh`, `sync-to-consumer.sh`.

**Tested end-to-end**: Document pipeline (PRD markdown with images) and audio pipeline (65min meeting via Whisper) — both working.

## Dependencies

| Dependency | Required by | Install |
|------------|-------------|---------|
| Python 3.10+ | orchestrator.py | Pre-installed on macOS |
| PyYAML | orchestrator.py | Auto-installed by init.sh |
| pandoc 3.x | preprocess.sh (docs) | `brew install pandoc` |
| curl | preprocess.sh (audio/video) | Pre-installed on macOS |
| Claude Code CLI | all agents | Subscription required |
| Whisper server | preprocess.sh (audio/video) | Running on network PC |

## Key Behaviors

- **Unified pipeline**: ALL inputs go through the same 4 steps. No branching pipelines.
- **Pre-processor is a script, not an agent**: Format conversion is mechanical — no LLM needed.
- **Category-driven extraction depth**: The classifier determines how deep the summarizer goes (supports primary + secondary categories). Technical content preserved near-verbatim; business content heavily compressed.
- **Content injection**: The summarizer receives the full source content directly in its task prompt (between `--- FULL CONTENT ---` markers), avoiding extra Read turns. Images are still read via the Read tool.
- **Real-time progress**: The orchestrator streams agent tool calls to stdout with timestamps (`[12s] Using: Read`), so you always know what's happening.
- **Image interpretation**: The summarizer reads extracted images (PNG files) via Claude's multimodal capabilities and describes diagrams as structured text. Images stay in `processing/` — only text reaches the final output.
- **Text-only output**: 100% portable markdown. No images, no binary files. Output is consumed as LLM context in other projects.
- **Processing deduplication**: Files tracked by path + SHA-256 hash.
- **Google Drive markdown preferred**: For Google Docs, export as .md and drop in `input/text/`. Cleaner than .docx.

## Key Design Decisions

- **Unified pipeline over branching**: One flow for all inputs.
- **3 agents**: Classifier (haiku, cheap), Summarizer (opus, deep), Context Structurer (sonnet, indexing).
- **CLI over SDK**: Uses Claude Code subscription, not API. No per-token billing.
- **Feature profiles**: Each project has a yaml in `features/`. Not committed — project-specific.
- **Output namespaced by feature**: `output/{feature}/meetings/`, not flat.
- **All output in English**, original terms preserved in [brackets].

## What Needs To Be Done

1. Tune agent system prompts based on real output quality
2. Implement remaining scripts (`watch-input.sh`, `sync-to-consumer.sh`)
3. Test classifier agent with different content types

## Architecture Reference

Full architecture doc: `orchestrator-architecture.md`

## Security Rules

Claude Code operates under strict safety constraints in this project via `.claude/settings.json` and hooks:

**Hard blocks (no override)**:
- No file modifications outside the project directory
- No destructive commands (`rm -rf`, `sudo`, `kill`, `dd`, `mkfs`, etc.)
- No force push or hard reset (`git push --force`, `git reset --hard`)
- No system modification (`brew`, `launchctl`, `defaults write`, `osascript`, etc.)
- No package installation outside the venv (`pip install`, `npm install -g`, etc.)
- No reading secrets (`~/.ssh`, `~/.aws`, `~/.gnupg`, `.env`)
- No piping to shell (`curl ... | bash`)
