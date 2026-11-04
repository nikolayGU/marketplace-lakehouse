#!/usr/bin/env python3
"""Stop hook: a turn that changed code ends only after `make verify-fast` or `make verify` passed
on this code (.verify-stamp). The stamp counts when it is exactly fresh for the working tree or
when the tree differs from the stamped one only in Markdown and docs/, the rule of the commit
gate in guard.py: a report written after the verify does not ask for another one, an edit of code
after it does. Markdown and docs/ changes alone need no check. Blocks once per stop: when Claude
Code is already continuing because of this hook, it lets the turn end, so a stack that is down
cannot loop the session."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_state import (  # noqa: E402
    code_changes,
    code_changes_since,
    read_stamp,
    tree_hash,
)


def unverified_code() -> list[str]:
    """The code paths that no verify stamp covers: every changed path when there is no stamp or
    its tree is gone from the object store, else those that differ from the stamped tree."""
    changed = code_changes(ROOT)
    if not changed:
        return []
    current = tree_hash(ROOT)
    stamp = read_stamp(ROOT, "verify", current)
    if stamp is None:
        return changed
    if stamp.fresh:
        return []
    try:
        return code_changes_since(ROOT, stamp, current)
    except subprocess.CalledProcessError:  # the stamped tree is gone, so the stamp covers nothing
        return changed


event = json.load(sys.stdin)
if event.get("stop_hook_active"):
    sys.exit(0)
try:
    changed = unverified_code()
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
