#!/usr/bin/env python3
"""SessionStart hook: the facts a session starts from, so it does not depend on the agent reading
them first. Git state, the verify stamp, the current state section of docs/HANDOFF.md, the goal
in docs/NEXT_SESSION.md, the running containers and the ones that should run but do not. Reads
only; a missing piece is reported as such, never fatal."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_state import describe_stamp  # noqa: E402

# The stack is found by the directory of its compose file, which docker compose writes into the
# label of every container, not by the project name: the name may come from .env, which neither
# this hook nor its environment reads. One filter only, as docker ANDs the label filters.
STACK_LABEL = f"label=com.docker.compose.project.working_dir={ROOT / 'docker'}"
# Docker brings these back after a daemon restart, unless they were stopped by hand.
RESTARTED = ("unless-stopped", "always")


def run(*cmd: str) -> str:
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable ({error.__class__.__name__})"
    return result.stdout.rstrip() if result.returncode == 0 else "unavailable"


def docker_lines(*args: str) -> list[str] | None:
    """The lines `docker <args>` prints, None when docker is missing, stuck or fails."""
    try:
        result = subprocess.run(
            ("docker", *args), cwd=ROOT, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.splitlines() if result.returncode == 0 else None


def stack_missing() -> str | None:
    """A line when no container carries the label of this checkout's compose directory while
    other containers exist: a stack started from another directory, or a path that docker wrote
    another way, would otherwise read as a stack with nothing stopped."""
    ours = docker_lines("ps", "-a", "--filter", STACK_LABEL, "--format", "{{.ID}}")
    if ours is None or ours:
        return None
    if not docker_lines("ps", "-a", "--format", "{{.ID}}"):
        return None
    return f"no containers of the stack at {ROOT / 'docker'} (other containers exist)"


def stopped_containers() -> list[str]:
    """One line per stopped container of the stack that a restart policy should have kept up
    (27.10 and 30.10: prometheus stayed in Exited (255) after a Docker restart and nobody saw
    it). Run-once jobs have restart `no` and are left out."""
    ids = docker_lines(
        "ps",
        "-a",
        "--filter",
        STACK_LABEL,
        "--filter",
        "status=exited",
        "--filter",
        "status=dead",
        "--filter",
        "status=created",
        "--format",
        "{{.ID}}",
    )
    if not ids:
        return []
    rows = docker_lines(
        "inspect",
        "--format",
        "{{.Name}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{.State.ExitCode}}",
        *ids,
    )
    lines = []
    for row in rows or []:
        parts = row.split()
        if len(parts) != 4 or parts[1] not in RESTARTED:
            continue
        name, policy, state, code = parts
        name = name.removeprefix("/")
        lines.append(
            f"{name}: {state} ({code}), {policy} did not bring it back; "
            f"docker start {name} only with the owner's ok"
        )
    return lines


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


def containers_section() -> str:
    running = run("docker", "ps", "--format", "{{.Names}} {{.Status}}") or "none"
    if running.startswith("unavailable"):  # no point in asking a docker that does not answer
        return running
    try:
        missing = stack_missing()
        stopped = stopped_containers()
    except Exception as error:  # a surprise from docker must not block the session start
        missing = None
        stopped = [f"stopped containers unreadable ({error.__class__.__name__})"]
    section = running + (f"\n\n{missing}" if missing else "")
    if not stopped:
        return section
    return (
        section + "\n\nNot running, restart policy unless-stopped or always:\n" + "\n".join(stopped)
    )


status = run("git", "status", "--short")
context = "\n\n".join(
    [
        "Session start facts (from .claude/hooks/session_context.py). Rules: AGENTS.md.",
        "Last commits:\n" + run("git", "log", "--oneline", "-5"),
        "Uncommitted: " + (f"{len(status.splitlines())} paths\n{status}" if status else "none"),
        "Verify stamp: " + stamp_line(),
        "HANDOFF:\n" + handoff_state(),
        "NEXT_SESSION:\n" + next_session_goal(),
        "Containers:\n" + containers_section(),
    ]
)
output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
print(json.dumps(output))
