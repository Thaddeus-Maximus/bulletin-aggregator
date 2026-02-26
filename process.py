#!/usr/bin/env python3
"""
Phase 2: Extract events from bulletin PDFs using the Claude CLI.

For each bulletin in store.json that doesn't yet have a .json summary,
invokes Claude to extract structured event data and saves the summary
alongside the PDF (same filename, .json extension).

Writes staged_events.json, ready for Phase 3 (merge).

Usage:
    python process.py
"""

import json
import re
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

STORE_PATH = Path("store.json")
STAGED_PATH = Path("staged_events.json")

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
Read the parish bulletin PDF at: {pdf_path}
Bulletin date: {bulletin_date}

Output a JSON array of events. Each object:
  "type": "mass" | "adoration" | "confession" | "misc"
  "location": string
  "datetime": "YYYY-MM-DDTHH:MM:00"
  "time_desc": time as written in bulletin
  "page": integer

Optional fields (include only when applicable):
  "details": brief description — misc events only
  "cancelled": true — only if bulletin explicitly states the event is cancelled

Rules:
- For recurring schedules (masses, confession, adoration): output only the next upcoming occurrence of each from the bulletin date. One object per distinct time slot.
- For misc event series (weekly group, monthly gathering, etc.): output only the next upcoming occurrence. Note the series in details.
- Silence is not cancellation — omit events not mentioned.
- "reconciliation" = type "confession".

Output ONLY the JSON array, nothing else.\
"""

# ---------------------------------------------------------------------------
# Store helper
# ---------------------------------------------------------------------------

def load_store() -> dict:
    if not STORE_PATH.exists():
        print("Error: store.json not found. Run scrape.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Claude invocation
# ---------------------------------------------------------------------------

def run_claude(prompt: str, pdf_path: Path) -> str:
    """
    Invoke the Claude CLI non-interactively.
    stderr flows live to the terminal (tool use, status messages).
    stdout is streamed to the terminal and captured for JSON parsing.
    """
    process = subprocess.Popen(
        ["claude", "--print", "--allowedTools", f"Read({pdf_path})"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
    )

    process.stdin.write(prompt)
    process.stdin.close()

    chunks = []

    def _read_stdout():
        for line in process.stdout:
            print(line, end="", flush=True)
            chunks.append(line)

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()

    start = time.time()
    while True:
        reader.join(timeout=5)
        if not reader.is_alive():
            break
        elapsed = time.time() - start
        print(f"  ... {elapsed:.0f}s", end="\r", flush=True)
        if elapsed > 600:
            process.kill()
            reader.join()
            raise RuntimeError("Claude CLI timed out after 600s")

    process.wait()

    if process.returncode != 0:
        raise RuntimeError(f"Claude CLI exited with code {process.returncode}")

    return "".join(chunks).strip()


def extract_json_array(text: str) -> list:
    """
    Pull a JSON array out of Claude's response.
    Tries the full response first; falls back to finding the first [...] span
    in case Claude added any preamble or postamble.
    """
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not extract a JSON array from Claude's response.\n"
        f"First 500 chars:\n{text[:500]}"
    )

# ---------------------------------------------------------------------------
# Per-bulletin processing
# ---------------------------------------------------------------------------

def summary_path_for(local_path: str) -> Path:
    return Path(local_path).with_suffix(".json")


def process_bulletin(bulletin: dict) -> list:
    """
    Ensure a .json summary exists for this bulletin, running Claude if needed.
    Returns the event list with source/bulletin_url/id injected.
    """
    pdf_path = Path(bulletin["local_path"]).resolve()
    summary = summary_path_for(bulletin["local_path"])

    if summary.exists():
        print(f"  Summary exists, loading")
        raw_items = json.loads(summary.read_text(encoding="utf-8"))
    else:
        prompt = PROMPT_TEMPLATE.format(
            pdf_path=pdf_path,
            bulletin_date=bulletin["date"],
        )
        raw_text = run_claude(prompt, pdf_path)
        raw_items = extract_json_array(raw_text)
        summary.write_text(json.dumps(raw_items, indent=2), encoding="utf-8")
        print(f"  Saved → {summary.name}")

    # Inject metadata Claude doesn't need to generate
    events = []
    for item in raw_items:
        event = dict(item)
        event["source"] = bulletin["source"]
        event["bulletin_url"] = bulletin["url"]
        event["id"] = None
        events.append(event)

    return events

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    store = load_store()
    bulletins = store.get("bulletins", [])

    if not bulletins:
        print("No bulletins found. Run scrape.py first.")
        return

    needs_claude = sum(1 for b in bulletins if not summary_path_for(b["local_path"]).exists())
    print(f"{len(bulletins)} bulletin(s) total, {needs_claude} need processing.\n")

    all_events = []
    for bulletin in bulletins:
        print(f"[{bulletin['source']}] {bulletin['date']}")
        try:
            events = process_bulletin(bulletin)
            all_events.extend(events)
            print(f"  {len(events)} event(s)\n")
        except Exception as e:
            print(f"  ERROR: {e}\n", file=sys.stderr)

    STAGED_PATH.write_text(json.dumps(all_events, indent=2), encoding="utf-8")
    print(f"Done. {len(all_events)} total event(s) written to {STAGED_PATH}")


if __name__ == "__main__":
    main()
