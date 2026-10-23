#!/usr/bin/env python3
"""PreToolUse guard for AGENTS.md's hard rules.

deny (exit 2, stderr is the reason): writes to secret files, force push, DROP, TRUNCATE, DELETE
without WHERE, shell writes to .env, and `git commit` unless a full `make verify` passed on this
working tree (.verify-stamp) or runs right before it in the same `&&` chain.
ask (a permission prompt, so the owner's ok is a click): replay, silver and other lake writes,
push, rebase, history rewrites, volume and recursive deletes, connector and Postgres settings, DDL.
The match is on the command text. A command made only of searches and reads (grep, rg, git log,
cat and the like, no substitution or redirect) runs none of these words and passes. If the guard
itself fails, it asks instead of letting the call through.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.[^/]+)?|[^/]+\.(pem|key|p12|pfx)|id_(rsa|ed25519)[^/]*|credentials[^/]*)$"
)
# `git`, its global options, then the subcommand: words in a commit message are not subcommands.
QUOTED_OR_WORD = r"(\"[^\"]*\"|'[^']*'|\S+)"
GIT = (
    r"\bgit(\s+(-c\s+"
    + QUOTED_OR_WORD
    + r"|--(git-dir|work-tree|namespace|config-env|attr-source)\s+"
    + QUOTED_OR_WORD
    + r"|--?[\w-]+(=\S+)?))*\s+[\"']?"
)
FORCE_PUSH = re.compile(GIT + r"push\b[^\n;&|]*(\s--force(-with-lease)?\b|\s-[a-z]*f\b|\s\+\S)")
DROP = re.compile(r"\bdrop\s+(table|view|schema|namespace|database|materialized\s+view)\b")
TRUNCATE = re.compile(r"\btruncate\s+(table\s+)?[a-z_\"][\w.\"]*")
DELETE = re.compile(r"\bdelete\s+from\s+[\w.\"]+([^;]*)")
SHELL_WRITE_ENV = re.compile(
    r"(>>?|\btee\b(\s+-a)?)\s*[\"']?[^\s;|&]*\.env\b(?!\.example)"
    r"|\bsed\b[^\n;|&]*\s-i\S*[^\n;|&]*\.env\b(?!\.example)"
    r"|\b(cp|mv|install|ln)\b[^\n;|&]*\s[\"']?[^\s;|&]*\.env(\.(?!example\b)[^\s;|&\"']*)?[\"']?"
    r"(\s+[12]?>>?\s*\S+)*\s*($|[;&|\n])"
)
COMMIT = re.compile(GIT + r"commit\b")
# A full verify chained with && before the commit: the commit only runs if it passed.
VERIFY_THEN_COMMIT = re.compile(r"\bmake\s+verify(\s[^;|\n]*?)?\s*&&[^;|\n]*" + GIT + r"commit\b")

ASK = [
    (
        re.compile(
            r"\bmake\b[^;&|\n]*\s(replay-burst|replay-start|replay-live|replay-reset|silver|"
            r"bootstrap|nuke|iceberg-demo|chaos-[\w-]+)(\s|$)"
        ),
        "spends the replay budget or writes to bronze, silver or the demo table",
    ),
    (re.compile(r"-m\s+replayer\s+(start|reset|load)\b"), "runs the replayer"),
    (re.compile(GIT + r"push\b"), "git push"),
    (re.compile(GIT + r"rebase\b"), "git rebase"),
    (re.compile(GIT + r"reset\b[^\n;&|]*--hard\b"), "git reset --hard"),
    (re.compile(GIT + r"commit\b[^\n;&|]*--amend\b"), "git commit --amend"),
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

READERS = {"cd", "ls", "cat", "head", "tail", "wc", "cut", "nl", "grep", "egrep", "fgrep", "rg"}
GIT_READERS = {"git log", "git show", "git diff", "git grep", "git blame", "git status"}
SEPARATORS = {"&&", "||", ";", "|"}
NULL_REDIRECT = re.compile(r"[ \t]([12]?>[ \t]*/dev/null|2>&1)(?=[ \t]|$)")
# Substitution, ANSI-C quoting shlex reads differently, a newline that hides a second command.
RUNS_MORE = re.compile(r"\$[(\x27\"]|`|<\(|\n")
# rg --pre and --hostname-bin, git grep -O / --open-files-in-pager (any prefix git accepts) run a
# program; git log and diff --output write a file.
RUNS_PROGRAM = re.compile(r"--pre|--hostname-bin|--op|--output|-[a-zA-Z]*O")


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


def reads_only(command: str) -> bool:
    """A pipeline of searches and reads: the words in it are data, nothing runs them."""
    if RUNS_MORE.search(command):
        return False
    command = NULL_REDIRECT.sub(" ", command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # bash reads `#` inside a word as text, shlex as a comment
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes
        return False
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            segments.append([])
        elif set(token) <= set("();<>|&") or RUNS_PROGRAM.match(token):
            return False  # a redirect, a subshell, a background job or a program to run
        else:
            segments[-1].append(token)
    return all(
        segment and (segment[0] in READERS or " ".join(segment[:2]) in GIT_READERS)
        for segment in segments
    )


def commit_allowed(low: str) -> bool:
    from scripts.agent_state import read_stamp

    if VERIFY_THEN_COMMIT.search(low):
        return True
    stamp = read_stamp(ROOT)
    return stamp is not None and stamp.mode == "full" and stamp.fresh


def check(event: dict[str, Any]) -> None:
    tool = event.get("tool_name", "")
    args = event.get("tool_input", {})
    if tool in ("Write", "Edit", "NotebookEdit"):
        path = args.get("file_path") or args.get("notebook_path") or ""
        if SECRET_FILE.search(path) and not path.endswith(".env.example"):
            deny(f"write to a secret file: {path}")
        return
    if tool != "Bash":
        return
    command = args.get("command", "")
    if reads_only(command):
        return
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


try:
    check(json.load(sys.stdin))
except Exception as error:  # a broken guard must not wave the call through
    ask(f"guard.py failed ({error.__class__.__name__}: {error}), check the call by hand")
sys.exit(0)
