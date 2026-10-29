#!/usr/bin/env python3
"""Hook for the `reviewer` subagent: records the verdict of its report in .review-stamp, which the
commit gate in guard.py asks for. Runs on PostToolUse of SubagentHandback, where the report is
`tool_input.message` (auto mode), and on SubagentStop, where it is `last_assistant_message` in the
other modes; after a hand-back that field holds only the closing text, which has no verdict line
and leaves the stamp as it is. Other agent types are ignored. The outcome goes to stderr. The hook
never blocks: whatever goes wrong, it exits 0."""

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def report_of(event: dict[str, Any]) -> str:
    if event.get("hook_event_name") == "SubagentStop":
        message = event.get("last_assistant_message")
    else:
        message = (event.get("tool_input") or {}).get("message")
    return message if isinstance(message, str) else ""


def main() -> None:
    from scripts.agent_state import record_review

    event = json.load(sys.stdin)
    if event.get("agent_type") == "reviewer":
        print(record_review(ROOT, report_of(event)), file=sys.stderr)


try:
    main()
except Exception as error:  # the stamp is evidence, not a gate step: a failure here never blocks
    print(f"review_stamp.py could not record the review: {error}", file=sys.stderr)
sys.exit(0)
