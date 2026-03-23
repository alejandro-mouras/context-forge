# Context Forge — Orchestrator Architecture

## Overview

Context Forge uses a unified 4-step pipeline for ALL inputs:

1. **Pre-processor** (shell script, no LLM) — normalizes any format into clean markdown + extracted images
2. **Classifier** (Claude Code agent, haiku) — quick content categorization to determine extraction depth
3. **Summarizer** (Claude Code agent, opus) — structured extraction + image interpretation, depth guided by category
4. **Context Structurer** (Claude Code agent, sonnet) — categorizes and indexes into final output

Uses the Claude Code subscription via CLI (`claude -p`). No API keys or per-token billing.

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
│  Step 4: Context Structurer   ▼  (sonnet)                │
│  ┌────────────────────────────────────────┐              │
│  │ Categorizes by feature profile. Writes │              │
│  │ to output/{feature}/{category}/. Up-   │              │
│  │ dates _index.md and _master-index.md   │              │
│  └────────────────────────────────────────┘              │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Why 3 Agents, Not 4

The original design had 4 agents: Transcriber, Doc Processor, Summarizer, Context Structurer. This was simplified, then a classifier was added:

- **Transcriber + Doc Processor → Pre-processor script**: Format conversion is mechanical. Calling Whisper or pandoc doesn't need an LLM. A shell script is faster, cheaper, and more reliable.
- **Classifier added (haiku)**: A quick, cheap pass that reads the first 500 lines and determines the content category. This controls how deep the summarizer goes — technical content gets near-verbatim extraction while business content gets heavy compression. Costs almost nothing (haiku, 1 turn).
- **Summarizer now handles image interpretation**: Since it's already an opus agent reading content, adding image interpretation (via Claude's multimodal capabilities) is natural.
- **Single pipeline for all inputs**: No branching logic in the orchestrator. The classifier + category-specific prompts handle depth differences.

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
| `--model` | Model per agent (opus for summarizer, sonnet for structurer) |
| `--max-turns` | Limits the agentic loop |
| `--dangerously-skip-permissions` | Full autonomy without confirmation prompts |
| `--disallowedTools` | Restricts tools by agent role |
| `--output-format stream-json` | Real-time streaming for monitoring |

---

## Agents

### Classifier (haiku)
- **Input**: Normalized markdown from `processing/normalized/` (first 500 lines)
- **Does**: Quick content analysis to determine content category (`technical`, `product`, `business`, `planning`)
- **Output**: JSON with `content_category`, `confidence`, `reasoning`
- **Tools**: Read only (no Write, Edit, Bash)
- **Max turns**: 1

### Summarizer (opus)
- **Input**: Normalized markdown from `processing/normalized/` + images from `-images/` directory + `content_category` from classifier
- **Does**: Reads text, reads images (multimodal), extracts structured information using category-specific depth profile. Technical content gets deep extraction (APIs, schemas, patterns); business content gets high compression.
- **Output**: Structured markdown in `processing/summarized/`
- **Tools**: Read, Write, Glob, Grep (no Bash)
- **Max turns**: 25

### Context Structurer (sonnet)
- **Input**: Summarized markdown from `processing/summarized/`
- **Does**: Categorizes by feature profile, writes to output, updates indexes
- **Output**: Final markdown in `output/{feature}/{category}/` with updated `_index.md` and `_master-index.md`
- **Tools**: Read, Write, Glob, Grep (no Bash)
- **Max turns**: 15

---

## Scripts

| Script | Called by | Dependencies | Purpose |
|--------|-----------|--------------|---------|
| `preprocess.sh` | orchestrator.py | python3 (for base64 extraction) | Unified pre-processor — routes all input types |
| `transcribe.sh` | preprocess.sh | curl, Whisper server | Sends audio/video to local Whisper server |
| `extract-doc.sh` | preprocess.sh | pandoc 3.x | Converts DOCX/PDF/PPTX to markdown via pandoc |
| `watch-input.sh` | — | — | Placeholder: watches `input/` for new files |
| `sync-to-consumer.sh` | — | — | Placeholder: syncs `output/` to downstream apps |

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
    ▼ (context-structurer — categorizes and indexes)
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

1. **Pre-processor extracts images**: From docx/pptx zips or from markdown base64 data
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

1. Test end-to-end pipeline run with classifier step
2. Tune summarizer extraction profiles based on real output quality per category
3. Implement `watch-input.sh` and `sync-to-consumer.sh`
