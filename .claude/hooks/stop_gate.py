#!/usr/bin/env python3
"""Stop hook: a turn that changed code ends only after `make verify-fast` or `make verify` passed
on the current working tree (.verify-stamp). Markdown and docs/ changes need no check. Blocks once
per stop: when Claude Code is already continuing because of this hook, it lets the turn end, so a
stack that is down cannot loop the session."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_state import code_changes, read_stamp  # noqa: E402

event = json.load(sys.stdin)
if event.get("stop_hook_active"):
    sys.exit(0)
try:
    changed = code_changes(ROOT)
    stamp = read_stamp(ROOT) if changed else None
except Exception as error:  # a broken git state must not trap the session
    print(f"stop_gate.py could not read the repo state: {error}", file=sys.stderr)
    sys.exit(0)
if not changed or (stamp is not None and stamp.fresh):
    sys.exit(0)

shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
reason = (
    f"Code changed ({shown}) and no make verify-fast or make verify passed on this working tree. "
    "Run make verify-fast and put its output in the report. If the stack is down, say "
    "'не проверено' in the report with the reason instead."
)
print(json.dumps({"decision": "block", "reason": reason}))
