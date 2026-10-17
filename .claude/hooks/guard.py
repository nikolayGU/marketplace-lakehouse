#!/usr/bin/env python3
"""PreToolUse guard. Exit 2 blocks the tool call; stderr is the reason."""

import json
import re
import sys

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.[^/]+)?|[^/]+\.(pem|key|p12|pfx)|id_(rsa|ed25519)[^/]*|credentials[^/]*)$"
)
FORCE_PUSH = re.compile(
    r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*(\s--force(-with-lease)?\b|\s-[a-z]*f\b|\s\+\S)"
)
DROP = re.compile(r"\bdrop\s+(table|view|schema|namespace|database|materialized\s+view)\b")
TRUNCATE = re.compile(r"\btruncate\s+(table\s+)?[a-z_\"][\w.\"]*")
DELETE = re.compile(r"\bdelete\s+from\s+[\w.\"]+([^;]*)")
SHELL_WRITE_ENV = re.compile(
    r"(>>?|\btee\b(\s+-a)?)\s*[\"']?[^\s;|&]*\.env\b(?!\.example)"
    r"|\bsed\b[^\n;|&]*\s-i\S*[^\n;|&]*\.env\b(?!\.example)"
)


def block(reason: str) -> None:
    print(
        f"blocked by .claude/hooks/guard.py: {reason}; ask the owner for an explicit ok",
        file=sys.stderr,
    )
    sys.exit(2)


event = json.load(sys.stdin)
tool = event.get("tool_name", "")
args = event.get("tool_input", {})

if tool in ("Write", "Edit", "NotebookEdit"):
    path = args.get("file_path") or args.get("notebook_path") or ""
    if SECRET_FILE.search(path) and not path.endswith(".env.example"):
        block(f"write to a secret file: {path}")
elif tool == "Bash":
    command = args.get("command", "")
    low = command.lower()
    if FORCE_PUSH.search(low):
        block("force push")
    if DROP.search(low):
        block("DROP")
    if TRUNCATE.search(low):
        block("TRUNCATE")
    for match in DELETE.finditer(low):
        if not re.search(r"\bwhere\b", match.group(1)):
            block("DELETE without WHERE")
    if SHELL_WRITE_ENV.search(command):
        block("shell write to .env")
sys.exit(0)
