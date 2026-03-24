# Context Forge — Orchestrator Architecture

## Overview

Context Forge uses a unified 4-step pipeline for ALL inputs:

1. **Pre-processor** (shell script, no LLM) — normalizes any format into clean markdown + extracted images
2. **Classifier** (Claude Code agent, haiku) — quick content categorization to determine extraction depth + output category
3. **Summarizer** (Claude Code agent, opus) — structured extraction + image interpretation, depth guided by category
4. **Structurer** (Python in orchestrator, no LLM) — copies to output directory, updates indexes

Only steps 2 and 3 use LLMs. Uses the Claude Code subscription via CLI (`claude -p`). No API keys or per-token billing.

---

## Pipeline

```
Any input
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  orchestrator.py                                         │
│                                                          │
│  Step 1: Pre-processor (script)                          │
│  ┌────────────────────────────────────────┐              │
│  │ preprocess.sh                          │              │
│  │   audio/video → transcribe.sh (Whisper)│              │
│  │   docx/pptx   → pandoc + zip images   │              │
│  │   markdown    → base64 image extraction│              │
│  │   pdf/odt     → pandoc                 │              │
│  │   images      → wrap as markdown ref   │              │
│  │   txt         → copy                   │              │
│  └────────────────────────────┬───────────┘              │
│                               │                          │
│               processing/normalized/                     │
│               ├── YYYY-MM-DD-file.md                     │
│               └── YYYY-MM-DD-file-images/                │
│                               │                          │
│  Step 2: Classifier (haiku)   ▼                          │
│  ┌────────────────────────────────────────┐              │
│  │ Reads first 500 lines. Determines      │              │
│  │ content_category: technical, product,  │              │
│  │ business, or planning. Fast (1 turn).  │              │
│  └────────────────────────────┬───────────┘              │
│                               │                          │
│              content_category (e.g. "technical")         │
│                               │                          │
│  Step 3: Summarizer (opus)    ▼                          │
│  ┌────────────────────────────────────────┐              │
│  │ Reads markdown + reads images (multi-  │              │
│  │ modal). Extraction depth guided by     │              │
│  │ content_category. Technical = deep,    │              │
│  │ business = compressed. Writes to       │              │
│  │ processing/summarized/                 │              │
│  └────────────────────────────┬───────────┘              │
│                               │                          │
│  Step 4: Structurer (Python)  ▼                          │
│  ┌────────────────────────────────────────┐              │
│  │ Pure Python — no LLM. Copies file to  │              │
│  │ output/{feature}/{category}/. Updates  │              │
│  │ _index.md and _master-index.md. Ex-   │              │
│  │ tracts tags from content.             │              │
│  └────────────────────────────────────────┘              │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Why 2 LLM Agents, Not 4

The original design had 4 LLM agents: Transcriber, Doc Processor, Summarizer, Context Structurer. The principle: **only use LLMs where reasoning is needed**.

- **Transcriber + Doc Processor → Pre-processor script**: Format conversion is mechanical. Calling Whisper or pandoc doesn't need an LLM.
- **Context Structurer → Python function**: File copying and index updates are string manipulation. No LLM reasoning needed. The structurer now runs in ~0s instead of ~2-7 min.
- **Classifier added (haiku)**: A quick, cheap pass that determines content category and output category. Controls summarizer depth. Costs almost nothing (haiku, 1 turn, content injected into prompt).
- **Content injection**: Both classifier and summarizer receive content directly in their prompts instead of wasting turns on Read tool calls.

### Content Categories

| Category | Compression | Preserve | Example Sources |
|----------|-------------|----------|-----------------|
| `technical` | Low (2:1-3:1) | APIs, schemas, state machines, arch decisions, tech debt, risks | Engineering meetings, design docs, technical PRD sections |
| `product` | Medium (4:1-5:1) | Requirements, user stories, acceptance criteria, metrics, flows | Product specs, roadmap reviews, feature discussions |
| `business` | High (8:1-10:1) | Numbers, deals, partnerships, competitive intel | Sales calls, exec summaries, market analysis |
| `planning` | Medium-high (5:1-8:1) | Timelines, milestones, assignments, dependencies, blockers | Sprint planning, retros, milestone reviews |

---

## How Agents Are Invoked

Each agent is a Claude Code instance launched via CLI:

```bash
cd /Users/ciru/Documents/PersonalProyects/context-forge

claude -p "$TASK" \
  --append-system-prompt-file "agents/summarizer/system-prompt.txt" \
  --model opus \
  --max-turns 25 \
  --dangerously-skip-permissions \
  --disallowedTools "Bash" \
  --output-format stream-json \
  --verbose
```

### CLI flags

| Flag | Purpose |
|------|---------|
| `-p "$TASK"` | Headless mode — executes the task and exits |
| `--append-system-prompt-file` | Adds agent role to Claude Code's base system prompt |
| `--model` | Model per agent (haiku for classifier, opus for summarizer) |
| `--max-turns` | Limits the agentic loop |
| `--dangerously-skip-permissions` | Full autonomy without confirmation prompts |
| `--disallowedTools` | Restricts tools by agent role |
| `--output-format stream-json` | Real-time streaming for monitoring |

---

## Agents

### Classifier (haiku) — LLM agent
- **Input**: First 500 lines of normalized markdown (injected into prompt, no Read needed)
- **Does**: Quick content analysis to determine content category (`technical`, `product`, `business`, `planning`) and output category (`documents`, `meetings`, `voice-notes`, `research`). Supports dual categories (primary + secondary).
- **Output**: JSON with `content_category`, `secondary_category`, `output_category`, `confidence`, `reasoning`
- **Tools**: None needed (content injected into prompt)
- **Max turns**: 1

### Summarizer (opus) — LLM agent
- **Input**: Full normalized markdown (injected into prompt) + images from `-images/` directory (read via Read tool) + classification from classifier
- **Does**: Extracts structured information using category-specific depth profile. Technical content gets deep extraction (APIs, schemas, patterns); business content gets high compression. Dual categories apply secondary depth to matching sections.
- **Output**: Structured markdown in `processing/summarized/`
- **Tools**: Read (images only), Write, Glob, Grep (no Bash)
- **Max turns**: 25

### Structurer — Pure Python (no LLM)
- **Input**: Summarized markdown from `processing/summarized/` + `output_category` from classifier
- **Does**: Copies file to `output/{feature}/{category}/` with slugified filename, extracts tags from content, updates `_index.md` and `_master-index.md` with timestamp
- **Output**: Final markdown in `output/{feature}/{category}/` with updated indexes
- **Implementation**: `structure_output()` in `orchestrator.py`

---

## Scripts

| Script | Called by | Dependencies | Purpose |
|--------|-----------|--------------|---------|
| `preprocess.sh` | orchestrator.py | python3 (for base64 extraction) | Unified pre-processor — routes all input types |
| `transcribe.sh` | preprocess.sh | curl, Whisper server | Sends audio/video to local Whisper server |
| `extract-doc.sh` | preprocess.sh | pandoc 3.x | Converts DOCX/PDF/PPTX to markdown via pandoc |

---

## Feature Profiles

Each project defines a `features/{name}.yaml` that the orchestrator passes to agents:

```yaml
name: my-project
description: "Short description of the project"
tags:
  COMP1: "Component One — what it does"
  COMP2: "Component Two — what it does"
terminology:
  COMP1: "Full Name of Component One"
  API: "Application Programming Interface"
  # ...
output_categories:
  meetings: "Call transcripts, meeting notes, standups"
  documents: "PRDs, specs, design docs, reports"
  # ...
extraction_hints:
  - "Decisions about architecture or component design"
  - "Action items with owner and deadline"
  # ...
```

---

## Data Flow

```
input/text/project-spec.md
    │
    ▼ (preprocess.sh — extracts base64 images)
processing/normalized/2026-03-23-project-spec.md
processing/normalized/2026-03-23-project-spec-images/
    ├── image1.png (architecture diagram)
    ├── image2.png (flow chart)
    │
    ▼ (classifier — reads first 500 lines, determines category)
    content_category: "technical"
    │
    ▼ (summarizer — reads text + images, uses "technical" depth profile)
processing/summarized/2026-03-23-project-spec.md
    │
    ▼ (structurer — Python, copies and indexes)
output/{feature}/documents/2026-03-23-project-spec.md
output/{feature}/documents/_index.md  (updated)
output/{feature}/_master-index.md     (updated)
```

---

## Processing Tracker

`processing/processed.log` — TSV format:
```
2026-03-23T14:30:00	/absolute/path/to/file.md	sha256hash
```

- Files identified by path + SHA-256 hash
- Modified files (different hash) are reprocessed
- `--force` bypasses the check
- Append-only log

---

## Image Handling

Images are extracted by the pre-processor and interpreted by the summarizer:

1. **Pre-processor extracts images**: From docx/pptx zips, from markdown base64 data, or from direct image inputs (png/jpg/svg)
2. **Summarizer reads images**: Using Claude's multimodal Read tool (PNG/JPG files)
3. **Summarizer writes text descriptions**: Inline in the structured markdown output
4. **Images stay in `processing/`**: They never reach `output/`

The final output is 100% text — portable, copyable, and consumable by any LLM.

---

## Environment

```bash
# .env — Whisper server config (only needed for audio/video inputs)
WHISPER_HOST=192.168.2.47
WHISPER_PORT=8765
WHISPER_API_KEY=<key>
WHISPER_LANG=en
```

---

## Next Steps

1. Tune summarizer extraction profiles based on real output quality per category
2. Test classifier with diverse content types (business calls, planning sessions)
