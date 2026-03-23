#!/usr/bin/env python3
"""Context Forge Orchestrator — Unified pipeline: Pre-process → Classify → Summarize → Structure."""

import hashlib
import json
import os
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"
PROCESSED_LOG = ROOT / "processing" / "processed.log"
NORMALIZED_DIR = ROOT / "processing" / "normalized"
SUMMARIZED_DIR = ROOT / "processing" / "summarized"


# ─── Environment & Config ───────────────────────────────────────────

def load_env():
    """Load .env file into environment."""
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def load_config():
    """Load global config.yaml."""
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def load_feature(config):
    """Load the active feature profile."""
    feature_name = config["active_feature"]
    feature_path = ROOT / "features" / f"{feature_name}.yaml"
    with open(feature_path) as f:
        return yaml.safe_load(f)


def load_agent_config(agent_name):
    """Load an agent's config.yaml."""
    agent_path = ROOT / "agents" / agent_name / "config.yaml"
    with open(agent_path) as f:
        return yaml.safe_load(f)


# ─── Processing Tracker ─────────────────────────────────────────────

def file_hash(file_path):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_processed_log():
    """Load the processed files log. Returns dict of {path: hash}."""
    if not PROCESSED_LOG.exists():
        return {}
    entries = {}
    with open(PROCESSED_LOG) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    entries[parts[1]] = parts[2]
    return entries


def mark_processed(file_path):
    """Append a file to the processed log."""
    PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
    h = file_hash(file_path)
    timestamp = datetime.now().isoformat()
    with open(PROCESSED_LOG, "a") as f:
        f.write(f"{timestamp}\t{file_path}\t{h}\n")


def is_already_processed(file_path):
    """Check if a file has already been processed (same path and hash)."""
    log = load_processed_log()
    resolved = str(Path(file_path).resolve())
    if resolved not in log:
        return False
    return log[resolved] == file_hash(file_path)


# ─── Pre-processor (script, no LLM) ─────────────────────────────────

def preprocess(input_file):
    """Run preprocess.sh to normalize any input into markdown + images."""
    print(f"\n{'='*60}")
    print(f"  Pre-processor (script)")
    print(f"  Input: {input_file}")
    print(f"{'='*60}\n")

    result = subprocess.run(
        ["scripts/preprocess.sh", str(input_file), str(NORMALIZED_DIR)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=1800,  # 30 min — audio transcription can be slow
    )

    if result.returncode != 0:
        print(f"[ERROR] Pre-processor failed (exit {result.returncode})")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        return None

    print(result.stdout.strip())

    # Find the output file
    basename = Path(input_file).stem
    output_file = find_output_file(NORMALIZED_DIR, basename)
    if output_file:
        print(f"  → Normalized: {output_file}")
    return output_file


# ─── Agent Runner ────────────────────────────────────────────────────

def read_file_content(file_path, max_lines=None):
    """Read file content, optionally limited to first N lines."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        if max_lines:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
            return "".join(lines)
        return f.read()


def build_task_prompt(agent_name, input_file, feature, content_category=None):
    """Build the task prompt for an agent."""
    feature_context = yaml.dump(feature, default_flow_style=False)
    basename = Path(input_file).stem
    images_dir = Path(input_file).parent / f"{basename}-images"

    if agent_name == "classifier":
        # Inject first 500 lines directly — saves the agent from needing a Read turn
        preview = read_file_content(input_file, max_lines=500)
        return (
            f"Classify the following content and output a JSON object with "
            f"content_category, confidence, and reasoning.\n\n"
            f"Feature profile (for context on the domain):\n```yaml\n{feature_context}```\n\n"
            f"--- CONTENT (first 500 lines) ---\n{preview}\n--- END CONTENT ---"
        )

    if agent_name == "summarizer":
        # Inject full file content directly — saves 3-4 Read turns on large files
        content = read_file_content(input_file)
        content_size = len(content)
        print(f"  Injecting {content_size:,} chars into summarizer prompt")

        images_note = ""
        if images_dir.exists() and any(images_dir.iterdir()):
            image_files = sorted(images_dir.iterdir())
            images_note = (
                f"\n\nIMPORTANT: This file has {len(image_files)} associated image(s) at:\n"
                f"  {images_dir}/\n"
                f"Read each image with the Read tool and interpret them as structured text "
                f"descriptions inline in your output (see your system prompt for format).\n"
                f"Images: {', '.join(f.name for f in image_files)}"
            )

        category_note = ""
        if content_category:
            category_note = (
                f"\n\nCONTENT CATEGORY: {content_category}\n"
                f"Use the '{content_category}' extraction profile from your system prompt. "
                f"Follow that profile's structure and depth guidelines exactly."
            )

        return (
            f"Extract structured information from the content below and write the result "
            f"to {SUMMARIZED_DIR}/{Path(input_file).name}\n\n"
            f"Feature profile:\n```yaml\n{feature_context}```"
            f"{category_note}"
            f"{images_note}\n\n"
            f"--- FULL CONTENT ---\n{content}\n--- END CONTENT ---"
        )

    if agent_name == "context-structurer":
        feature_name = feature["name"]
        return (
            f"Structure this file into final output: {input_file}\n\n"
            f"Feature profile:\n```yaml\n{feature_context}```\n\n"
            f"Read the file, categorize it, write it to output/{feature_name}/<category>/, "
            f"and update the category _index.md and _master-index.md."
        )

    return f"Process: {input_file}"



# Per-agent timeout in seconds
AGENT_TIMEOUTS = {
    "classifier": 120,       # haiku, 1 turn — should be very fast
    "summarizer": 1800,      # opus, large docs with images — up to 30 min
    "context-structurer": 300,  # sonnet, indexing — 5 min
}


def run_agent(agent_name, task, config):
    """Launch a Claude Code instance for an agent."""
    agent_config = load_agent_config(agent_name)
    defaults = config.get("agent_defaults", {})

    model = agent_config.get("model", "sonnet")
    max_turns = agent_config.get("max_turns", defaults.get("max_turns", 10))
    permission_mode = agent_config.get("permission_mode", defaults.get("permission_mode", "dangerously-skip"))
    disallowed = agent_config.get("disallowed_tools", [])
    timeout = AGENT_TIMEOUTS.get(agent_name, 600)

    system_prompt_file = ROOT / "agents" / agent_name / "system-prompt.txt"

    cmd = [
        "claude", "-p", task,
        "--append-system-prompt-file", str(system_prompt_file),
        "--model", model,
        "--max-turns", str(max_turns),
    ]

    if permission_mode == "dangerously-skip":
        cmd.append("--dangerously-skip-permissions")

    for tool in disallowed:
        cmd.extend(["--disallowedTools", tool])

    cmd.extend(["--output-format", "stream-json", "--verbose"])

    print(f"\n{'='*60}")
    print(f"  Agent: {agent_name} ({model})")
    print(f"  Max turns: {max_turns} | Timeout: {timeout}s")
    print(f"{'='*60}\n")

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        print(f"[ERROR] {agent_name} failed (exit {result.returncode})")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        return None

    # Parse stream-json output — extract last assistant text
    # Check both "assistant" message blocks and "result" type events
    output_text = ""
    for line in result.stdout.strip().split("\n"):
        try:
            event = json.loads(line)
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        output_text = block["text"]
            elif event.get("type") == "result":
                text = event.get("result", "")
                if text:
                    output_text = text
        except (json.JSONDecodeError, KeyError):
            continue

    print(f"[{agent_name}] {output_text[:200]}" if output_text else f"[{agent_name}] (no text output)")
    return output_text


# ─── Classifier ──────────────────────────────────────────────────────

VALID_CATEGORIES = {"technical", "product", "business", "planning"}
DEFAULT_CATEGORY = "technical"


def classify(normalized_file, config, feature):
    """Run the classifier agent to determine content category."""
    task = build_task_prompt("classifier", normalized_file, feature)
    result = run_agent("classifier", task, config)

    if result is None:
        print(f"[classifier] Failed — defaulting to '{DEFAULT_CATEGORY}'")
        return DEFAULT_CATEGORY

    # Extract JSON from agent output (may contain markdown fences)
    text = result.strip()
    if "```" in text:
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                text = line
                break

    try:
        data = json.loads(text)
        category = data.get("content_category", DEFAULT_CATEGORY)
        confidence = data.get("confidence", "unknown")
        reasoning = data.get("reasoning", "")

        if category not in VALID_CATEGORIES:
            print(f"[classifier] Unknown category '{category}' — defaulting to '{DEFAULT_CATEGORY}'")
            category = DEFAULT_CATEGORY

        print(f"[classifier] Category: {category} (confidence: {confidence})")
        if reasoning:
            print(f"  Reasoning: {reasoning[:200]}")
        return category

    except (json.JSONDecodeError, AttributeError):
        print(f"[classifier] Could not parse output — defaulting to '{DEFAULT_CATEGORY}'")
        return DEFAULT_CATEGORY


# ─── Helpers ─────────────────────────────────────────────────────────

def find_output_file(directory, basename):
    """Find the most recent file matching a basename in a directory."""
    directory = Path(directory)
    if not directory.exists():
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    expected = directory / f"{today}-{basename}.md"
    if expected.exists():
        return str(expected)
    matches = sorted(
        [m for m in directory.glob(f"*{basename}*") if m.is_file() and m.suffix == ".md"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(matches[0]) if matches else None


# ─── Pipeline ────────────────────────────────────────────────────────

def run_pipeline(input_file, config, feature, force=False):
    """Run the unified pipeline: Pre-process → Summarize → Structure."""
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_file}")
        return False

    resolved_path = str(input_path.resolve())

    if not force and is_already_processed(resolved_path):
        print(f"Skipping (already processed): {input_file}")
        return True

    basename = input_path.stem
    print(f"\nPipeline: Pre-process → Classify → Summarize → Structure")
    print(f"Input: {input_file}")
    print(f"Feature: {feature['name']}")

    # Step 1: Pre-process (script — no LLM)
    normalized_file = preprocess(input_file)
    if not normalized_file:
        print("\nPipeline failed at: pre-processor")
        return False

    # Step 2: Classifier agent (haiku — quick content categorization)
    content_category = classify(normalized_file, config, feature)
    print(f"  → Category: {content_category}")

    # Step 3: Summarizer agent (opus — depth guided by category)
    SUMMARIZED_DIR.mkdir(parents=True, exist_ok=True)
    task = build_task_prompt("summarizer", normalized_file, feature, content_category=content_category)
    result = run_agent("summarizer", task, config)
    if result is None:
        print("\nPipeline failed at: summarizer")
        return False

    summarized_file = find_output_file(SUMMARIZED_DIR, basename)
    if not summarized_file:
        print("\nPipeline failed: summarizer produced no output file")
        return False
    print(f"  → Summarized: {summarized_file}")

    # Step 4: Context Structurer agent (sonnet — categorize and index)
    task = build_task_prompt("context-structurer", summarized_file, feature)
    result = run_agent("context-structurer", task, config)
    if result is None:
        print("\nPipeline failed at: context-structurer")
        return False

    mark_processed(resolved_path)
    print(f"\nPipeline complete for: {input_file}")
    return True


# ─── Main ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py <input-file> [input-file2 ...]")
        print("       python orchestrator.py --scan    (process new files in input/)")
        print("       python orchestrator.py --force   (reprocess even if already done)")
        sys.exit(1)

    load_env()
    config = load_config()
    feature = load_feature(config)

    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    if not args or args[0] == "--scan":
        input_dir = ROOT / "input"
        files = []
        for subdir in ["audio", "video", "docs", "text"]:
            dir_path = input_dir / subdir
            if dir_path.exists():
                files.extend([f for f in dir_path.iterdir() if f.is_file() and not f.name.startswith(".")])

        if not files:
            print("No files found in input/")
            sys.exit(0)

        print(f"Found {len(files)} file(s) to process")
        for f in files:
            run_pipeline(str(f), config, feature, force=force)
    else:
        for input_file in args:
            run_pipeline(input_file, config, feature, force=force)


if __name__ == "__main__":
    main()
