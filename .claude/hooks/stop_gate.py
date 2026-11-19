#!/usr/bin/env python3
"""Stop hook: a turn that changed code of the stack ends only after `make verify-fast` or
`make verify` passed on it (.verify-stamp). Only paths of the `verify` level or above count (see
`gate_level` in scripts/agent_state.py): tests, CI, agent files and lint configs are checked by
`make check` at the commit gate, Markdown and docs/ need nothing. The stamp counts for a path when
the path did not change since the stamped tree (`uncovered`, the rule of the commit gate in
guard.py): a report written after the verify does not ask for another one, an edit of the stack
code after it does. When the session has a base (the tree it started on, kept by
session_context.py), only the paths changed since that base count, so code edited before the
session is not blamed on it; without a base the paths changed against HEAD count. Blocks once per
stop: when Claude Code is already continuing because of this hook, it lets the turn end, so a
stack that is down cannot loop the session."""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_state import (  # noqa: E402
    changed_paths,
    code_changes,
    gate_level,
    read_stamp,
    session_base,
    tree_hash,
    uncovered,
)

STACK_LEVELS = ("verify", "full")


def stack_paths(paths: list[str]) -> list[str]:
    return [p for p in paths if gate_level(p) in STACK_LEVELS]


def unverified_code(session_id: str) -> list[str]:
    """The stack paths that no verify stamp covers: every changed path when there is no stamp or
    its tree is gone from the object store, else those that differ from the stamped tree."""
    current = tree_hash(ROOT)
    base = session_base(ROOT, session_id) if session_id else None
    since = code_changes(ROOT)
    if base:
        # Code that came in a commit after the base (a pull, a commit of the owner) passed the
        # commit gate, and an edit that was undone is no change: only what still differs from
        # HEAD counts.
        with contextlib.suppress(subprocess.CalledProcessError):  # base tree gone: as without it
            since = sorted(set(changed_paths(ROOT, base, current)) & set(since))
    changed = stack_paths(since)
    if not changed:
        return []
    stamp = read_stamp(ROOT, "verify", current)
    if stamp is None:
        return changed
    open_paths = uncovered(ROOT, stamp, current, "verify")
    if open_paths and open_paths[0].startswith("(tree "):  # the stamped tree is gone
        return changed
    return [p for p in changed if p in open_paths]


try:
    event = json.load(sys.stdin)
except ValueError:
    event = {}
if not isinstance(event, dict):
    event = {}
if event.get("stop_hook_active"):
    sys.exit(0)
session_id = event.get("session_id")
try:
    changed = unverified_code(session_id if isinstance(session_id, str) else "")
except Exception as error:  # a broken git state must not trap the session
    print(f"stop_gate.py could not read the repo state: {error}", file=sys.stderr)
    sys.exit(0)
if not changed:
    sys.exit(0)

shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
reason = (
    f"Code changed ({shown}) and no make verify-fast or make verify passed on this working tree. "
    "Run make verify-fast and put its output in the report. If the stack is down, say "
    "'не проверено' in the report with the reason instead."
)
print(json.dumps({"decision": "block", "reason": reason}))
