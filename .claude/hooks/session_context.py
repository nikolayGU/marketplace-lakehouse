#!/usr/bin/env python3
"""SessionStart hook: the facts a session starts from, so it does not depend on the agent reading
them first. Git state, the verify stamp, the current state section of docs/HANDOFF.md, the goal
in docs/NEXT_SESSION.md and the running containers. Reads only; a missing piece is reported as
such, never fatal."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_state import describe_stamp  # noqa: E402


def run(*cmd: str) -> str:
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable ({error.__class__.__name__})"
    return result.stdout.rstrip() if result.returncode == 0 else "unavailable"


def handoff_state() -> str:
    path = ROOT / "docs" / "HANDOFF.md"
    if not path.exists():
        return "docs/HANDOFF.md is missing"
    lines = path.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## Состояние")), None)
    if start is None:
        return "no '## Состояние' section in docs/HANDOFF.md"
    section = []
    for line in lines[start:]:
        if line.startswith("### ") or (section and line.startswith("## ")):
            break
        section.append(line)
    return "\n".join(section).strip()


def next_session_goal() -> str:
    path = ROOT / "docs" / "NEXT_SESSION.md"
    if not path.exists():
        return "docs/NEXT_SESSION.md is missing"
    lines = path.read_text().splitlines()
    head = lines[:1]
    if "```text" in lines:
        body = lines[lines.index("```text") + 1 :]
        head += body[: next((i for i, line in enumerate(body) if not line.strip()), len(body))]
    return "\n".join(head)


def stamp_line() -> str:
    try:
        return describe_stamp(ROOT)
    except Exception as error:  # git trouble must not block the session start
        return f"unreadable ({error.__class__.__name__})"


status = run("git", "status", "--short")
context = "\n\n".join(
    [
        "Session start facts (from .claude/hooks/session_context.py). Rules: AGENTS.md.",
        "Last commits:\n" + run("git", "log", "--oneline", "-5"),
        "Uncommitted: " + (f"{len(status.splitlines())} paths\n{status}" if status else "none"),
        "Verify stamp: " + stamp_line(),
        "HANDOFF:\n" + handoff_state(),
        "NEXT_SESSION:\n" + next_session_goal(),
        "Containers:\n" + (run("docker", "ps", "--format", "{{.Names}} {{.Status}}") or "none"),
    ]
)
output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
print(json.dumps(output))
