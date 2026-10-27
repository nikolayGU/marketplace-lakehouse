#!/usr/bin/env python3
"""PreToolUse guard for AGENTS.md's hard rules.

deny (exit 2, stderr is the reason): writes to secret files, force push, DROP, TRUNCATE, DELETE
without WHERE, advancing or dropping a replication slot, pg_logical_emit_message, shell writes to
.env, writes to the hooks and settings in this repository's .claude/, and `git commit` unless a
full `make verify` passed on this working tree (.verify-stamp; Markdown and docs/ edited after it
do not count) or runs right before it in the same `&&` chain.
ask (a permission prompt, so the owner's ok is a click): replay and scenarios, source, silver and
other lake writes, Iceberg maintenance and its DAGs, push, rebase, history rewrites, discarded work,
volume, image and recursive deletes, stopped, removed or recreated containers (not the scheduler
stop of the verify cycle), Kafka topic settings, connector, catalog and Postgres settings, DDL,
actions on GitHub, Windows and WSL settings, edits of the agent roles and rules.
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
# Moving the slot past records skips them for good; dropping it forces a new initial snapshot.
SLOT_SKIP = re.compile(r"\bpg_(replication_slot_advance|drop_replication_slot)\b")
SHELL_WRITE_ENV = re.compile(
    r"(>>?|\btee\b(\s+-a)?)\s*[\"']?[^\s;|&]*\.env\b(?!\.example)"
    r"|\bsed\b[^\n;|&]*\s-i\S*[^\n;|&]*\.env\b(?!\.example)"
    r"|\b(cp|mv|install|ln)\b[^\n;|&]*\s[\"']?[^\s;|&]*\.env(\.(?!example\b)[^\s;|&\"']*)?[\"']?"
    r"(\s+[12]?>>?\s*\S+)*\s*($|[;&|\n])"
)
# Pg_logical_emit_message lands in topic oltp.message and stopped CDC once (ADR-023).
LOGICAL_MESSAGE = re.compile(r"\bpg_logical_emit_message\b")
# The guard and its settings (the owner applies changes from a copy, AGENTS.md "Хуки") and the
# agent rules. Only inside this repository: a copy in the scratchpad is free to edit.
HARNESS_FILE = re.compile(r"^\.claude/(hooks/|settings(\.local)?\.json$)")
HARNESS_DOC = re.compile(
    r"^(\.claude/agents/[^/]+|AGENTS\.md|CLAUDE\.md|docs/agent-rules\.md"
    r"|docs/planning/13-harness\.md)$"
)
# A relative path at the start of a word, or an absolute one under the repository root.
IN_REPO = r"(?:^|(?<=[\s\"'=>])|" + re.escape(str(ROOT)) + r"/)(?:\./)?"


def shell_write(target: str) -> re.Pattern[str]:
    """A shell command that writes, moves or removes a file of this repository matching target."""
    path = IN_REPO + target
    return re.compile(
        r"(>>?|\btee\b(\s+-a)?)\s*[\"']?"
        + path
        + r"|\b(sed|perl)\b[^\n;|&]*\s-i\S*[^\n;|&]*"
        + path
        + r"|\b(rm|chmod|chown|truncate|touch)\b[^\n;|&]*"
        + path
        + r"|\b(cp|mv|install|ln|rsync)\b[^\n;|&]*\s[\"']?"
        + path
        + r"[^\s;|&\"']*[\"']?\s*($|[;&|\n])"
        + r"|\bopen\([^)]*"
        + path
    )


SHELL_WRITE_HARNESS = shell_write(r"\.claude/(hooks|settings)")
SHELL_WRITE_RULES = shell_write(
    r"(\.claude/agents/|AGENTS\.md|CLAUDE\.md|docs/agent-rules\.md|docs/planning/13-harness\.md)"
)
# The Debezium connector (8083) and the Lakekeeper catalog (8181) change by any HTTP write.
HTTP_WRITE = r"(?=[^\n]*:(8083|8181)/)[^\n]*"
COMMIT = re.compile(GIT + r"commit\b")
# A full verify chained with && before the commit: the commit only runs if it passed.
VERIFY_THEN_COMMIT = re.compile(r"\bmake\s+verify(\s[^;|\n]*?)?\s*&&[^;|\n]*" + GIT + r"commit\b")

ASK = [
    (
        re.compile(
            r"\bmake\b[^;&|\n]*\s(replay-burst|replay-start|replay-live|replay-reset|replay-load|"
            r"silver|bootstrap|nuke|iceberg-demo|chaos-[\w-]+|cdc-snapshot|migrate|"
            r"watermark-demo|watermark-live)(\s|$)"
        ),
        "spends the replay budget or writes to the source, bronze, silver or the demo tables",
    ),
    (
        re.compile(
            r"-m\s+replayer\s+(start|reset|load)\b"
            r"|\b(start|restart|up|run)\b[^\n;&|]*\boltp-replayer\b"
            r"|scripts/(replay-burst|chaos/[\w-]+)\.sh|connect/snapshot\.sh"
        ),
        "runs the replayer or a scenario",
    ),
    (re.compile(GIT + r"push\b"), "git push"),
    (re.compile(GIT + r"rebase\b"), "git rebase"),
    (re.compile(GIT + r"reset\b[^\n;&|]*--hard\b"), "git reset --hard"),
    (re.compile(GIT + r"commit\b[^\n;&|]*--amend\b"), "git commit --amend"),
    (re.compile(r"\bdocker\b[^\n;&|]*\bdown\b[^\n;&|]*\s(-v|--volumes)\b"), "removes volumes"),
    (re.compile(r"\bdocker\s+(volume\s+(rm|prune)|system\s+prune)\b"), "removes volumes"),
    (re.compile(r"\brm\s+(-[a-z]*r|--recursive)"), "recursive delete"),
    (
        re.compile(
            GIT + r"(clean\b[^\n;&|]*\s-[a-z]*f|checkout\s+(--\s|\.(\s|$))|restore\b"
            r"|stash\s+(drop|clear)|branch\s+-d\b)"
        ),
        "discards uncommitted work or a branch",
    ),
    # spark-silver with no arguments merges silver; with arguments it runs maintenance or the demo.
    (
        re.compile(r"\bcompose\b[^\n;&|]*\brun\b[^\n;&|]*\bspark-silver\b"),
        "a Spark job that writes silver or rewrites lake files",
    ),
    (
        re.compile(
            r"\b(maintenance\s+(expire|orphans|rewrite-data|rewrite-position-deletes)|iceberg_demo"
            r"|expire_snapshots|remove_orphan_files|rewrite_data_files|rewrite_position_delete_files"
            r"|rollback_to_snapshot|set_current_snapshot|cherrypick_snapshot|fast_forward"
            r"|(un)?register_table)\b"
        ),
        "an Iceberg procedure that rewrites or deletes table files (W5-D13 ladder)",
    ),
    (
        re.compile(
            r"\bairflow\s+(dags\s+(trigger|unpause|backfill|test)|tasks\s+(run|test))\b"
            r"[^\n;&|]*iceberg_|/api/v\d+/dags/iceberg_"
            r"|[\"']?dry_run[\"']?\s*:\s*false|[\"']?expire_and_compact[\"']?\s*:\s*true"
        ),
        "the Iceberg maintenance DAGs or their destructive switch (W5-D13 ladder)",
    ),
    (
        re.compile(r"\bairflow\s+(dags\s+delete|tasks\s+clear|db\s+(clean|reset))\b"),
        "deletes or rewrites Airflow run history",
    ),
    (
        re.compile(
            r"\bkafka-(configs|topics)(\.sh)?\b[^\n;&|]*\s--(alter|delete)\b"
            r"|\bkafka-(delete-records|reassign-partitions|leader-election)(\.sh)?\b"
            r"|\bkafka-consumer-groups(\.sh)?\b[^\n;&|]*\s--(reset-offsets|delete(-offsets)?)\b"
        ),
        "changes Kafka topics, retention or offsets",
    ),
    (
        re.compile(
            r"\bdocker\b[^\n;&|]*\s(image\s+(prune|rm|remove)|rmi|builder\s+prune|buildx\s+prune)\b"
            r"|\b(docker|compose)\b[^\n;&|]*\s--rmi\b"
        ),
        "removes images: the MinIO images exist only in the local store (review item 6)",
    ),
    # `compose` also catches $COMPOSE, the Makefile's name for the compose command.
    (
        re.compile(
            r"\b(docker|compose)\b[^\n;&|]*\s(down|rm|container\s+(rm|prune))\b"
            r"|\b(docker|compose)\b(?![^\n;&|]*\bexec\b)[^\n;&|]*\s(stop|kill|restart|pause)\b"
            r"(?![^\n;&|]*airflow-scheduler)"
        ),
        "stops or removes stack containers (the scheduler stop of the verify cycle is free)",
    ),
    # A changed image recreates spark-bronze, and its start sets the bronze metadata property.
    (
        re.compile(r"\bmake\b[^;&|\n]*\s(start|up)(\s|$)|\bcompose\b[^\n;&|]*\sup(\s|$)"),
        "may recreate spark-bronze or minio (ADR-025 bronze metadata property, MinIO image)",
    ),
    (
        re.compile(
            r"\bgh(\s+(-r|--repo)[\s=]\S+)?\s+(workflow\s+(run|enable|disable)"
            r"|run\s+(rerun|cancel|delete)|pr\s+(create|merge|close|comment|review|edit)"
            r"|release\s+(create|delete|upload|edit)|repo\s+(edit|delete|rename|archive)"
            r"|secret\s+(set|delete)|variable\s+(set|delete)|issue\s+(create|close|comment|edit)"
            r"|cache\s+delete)\b"
            r"|\bgh\s+api\b[^\n;&|]*((-x|--method)\s*(post|put|patch|delete)\b"
            r"|\s(-f|--field|--raw-field|--input)[\s=])"
            r"|\bdocker\s+(push|login)\b"
        ),
        "acts on GitHub or a registry, visible outside the laptop",
    ),
    (
        re.compile(
            HTTP_WRITE + r"(-x\s*|--request[\s=]*)(post|put|patch|delete)\b"
            r"|" + HTTP_WRITE + r"\s(-d|--data(-raw|-binary|-urlencode)?|--json)[\s=]"
            r"|scripts/lakekeeper/(protect|register|bootstrap)\.sh"
        ),
        "changes the Debezium connector or the Lakekeeper catalog",
    ),
    (
        re.compile(
            r"\bmc\s+(rm|rb|mv|cp|mirror|retention|ilm|version|admin)\b"
            r"|\baws\s+s3(api)?\s+(rm|rb|mv|cp|sync|delete)"
        ),
        "changes or copies objects of the lake bucket",
    ),
    (
        re.compile(
            r"\b(insert\s+into|update|copy)\s+\"?(shop|replay|cdc)\"?\."
            r"|\bdelete\s+from\s+\"?(shop|replay)\"?\."
            r"|\b(create|alter)\s+(publication|subscription)\b|\balter\s+(role|database)\b"
            r"|\bpg_(terminate_backend|create_logical_replication_slot)\b"
        ),
        "writes to the source database or its replication setup",
    ),
    (
        re.compile(
            r"\b(powercfg|wsl|powershell|pwsh)\.exe\b|\bpowercfg\b|\bwsl\s+--|\.wslconfig\b"
        ),
        "Windows and WSL settings are the owner's",
    ),
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
    from scripts.agent_state import code_changes_since, read_stamp

    if VERIFY_THEN_COMMIT.search(low):
        return True
    stamp = read_stamp(ROOT)
    if stamp is None or stamp.mode != "full":
        return False
    # Markdown and docs/ edited after the verify need no new one, as in stop_gate.py.
    return stamp.fresh or not code_changes_since(ROOT, stamp)


def repo_path(path: str) -> str | None:
    """The path relative to the repository root, None outside it."""
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None


def check(event: dict[str, Any]) -> None:
    tool = event.get("tool_name", "")
    args = event.get("tool_input", {})
    if tool in ("Write", "Edit", "NotebookEdit"):
        path = args.get("file_path") or args.get("notebook_path") or ""
        if SECRET_FILE.search(path) and not path.endswith(".env.example"):
            deny(f"write to a secret file: {path}")
        inside = repo_path(path)
        if inside is not None and HARNESS_FILE.search(inside):
            deny(
                f"write to the agent hooks or settings: {path}",
                "prepare a copy in the scratchpad, the owner applies it with cp",
            )
        if inside is not None and HARNESS_DOC.search(inside):
            ask(f"edits the agent roles or rules: {path}")
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
    if SLOT_SKIP.search(low):
        deny("advancing or dropping a replication slot loses CDC records")
    if LOGICAL_MESSAGE.search(low):
        deny("pg_logical_emit_message lands in oltp.message and stopped CDC (ADR-023)")
    for match in DELETE.finditer(low):
        if not re.search(r"\bwhere\b", match.group(1)):
            deny("DELETE without WHERE")
    if SHELL_WRITE_ENV.search(command):
        deny("shell write to .env")
    if SHELL_WRITE_HARNESS.search(command):
        deny(
            "shell write to the agent hooks or settings",
            "prepare a copy in the scratchpad, the owner applies it with cp",
        )
    if COMMIT.search(low) and not commit_allowed(low):
        deny("git commit without a full make verify on this working tree", "run make verify first")
    if SHELL_WRITE_RULES.search(command):
        ask("edits the agent roles or rules")
    for pattern, reason in ASK:
        if pattern.search(low):
            ask(reason)


try:
    check(json.load(sys.stdin))
except Exception as error:  # a broken guard must not wave the call through
    ask(f"guard.py failed ({error.__class__.__name__}: {error}), check the call by hand")
sys.exit(0)
