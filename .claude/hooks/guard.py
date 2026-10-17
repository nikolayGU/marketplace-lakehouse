#!/usr/bin/env python3
"""PreToolUse guard for AGENTS.md's hard rules.

deny (exit 2, stderr is the reason): writes to secret files, force push, DROP, TRUNCATE, DELETE
without WHERE, shell writes to .env, and `git commit` unless a full `make verify` passed on this
working tree (.verify-stamp) or runs right before it in the same `&&` chain.
ask (a permission prompt, so the owner's ok is a click): replay, silver and other lake writes,
push, rebase, history rewrites, volume and recursive deletes, connector and Postgres settings, DDL.
The match is on the command text, so a grep for such words is caught too.
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_state import read_stamp  # noqa: E402

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.[^/]+)?|[^/]+\.(pem|key|p12|pfx)|id_(rsa|ed25519)[^/]*|credentials[^/]*)$"
)
GIT = r"\bgit\b[^\n;&|]*"
FORCE_PUSH = re.compile(GIT + r"\bpush\b[^\n;&|]*(\s--force(-with-lease)?\b|\s-[a-z]*f\b|\s\+\S)")
DROP = re.compile(r"\bdrop\s+(table|view|schema|namespace|database|materialized\s+view)\b")
TRUNCATE = re.compile(r"\btruncate\s+(table\s+)?[a-z_\"][\w.\"]*")
DELETE = re.compile(r"\bdelete\s+from\s+[\w.\"]+([^;]*)")
SHELL_WRITE_ENV = re.compile(
    r"(>>?|\btee\b(\s+-a)?)\s*[\"']?[^\s;|&]*\.env\b(?!\.example)"
    r"|\bsed\b[^\n;|&]*\s-i\S*[^\n;|&]*\.env\b(?!\.example)"
)
COMMIT = re.compile(GIT + r"\bcommit\b")
# A full verify chained with && before the commit: the commit only runs if it passed.
VERIFY_THEN_COMMIT = re.compile(r"\bmake\s+verify(\s[^;|\n]*?)?\s*&&[^;|\n]*" + GIT + r"\bcommit\b")

ASK = [
    (
        re.compile(
            r"\bmake\b[^;&|\n]*\s(replay-burst|replay-start|replay-live|replay-reset|silver|"
            r"bootstrap|nuke|iceberg-demo|chaos-[\w-]+)(\s|$)"
        ),
        "spends the replay budget or writes to bronze, silver or the demo table",
    ),
    (re.compile(r"-m\s+replayer\s+(start|reset|load)\b"), "runs the replayer"),
    (re.compile(GIT + r"\bpush\b"), "git push"),
    (re.compile(GIT + r"\brebase\b"), "git rebase"),
    (re.compile(GIT + r"\breset\b[^\n;&|]*--hard\b"), "git reset --hard"),
    (re.compile(GIT + r"\bcommit\b[^\n;&|]*--amend\b"), "git commit --amend"),
    (re.compile(r"\bdocker\b[^\n;&|]*\bdown\b[^\n;&|]*\s(-v|--volumes)\b"), "removes volumes"),
    (re.compile(r"\bdocker\s+(volume\s+(rm|prune)|system\s+prune)\b"), "removes volumes"),
    (re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-r\s+-f|-f\s+-r)"), "rm -rf"),
    (
        re.compile(r"connect/register\.sh|:8083/connectors\S*[^\n]*-x\s*(put|post|delete)"),
        "changes the Debezium connector",
    ),
    (re.compile(r"-x\s*(put|post|delete)[^\n]*:8083/connectors"), "changes the Debezium connector"),
    (re.compile(r"\balter\s+system\b"), "changes Postgres settings"),
    (re.compile(r"\b(alter|create)\s+(table|schema|view|namespace)\b"), "DDL outside migrations"),
]


def deny(reason: str, fix: str = "ask the owner for an explicit ok") -> None:
    print(f"blocked by .claude/hooks/guard.py: {reason}; {fix}", file=sys.stderr)
    sys.exit(2)


def ask(reason: str) -> None:
    decision = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": f"AGENTS.md hard rule, needs the owner's ok: {reason}",
    }
    print(json.dumps({"hookSpecificOutput": decision}))
    sys.exit(0)


def commit_allowed(low: str) -> bool:
    if VERIFY_THEN_COMMIT.search(low):
        return True
    stamp = read_stamp(ROOT)
    return stamp is not None and stamp.mode == "full" and stamp.fresh


event = json.load(sys.stdin)
tool = event.get("tool_name", "")
args = event.get("tool_input", {})

if tool in ("Write", "Edit", "NotebookEdit"):
    path = args.get("file_path") or args.get("notebook_path") or ""
    if SECRET_FILE.search(path) and not path.endswith(".env.example"):
        deny(f"write to a secret file: {path}")
elif tool == "Bash":
    command = args.get("command", "")
    low = command.lower()
    if FORCE_PUSH.search(low):
        deny("force push")
    if DROP.search(low):
        deny("DROP")
    if TRUNCATE.search(low):
        deny("TRUNCATE")
    for match in DELETE.finditer(low):
        if not re.search(r"\bwhere\b", match.group(1)):
            deny("DELETE without WHERE")
    if SHELL_WRITE_ENV.search(command):
        deny("shell write to .env")
    if COMMIT.search(low) and not commit_allowed(low):
        deny("git commit without a full make verify on this working tree", "run make verify first")
    for pattern, reason in ASK:
        if pattern.search(low):
            ask(reason)
sys.exit(0)
