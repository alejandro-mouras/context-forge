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

    # Find the output file — strip YYYYMMDD_ prefix since preprocess.sh converts it to YYYY-MM-DD-
    import re
    basename = Path(input_file).stem
    name_part = re.sub(r"^\d{8}_", "", basename)
    output_file = find_output_file(NORMALIZED_DIR, name_part)
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


def build_task_prompt(agent_name, input_file, feature, classification=None):
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
        if classification:
            primary = classification["primary"]
            secondary = classification.get("secondary")
            if secondary:
                category_note = (
                    f"\n\nCONTENT CATEGORIES: primary={primary}, secondary={secondary}\n"
                    f"Use the '{primary}' extraction profile as your base structure. "
                    f"But for sections that contain {secondary} content, apply the '{secondary}' "
                    f"extraction depth — preserve full detail for those sections as described "
                    f"in the '{secondary}' profile. Do not compress {secondary} sections just "
                    f"because the primary category has higher compression."
                )
            else:
                category_note = (
                    f"\n\nCONTENT CATEGORY: {primary}\n"
                    f"Use the '{primary}' extraction profile from your system prompt. "
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

    return f"Process: {input_file}"



# Per-agent timeout in seconds
AGENT_TIMEOUTS = {
    "classifier": 120,       # haiku, 1 turn — should be very fast
    "summarizer": 1800,      # opus, large docs with images — up to 30 min
    # context-structurer is now pure Python, no timeout needed
}


def run_agent(agent_name, task, config):
    """Launch a Claude Code instance for an agent with real-time progress output."""
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
    print(f"{'='*60}\n", flush=True)

    # Stream output in real-time instead of capturing
    import time
    start_time = time.time()
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    output_text = ""
    turn_count = 0

    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                # Show tool usage in real-time
                if event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "?")
                            elapsed = int(time.time() - start_time)
                            print(f"  [{elapsed}s] Using: {tool_name}", flush=True)
                            turn_count += 1
                        elif block.get("type") == "text":
                            output_text = block["text"]

                elif event_type == "result":
                    text = event.get("result", "")
                    if text:
                        output_text = text

            except (json.JSONDecodeError, KeyError):
                continue

        process.wait(timeout=timeout)

    except subprocess.TimeoutExpired:
        process.kill()
        print(f"[ERROR] {agent_name} timed out after {timeout}s")
        return None

    elapsed = int(time.time() - start_time)

    if process.returncode != 0:
        stderr = process.stderr.read() if process.stderr else ""
        print(f"[ERROR] {agent_name} failed (exit {process.returncode}) after {elapsed}s")
        if stderr:
            print(f"  stderr: {stderr[:500]}")
        return None

    print(f"\n  [{elapsed}s] Done ({turn_count} tool calls)")
    print(f"[{agent_name}] {output_text[:200]}" if output_text else f"[{agent_name}] (no text output)", flush=True)
    return output_text


# ─── Classifier ──────────────────────────────────────────────────────

VALID_CATEGORIES = {"technical", "product", "business", "planning"}
VALID_OUTPUT_CATEGORIES = {"meetings", "voice-notes", "documents", "research"}
DEFAULT_CATEGORY = "technical"
DEFAULT_OUTPUT_CATEGORY = "documents"


def classify(normalized_file, config, feature):
    """Run the classifier agent to determine content category.

    Returns a dict with 'primary' and optional 'secondary' category.
    """
    task = build_task_prompt("classifier", normalized_file, feature)
    result = run_agent("classifier", task, config)

    default_result = {"primary": DEFAULT_CATEGORY, "secondary": None, "output_category": DEFAULT_OUTPUT_CATEGORY}

    if result is None:
        print(f"[classifier] Failed — defaulting to '{DEFAULT_CATEGORY}'")
        return default_result

    # Extract JSON from agent output (may contain markdown fences)
    text = result.strip()
    if "```" in text:
        import re
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    try:
        data = json.loads(text)
        primary = data.get("content_category", DEFAULT_CATEGORY)
        secondary = data.get("secondary_category")
        confidence = data.get("confidence", "unknown")
        reasoning = data.get("reasoning", "")

        if primary not in VALID_CATEGORIES:
            print(f"[classifier] Unknown primary '{primary}' — defaulting to '{DEFAULT_CATEGORY}'")
            primary = DEFAULT_CATEGORY

        if secondary and secondary not in VALID_CATEGORIES:
            print(f"[classifier] Unknown secondary '{secondary}' — ignoring")
            secondary = None

        output_category = data.get("output_category", DEFAULT_OUTPUT_CATEGORY)
        if output_category not in VALID_OUTPUT_CATEGORIES:
            print(f"[classifier] Unknown output_category '{output_category}' — defaulting to '{DEFAULT_OUTPUT_CATEGORY}'")
            output_category = DEFAULT_OUTPUT_CATEGORY

        if secondary:
            print(f"[classifier] Category: {primary} + {secondary} → {output_category} (confidence: {confidence})")
        else:
            print(f"[classifier] Category: {primary} → {output_category} (confidence: {confidence})")
        if reasoning:
            print(f"  Reasoning: {reasoning[:200]}")

        return {"primary": primary, "secondary": secondary, "output_category": output_category}

    except (json.JSONDecodeError, AttributeError):
        print(f"[classifier] Could not parse output — defaulting to '{DEFAULT_CATEGORY}'")
        return default_result


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


# ─── Context Structurer (pure Python, no LLM) ───────────────────────

def slugify(text):
    """Convert text to a URL-friendly slug."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


def extract_tags_from_content(content, feature):
    """Extract feature profile tags found in the summarized content."""
    tags = []
    feature_tags = feature.get("tags", {})
    for tag in feature_tags:
        # Look for the tag in headers, table cells, or [TAG] references
        if f"[{tag}]" in content or f"`{tag}`" in content or f"| {tag} |" in content:
            tags.append(tag)
    return tags


def structure_output(summarized_file, feature, output_category):
    """Copy summarized file to output directory and update indexes. No LLM needed."""
    print(f"\n{'='*60}")
    print(f"  Context Structurer (script)")
    print(f"{'='*60}\n")

    feature_name = feature["name"]
    output_dir = ROOT / "output" / feature_name / output_category
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read summarized content
    content = Path(summarized_file).read_text(encoding="utf-8")

    # Extract title from first H1 heading
    title = Path(summarized_file).stem
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line.lstrip("# ").split(" — ")[0].strip()
            break

    # Extract date from summarized filename (YYYY-MM-DD-name.md)
    import re
    stem = Path(summarized_file).stem
    date_match = re.match(r"(\d{4}-\d{2}-\d{2})-", stem)
    file_date = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")

    # Build output filename: YYYY-MM-DD-slugified-title.md
    slug = slugify(title)
    output_filename = f"{file_date}-{slug}.md"
    output_file = output_dir / output_filename

    # Copy content to output
    output_file.write_text(content, encoding="utf-8")
    print(f"  → Output: {output_file}")

    # Extract tags from content
    tags = extract_tags_from_content(content, feature)
    tags_str = ", ".join(f"[{t}]" for t in tags) if tags else "—"

    # Timestamp for index entries
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Update category index
    _update_category_index(output_dir, now, title, tags_str, output_filename)

    # Update master index
    _update_master_index(ROOT / "output" / feature_name, feature_name, now, title,
                         tags, output_category, output_filename)

    print(f"  → Tags: {tags_str}")
    print(f"  → Indexes updated")
    return str(output_file)


def _update_category_index(category_dir, timestamp, title, tags_str, filename):
    """Update or create the category _index.md."""
    index_file = category_dir / "_index.md"
    category_name = category_dir.name.replace("-", " ").title()

    if index_file.exists():
        lines = index_file.read_text(encoding="utf-8").split("\n")
        # Remove existing entry for same filename if present
        lines = [l for l in lines if filename not in l]
        # Find the table (after header row + separator)
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith("|---") or line.startswith("| ---"):
                insert_idx = i + 1
                break
        if insert_idx is not None:
            entry = f"| {timestamp} | {title} | {tags_str} | document |"
            lines.insert(insert_idx, entry)
        content = "\n".join(lines)
    else:
        content = (
            f"# {category_name}\n\n"
            f"| Processed | Title | Tags | Source |\n"
            f"|-----------|-------|------|--------|\n"
            f"| {timestamp} | {title} | {tags_str} | document |\n"
        )

    index_file.write_text(content, encoding="utf-8")


def _update_master_index(feature_dir, feature_name, timestamp, title, tags,
                         output_category, filename):
    """Update or create the master _master-index.md."""
    index_file = feature_dir / "_master-index.md"
    relative_path = f"{output_category}/{filename}"
    tags_str = ", ".join(f"[{t}]" for t in tags) if tags else "—"
    entry_line = f"- [{timestamp} {title}]({relative_path}) — {tags_str}"

    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        # Remove existing entry for same file if present
        lines = [l for l in content.split("\n") if filename not in l]
        content = "\n".join(lines)

        # Add to Recent section (after "## Recent" line)
        recent_lines = content.split("\n")
        insert_idx = None
        for i, line in enumerate(recent_lines):
            if line.strip() == "## Recent":
                insert_idx = i + 1
                break

        if insert_idx is not None:
            recent_lines.insert(insert_idx, entry_line)
        else:
            # No Recent section — add one after the title
            for i, line in enumerate(recent_lines):
                if line.startswith("# "):
                    recent_lines.insert(i + 1, f"\n## Recent\n{entry_line}")
                    break

        content = "\n".join(recent_lines)

        # Add to "By component" sections
        for tag in tags:
            section_header = f"### {tag}"
            if section_header in content:
                # Add under existing section if not already there
                tag_entry = f"- [{timestamp} {title}]({relative_path})"
                if tag_entry not in content:
                    idx = content.index(section_header) + len(section_header)
                    content = content[:idx] + f"\n{tag_entry}" + content[idx:]
            else:
                # Create new section before the end
                tag_entry = f"\n{section_header}\n- [{timestamp} {title}]({relative_path})\n"
                content = content.rstrip() + "\n" + tag_entry

        index_file.write_text(content, encoding="utf-8")
    else:
        # Create fresh master index
        lines = [f"# {feature_name.title()} — Master Index\n", "## Recent", entry_line, "",
                 "## By component"]
        for tag in tags:
            lines.append(f"\n### {tag}")
            lines.append(f"- [{timestamp} {title}]({relative_path})")
        lines.append("")
        index_file.write_text("\n".join(lines), encoding="utf-8")


# ─── Pipeline ────────────────────────────────────────────────────────

PIPELINE_STEPS = ["preprocess", "classify", "summarize", "structure"]


def run_pipeline(input_file, config, feature, force=False, from_step=None):
    """Run the unified pipeline: Pre-process → Classify → Summarize → Structure.

    Args:
        from_step: Start from this step instead of the beginning.
            "classify" — skip pre-process, input must be a file in processing/normalized/
            "summarize" — skip pre-process + classify, input must be in processing/normalized/
            "structure" — skip everything except structurer, input must be in processing/summarized/
    """
    import re
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"Error: File not found: {input_file}")
        return False

    # Validate YYYYMMDD_ prefix on input files (not for --from-step which uses processing/ files)
    if not from_step and not re.match(r"^\d{8}_", input_path.name):
        print(f"Error: Input filename must start with YYYYMMDD_ prefix")
        print(f"  Got: {input_path.name}")
        print(f"  Expected: YYYYMMDD_description.ext (e.g., 20260321_my-document.md)")
        return False

    resolved_path = str(input_path.resolve())
    start = PIPELINE_STEPS.index(from_step) if from_step else 0
    steps_label = " → ".join(s.capitalize() for s in PIPELINE_STEPS[start:])

    if start == 0 and not force and is_already_processed(resolved_path):
        print(f"Skipping (already processed): {input_file}")
        return True

    basename = input_path.stem
    # Strip date prefix from basename for output file matching
    # Handles both YYYYMMDD_ (input files) and YYYY-MM-DD- (processing files)
    import re
    clean_basename = re.sub(r"^(\d{8}_|\d{4}-\d{2}-\d{2}-)", "", basename)

    print(f"\nPipeline: {steps_label}")
    print(f"Input: {input_file}")
    print(f"Feature: {feature['name']}")

    # Step 1: Pre-process (script — no LLM)
    if start <= 0:
        normalized_file = preprocess(input_file)
        if not normalized_file:
            print("\nPipeline failed at: pre-processor")
            return False
    else:
        normalized_file = str(input_path) if start <= 2 else None

    # Step 2: Classifier agent (haiku — quick content categorization)
    if start <= 1:
        classification = classify(normalized_file, config, feature)
        label = classification["primary"]
        if classification.get("secondary"):
            label += f" + {classification['secondary']}"
        print(f"  → Category: {label} → {classification['output_category']}")
    else:
        classification = {"primary": DEFAULT_CATEGORY, "secondary": None, "output_category": DEFAULT_OUTPUT_CATEGORY}
        print(f"  → Category: {DEFAULT_CATEGORY} → {DEFAULT_OUTPUT_CATEGORY} (default, classifier skipped)")

    # Step 3: Summarizer agent (opus — depth guided by category)
    if start <= 2:
        SUMMARIZED_DIR.mkdir(parents=True, exist_ok=True)
        task = build_task_prompt("summarizer", normalized_file, feature, classification=classification)
        result = run_agent("summarizer", task, config)
        if result is None:
            print("\nPipeline failed at: summarizer")
            return False

        summarized_file = find_output_file(SUMMARIZED_DIR, clean_basename)
        if not summarized_file:
            print("\nPipeline failed: summarizer produced no output file")
            return False
        print(f"  → Summarized: {summarized_file}")
    else:
        summarized_file = str(input_path)

    # Step 4: Context Structurer (script — copy to output + update indexes)
    output_category = classification.get("output_category", DEFAULT_OUTPUT_CATEGORY)
    output_file = structure_output(summarized_file, feature, output_category)
    if not output_file:
        print("\nPipeline failed at: context-structurer")
        return False

    if start == 0:
        mark_processed(resolved_path)
    print(f"\nPipeline complete for: {input_file}")
    return True


# ─── Main ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py <input-file> [input-file2 ...]")
        print("       python orchestrator.py --scan          (process new files in input/)")
        print("       python orchestrator.py --force         (reprocess even if already done)")
        print("       python orchestrator.py --from-step <step> <file>")
        print("         Steps: classify, summarize, structure")
        print("         Example: python orchestrator.py --from-step classify processing/normalized/file.md")
        sys.exit(1)

    load_env()
    config = load_config()
    feature = load_feature(config)

    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    # Parse --from-step
    from_step = None
    if "--from-step" in args:
        idx = args.index("--from-step")
        if idx + 1 >= len(args):
            print("Error: --from-step requires a step name (classify, summarize, structure)")
            sys.exit(1)
        from_step = args[idx + 1]
        if from_step not in PIPELINE_STEPS[1:]:  # can't start from "preprocess" — that's the default
            print(f"Error: Invalid step '{from_step}'. Valid: classify, summarize, structure")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    if not args or args[0] == "--scan":
        if from_step:
            print("Error: --from-step cannot be used with --scan")
            sys.exit(1)
        input_dir = ROOT / "input"
        files = []
        for subdir in ["audio", "video", "docs", "text", "images"]:
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
            run_pipeline(input_file, config, feature, force=force, from_step=from_step)


if __name__ == "__main__":
    main()
