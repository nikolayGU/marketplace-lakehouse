#!/usr/bin/env python3
"""PreToolUse guard for AGENTS.md's hard rules.

deny (exit 2, stderr is the reason): writes to secret files, force push, DROP, TRUNCATE, DELETE
without WHERE, advancing or dropping a replication slot, pg_logical_emit_message, shell writes to
.env, writes to the hooks and settings in this repository's .claude/, a gate stamp written by hand
(a file tool on .verify-stamp, .check-stamp or .review-stamp; a command that names one of them and
is not a plain read; `agent_state.py stamp` or `check` run directly; inline Python that names
agent_state; `agent_state.py tree` and `show` are reads), `make check` with a flag, a variable or
a make or pytest option variable that could stamp failing checks, and `git commit` unless the gate
holds on this working tree. The gate: a full `make verify` always (passed on this
tree, or run right before the commit in the same `&&` chain); and when code changed (not Markdown
and docs/), also `make check` (.check-stamp) and a reviewer verdict other than "return"
(.review-stamp, written by review_stamp.py). A stamp counts when it is fresh for the tree or only
Markdown and docs/ changed since it.
ask (a permission prompt, so the owner's ok is a click): replay and scenarios, source, silver and
other lake writes, Iceberg maintenance and its DAGs, push, rebase, history rewrites, discarded work,
volume, image and recursive deletes, stopped, removed or recreated containers (`make down` as well;
not the scheduler stop of the verify cycle), Kafka topic settings, connector, catalog and Postgres
settings, DDL, actions on GitHub, Windows and WSL settings, edits of the agent roles, skills and
rules and of scripts/agent_state.py, which decides what a stamp means; and a command that shows a
secret: a read of .env (cat, grep, jq, source, a `<` redirect, `$(<.env)`, inline Python and the
like; not .env.example and not `--env-file .env`), `docker compose config` without -q or a listing
flag (--services, --profiles, --images, --volumes), `docker inspect` without a --format or with one
that prints Env or the whole object (`json`, a lone dot, `.Config` with no field), and `env` or
`printenv` run by `docker exec` or `compose exec|run`, or a read of /proc/<pid>/environ.
The match is on the command text, and on the text with each backslash-newline joined too (a
comment ends at the newline, so the joined text can hide a command): the stricter answer wins.
Inline code is code in `-c` or `-e` (after options whose quoted values may hold a `;`), a
here-document or here-string, `-`, `< <(...)`, or the stdin of an interpreter at the end of a pipe
with no script file or module (a wrapper such as `nice -n 5`, `timeout 60`, a redirect or a group
bracket may stand around it). A shell counts only for the stdin forms: a here-document with no
script file, or a pipe. A token scan of each simple command adds what those patterns cannot tell:
an option with a value is not a script file (`bash -euo pipefail`, `-o name`, `--rcfile f`,
`python3 --check-hash-based-pycs never`), `-s` reads the script from stdin whatever follows, `--`
and `-` end the options, a group or `>(...)` after a pipe feeds its commands, and a process
substitution given as the script is code (`python3 <(...)`, `bash <(...)`); node `-p`, `--print`,
`--eval`, perl `-E` and pypy count as inline code. A word that starts with `#` is a comment up
to the next line break (a `;` or `|` does not end it): it is no script file. The scan only adds
to the patterns. A command made only of searches and reads (grep, rg, git log, cat and the like,
no substitution or redirect) runs none of these words and passes, but the secret check runs before
that exit.
If the guard itself fails, or fails on one of the two texts, it asks instead of letting the call
through (a deny of the other text still wins).
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

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
# The guard and its settings (the owner applies changes from a copy, AGENTS.md "Хуки"), the agent
# roles, skills and rules, and the code that says what a stamp means. Only inside this repository:
# a copy in the scratchpad is free to edit.
HARNESS_FILE = re.compile(r"^\.claude/(hooks/|settings(\.local)?\.json$)")
HARNESS_DOC = re.compile(
    r"^(\.claude/(agents/[^/]+|skills/.+)|AGENTS\.md|CLAUDE\.md|docs/agent-rules\.md"
    r"|docs/planning/13-harness\.md|scripts/agent_state\.py)$"
)
# The gate stamps are written by make verify, make check and review_stamp.py, never by the agent.
STAMP_FILE = re.compile(r"^\.(verify|check|review)-stamp$")
STAMP_FIX = "the stamps come from make verify, make check and the reviewer's report"
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
        + r"[^\s;|&\"']*[\"']?(\s+[12]?>>?\s*\S+)*\s*($|[;&|\n])"
        + r"|\bopen\([^)]*"
        + path
    )


SHELL_WRITE_HARNESS = shell_write(r"\.claude/(hooks|settings)")
SHELL_WRITE_RULES = shell_write(
    r"(\.claude/(agents|skills)/|AGENTS\.md|CLAUDE\.md|docs/agent-rules\.md"
    r"|docs/planning/13-harness\.md|scripts/agent_state\.py)"
)
# A gate stamp named by a command that is not a plain read, the stamp code run directly, or inline
# Python that names the module: every form of writing a stamp that the command text shows.
STAMP_NAME = re.compile(r"\.(verify|check|review)-stamp\b")
STAMP_CLI = re.compile(r"\bagent_state(\.py)?[\"']?\s+[\"']?(stamp|check)\b")
# The rest of one simple command, up to a separator outside quotes: the value of an option such as
# `-X 'a;b'` may hold one. The plain run is tried first; the quoted run is the way out when a
# separator in quotes ends it too early.
SEGMENT = r"(?:[^\n;|&]*|(?:[^\n;|&'\"\\]|\\.|'[^']*'|\"[^\"]*\")*)"
# A backslash right before a newline joins the two lines (an even run of backslashes does not).
LINE_CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
# What a pipe may put between itself and the interpreter that reads the piped text as its code: a
# group bracket, a variable, a wrapper with its options (`nice -n 5`, `timeout 60`, `sudo -u x`).
# A word of digits with an optional unit (`5`, `60s`), a wrapper name (`env`, `uv run`) and an
# assignment (`A=1`) are items of their own, never the value of an option (`-a 5`, `-a env`,
# `-a A=1 nice`), so there is one way to split a run of such pairs and a mismatch costs one pass,
# not 2^n (`nice` and 22 pairs of `-a 5` took seconds). A value that only looks like a number
# (`0.5`, `1.5s`, `5x`) is still a value. The pattern was compared with the one before on
# generated forms: none that was denied or asked for before passes now.
WRAPPER_NAMES = r"env|sudo|time|exec|nohup|nice|command|xargs|timeout|stdbuf|setsid|ionice"
WRAPPER_ITEM = r"(?:(?:\d+[smhd]?|" + WRAPPER_NAMES + r"|(?:uv|poetry)\s+run)(?:\s|$))"
WRAPPER_VALUE = r"(?!" + WRAPPER_ITEM + r"|[A-Za-z_]\w*=)[^\s-]\S*"
WRAPPER_ARGS = r"(?:\s+(?:-\S+(?:\s+" + WRAPPER_VALUE + r")?|\d+[smhd]?))*"
CODE_RUNNERS = r"(?:python|pypy)[\d.]*|perl|ruby|node|bash|sh|zsh|dash|ksh"
AFTER_PIPE = (
    r"(?<!\|)\|(?!\|)&?\s*(?:[({]\s*)*"
    r"(?:(?:(?:"
    + WRAPPER_NAMES
    + r"|uv\s+run|poetry\s+run|[A-Za-z_]\w*=\S*)"
    + WRAPPER_ARGS
    + r")\s+)*(?:[\w.-]*/)*"
)
# The interpreter ends its command or goes on with options, a redirect or /dev/stdin: it has no
# script file or module to run, so the piped text is its code (or `-c` takes it from stdin by
# xargs). With a script file or `-m module` the piped text is only its data. `-X` and `-W` take
# the next word as their value.
READS_STDIN = (
    r"(?=(?:\s+(?:-[XW]\s+\S+|-[^\s\-mc]\S*|--\S+))*\s*(?:$|[\n;&|)}]|\d*[<>])"
    r"|\s+-(?:\s|$)|\s+-[a-zA-Z]*c\b|\s+/dev/(?:stdin|fd/0)\b)"
)
INLINE_PYTHON = re.compile(
    r"\bpython[\d.]*\b" + SEGMENT + r"(?:\s-[a-zA-Z]*c\b|<\s*<\()|<<|\bpython[\d.]*\s+-(\s|$)"
    r"|" + AFTER_PIPE + r"python[\d.]*\b" + READS_STDIN
)
# make check stamps the tree it checked: a flag such as -i or -o, a variable, or a make or pytest
# option variable anywhere in the command could make it stamp failing checks.
MAKE_CHECK_ENV = re.compile(r"\b(PYTEST_ADDOPTS|MAKEFLAGS|MFLAGS|GNUMAKEFLAGS)\b")
REDIRECT = re.compile(r"[012]?(>>?|<)&?\S*|&>>?\S*")


def bends_make_check(command: str) -> bool:
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        words = segment.split()
        if "make" not in words:
            continue
        at = words.index("make")
        args = [word for word in words[at + 1 :] if not REDIRECT.fullmatch(word)]
        if "check" in args and (
            args != ["check"]
            or any("=" in word for word in words[:at])
            or MAKE_CHECK_ENV.search(command)
        ):
            return True
    return False


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
    # `make down` runs `compose down`, which the rule above asks for by its own words.
    (
        re.compile(r"\bmake\b[^;&|\n]*\s(start|up|down)(\s|$)|\bcompose\b[^\n;&|]*\sup(\s|$)"),
        "make start and up may recreate spark-bronze or minio (ADR-025 bronze metadata property,"
        " MinIO image), make down removes the stack containers",
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
GIT_READERS = {
    "git log",
    "git show",
    "git diff",
    "git grep",
    "git blame",
    "git status",
    "git check-ignore",
}
SEPARATORS = {"&&", "||", ";", "|"}
NULL_REDIRECT = re.compile(r"[ \t]([12]?>[ \t]*/dev/null|2>&1)(?=[ \t]|$)")
# Substitution, ANSI-C quoting shlex reads differently, a newline that hides a second command.
RUNS_MORE = re.compile(r"\$[(\x27\"]|`|<\(|\n")
# rg --pre and --hostname-bin, git grep -O / --open-files-in-pager (any prefix git accepts) run a
# program; git log and diff --output write a file.
RUNS_PROGRAM = re.compile(r"--pre|--hostname-bin|--op|--output|-[a-zA-Z]*O")

# Showing a secret: a read of .env, the compose file with the values of .env filled in, the Env of
# a container. Checked on the words of each command: `--env-file .env` hands the file to compose
# and `grep .env docs` only searches for the name, neither shows what is in it.
ENV_FILE = re.compile(r"(^|/)\.env(\.(?!example$)[^/]*)?$")
ENV_TEXT = re.compile(r"(?:^|[\s\"'=/(])\.env(?:\.(?!example\b)\w+)?(?![\w.-])")
# `--env-file .env` hands the file to compose; the command does not read it.
ENV_FILE_OPTION = re.compile(r"--env-file[=\s]+\S+")
INTERPRETERS = r"python[\d.]*|perl|ruby|node"
# The code is an argument (`-c`, `-e`), a here-document or here-string, `-` for stdin, a process
# substitution on stdin, or the text of an earlier command of the pipeline. A shell counts only
# when it reads its stdin: `bash -c` is read word by word below.
INLINE_CODE = re.compile(
    r"\b(" + INTERPRETERS + r")\b" + SEGMENT + r"(\s-[a-zA-Z]*[ce]\b|<<|\s-(\s|$)|<\s*<\()"
    r"|(?<![\w.-])(bash|sh|zsh|dash|ksh)\b(?:\s+-\S+)*\s*<<"
    r"|" + AFTER_PIPE + r"(" + INTERPRETERS + r"|bash|sh|zsh|dash|ksh)\b" + READS_STDIN
)
# The text of $(...) and of a backtick pair, which a quoted word hides from the word split.
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
PROC_ENVIRON = re.compile(r"/proc/[^\s/]+/environ")
# Commands that print a file, search it, edit it, or copy it somewhere a later read can reach.
SECRET_READERS = re.compile(
    r"cat|tac|nl|head|tail|less|more|most|cut|sort|uniq|paste|column|fold|rev|grep|egrep|fgrep"
    r"|rg|ag|awk|gawk|mawk|sed|jq|yq|diff|cmp|comm|strings|od|xxd|hexdump|base64|bat|batcat|view"
    r"|vi|vim|nvim|nano|emacs|source|\.|cp|mv|rsync|tar|zip"
)
# The first word after these is the pattern or script, not a file.
PATTERN_FIRST = {"grep", "egrep", "fgrep", "rg", "ag", "awk", "gawk", "mawk", "sed", "jq", "yq"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# Words that run the next command, and keywords that start one.
WRAPPERS = {"sudo", "env", "time", "command", "exec", "nohup", "nice", "xargs"}
KEYWORDS = {"{", "!", "if", "then", "else", "elif", "do", "while", "until"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
DOCKER_VALUE_OPTIONS = {"--config", "--context", "-c", "-H", "--host", "-l", "--log-level"}
COMPOSE_VALUE_OPTIONS = {
    "-f",
    "--file",
    "-p",
    "--project-name",
    "--profile",
    "--env-file",
    "--project-directory",
    "--ansi",
    "--parallel",
    "--progress",
    "--context",
    "-c",
    "-H",
    "--host",
}
CONFIG_LISTINGS = {"-q", "--quiet", "--services", "--profiles", "--images", "--volumes"}
# Options of `exec` and `run` that take a value, so that the word after them is not the container.
EXEC_VALUE_OPTIONS = {
    "-e",
    "--env",
    "-u",
    "--user",
    "-w",
    "--workdir",
    "--index",
    "--detach-keys",
    "--entrypoint",
    "-v",
    "--volume",
    "-p",
    "--publish",
    "--name",
    "-l",
    "--label",
}
# In an action of a docker inspect format: the whole object (a lone dot) or .Config with no field.
WHOLE_OBJECT = re.compile(r"(?<![\w.])\.(?![\w.])|(?<!\w)\.Config(?![\w.])")
SECRET_ENV = "reads .env, which holds every password of the stack (a secret)"
SECRET_ENVIRON = "prints the environment of a process or container, with its passwords (a secret)"
SECRET_CONFIG = (
    "docker compose config prints the passwords of .env (a secret); -q or --services is enough"
)
SECRET_INSPECT = (
    "docker inspect prints the Env of the container with its passwords (a secret);"
    " use --format with fields other than Env"
)


class VerdictError(Exception):
    """A deny or an ask. Raised, so that the check of a command can be run on two texts of it and
    the stricter verdict kept."""

    def __init__(self, kind: str, reason: str, fix: str = "") -> None:
        super().__init__(reason)
        self.kind, self.reason, self.fix = kind, reason, fix

    def emit(self) -> NoReturn:
        if self.kind == "deny":
            print(f"blocked by .claude/hooks/guard.py: {self.reason}; {self.fix}", file=sys.stderr)
            sys.exit(2)
        decision = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": f"AGENTS.md hard rule, needs the owner's ok: {self.reason}",
        }
        print(json.dumps({"hookSpecificOutput": decision}))
        sys.exit(0)


def deny(reason: str, fix: str = "ask the owner for an explicit ok") -> NoReturn:
    raise VerdictError("deny", reason, fix)


def ask(reason: str) -> NoReturn:
    raise VerdictError("ask", reason)


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


def shell_words(command: str) -> tuple[list[list[str]], list[str]] | None:
    """The words of each simple command in the text, and the files a `<` redirect reads. A
    separator, a subshell, a substitution, a backtick or a newline starts a new command. None when
    the quotes do not balance."""
    lexer = shlex.shlex(
        command.replace("\n", " ; ").replace("`", " ( "), posix=True, punctuation_chars=True
    )
    lexer.whitespace_split = True
    lexer.commenters = ""  # bash reads `#` inside a word as text, shlex as a comment
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    stdin_files: list[str] = []
    redirect = ""
    for token in tokens:
        if redirect:  # the word after a redirect operator is its target, not an argument
            if redirect == "<":
                stdin_files.append(token)
            redirect = ""
        elif token and set(token) <= set("();<>|&"):  # an operator; a quoted `f(x)` is a word
            if set(token) <= set("<>&") and set(token) & set("<>"):
                redirect = token
            else:
                segments.append([])
        else:
            segments[-1].append(token)
    return segments, stdin_files


def subcommand(args: list[str], value_options: set[str]) -> int | None:
    """Index of the first word that is not an option or the value of one."""
    skip = False
    for at, arg in enumerate(args):
        if skip:
            skip = False
        elif arg in value_options:
            skip = True
        elif not arg.startswith("-"):
            return at
    return None


def format_prints_env(text: str) -> bool:
    """A docker inspect format that prints Env, or the whole object or its Config, which hold it:
    `json` (the shortcut for the whole object), a lone dot, `.Config` with no field after it."""
    if text.strip() == "json" or re.search(r"\bEnv\b", text):
        return True
    return any(WHOLE_OBJECT.search(action) for action in re.findall(r"\{\{(.*?)\}\}", text))


def inspect_prints_env(options: list[str]) -> bool:
    """`docker inspect` options: no --format, or one that prints Env or the whole object."""
    formats = []
    for at, option in enumerate(options):
        if option in ("-f", "--format") and at + 1 < len(options):
            formats.append(options[at + 1])
        elif option.startswith("--format="):
            formats.append(option.removeprefix("--format="))
        elif option.startswith("-f") and not option.startswith("--"):
            formats.append(option[2:])
    return not formats or any(format_prints_env(text) for text in formats)


def prints_environment(words: list[str]) -> bool:
    """The command given to a container prints its environment: printenv, env with no command to
    run, or a shell script that does either."""
    if not words:
        return False
    name, args = words[0], words[1:]
    if name == "printenv":
        return True
    if name == "env":
        return not [arg for arg in args if not arg.startswith("-") and "=" not in arg]
    script = next(
        (at for at, arg in enumerate(args[:-1]) if re.fullmatch(r"-[a-zA-Z]*c", arg)), None
    )
    if name in SHELLS and script is not None:
        return bool(
            re.search(r"(?:^|[;&|(]\s*)(?:printenv\b|env\s*(?:$|[;&|)]))", args[script + 1])
        )
    return False


def exec_prints_environment(args: list[str]) -> bool:
    """The words after `exec` or `run`: options, the container or service, then its command."""
    at = subcommand(args, EXEC_VALUE_OPTIONS)
    return at is not None and prints_environment(args[at + 1 :])


def secret_in_segment(words: list[str]) -> str | None:
    wrapped = False
    while words:
        word = words[0]
        if word in WRAPPERS:
            wrapped = True
        elif not (word in KEYWORDS or ASSIGNMENT.match(word) or (wrapped and word[:1] == "-")):
            break
        del words[0]
    if not words:
        return None
    name, args = words[0], words[1:]
    script = next(
        (at for at, arg in enumerate(args[:-1]) if re.fullmatch(r"-[a-zA-Z]*c", arg)), None
    )
    if name in SHELLS and script is not None:
        return secret_shown(args[script + 1])
    if name == "eval":
        return secret_shown(" ".join(args))
    if SECRET_READERS.fullmatch(name):
        files = [arg for arg in args if not arg.startswith("-")]
        if name in PATTERN_FIRST and not any(arg in ("-f", "--file") for arg in args):
            files = files[1:]
        return SECRET_ENV if any(ENV_FILE.search(file) for file in files) else None
    if name in ("docker-compose", "$COMPOSE", "${COMPOSE}"):
        return compose_secret(args)
    if name == "docker":
        at = subcommand(args, DOCKER_VALUE_OPTIONS)
        if at is None:
            return None
        sub, rest = args[at], args[at + 1 :]
        if sub == "container" and rest[:1] == ["inspect"]:
            sub, rest = "inspect", rest[1:]
        if sub == "compose":
            return compose_secret(rest)
        if sub == "inspect" and inspect_prints_env(rest):
            return SECRET_INSPECT
        if sub == "exec" and exec_prints_environment(rest):
            return SECRET_ENVIRON
    return None


def compose_secret(args: list[str]) -> str | None:
    at = subcommand(args, COMPOSE_VALUE_OPTIONS)
    if at is None:
        return None
    sub, rest = args[at], args[at + 1 :]
    if sub in ("config", "convert"):
        return None if CONFIG_LISTINGS & set(rest) else SECRET_CONFIG
    if sub in ("exec", "run") and exec_prints_environment(rest):
        return SECRET_ENVIRON
    return None


# The token scan below finds the inline code the regexes above cannot: it reads the words of each
# simple command, so an option with a value, `--`, `-s`, a group after a pipe and a process
# substitution are told from a script file. It only adds to the regexes.
PUNCTUATION = re.compile(r"\|&|\|\||&&|;;|<<<|<<|<\(|>\(|&>>?|>>|>&|<&|>\||[();<>|&]")
REDIRECTS = {"<", "<<", "<<<", ">", ">>", ">&", "<&", "&>", "&>>", ">|"}
PIPE_TOKENS = {"|", "|&"}
PROCESS_SUBSTITUTION = "\0<("
STDIN_FILES = {"/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
RUNNER_WRAPPERS = WRAPPERS | {"timeout", "stdbuf", "setsid", "ionice"}
WRAPPER_VALUE_WORD = re.compile(r"(?:[\w.-]*/)*(?:" + CODE_RUNNERS + r")\b")


class Flavor:
    """What the options of one kind of interpreter mean for the text on its stdin."""

    def __init__(
        self,
        code: str = "",
        module: str = "",
        value: str = "",
        long_code: tuple[str, ...] = (),
        long_value: tuple[str, ...] = (),
    ) -> None:
        # code: flag letters whose command takes the code, module: flag letters that run a module
        # (stdin stays data), value: flag letters that take a value (glued or the next word),
        # long_code and long_value: the same for the `--name` options.
        self.code, self.module, self.value = code, module, value
        self.long_code, self.long_value = long_code, long_value


FLAVORS = {
    "python": Flavor(code="c", module="m", value="XW", long_value=("--check-hash-based-pycs",)),
    "node": Flavor(
        code="pe",
        value="rC",
        long_code=("--eval", "--print"),
        long_value=("--require", "--import", "--loader", "--experimental-loader", "--conditions"),
    ),
    "perl": Flavor(code="eE", value="I"),
    "ruby": Flavor(code="e", value="rICEF"),
    "shell": Flavor(long_value=("--rcfile", "--init-file")),
}


def runner_flavor(name: str) -> str | None:
    base = name.rsplit("/", 1)[-1]
    if re.fullmatch(r"(?:python|pypy)[\d.]*", base):
        return "python"
    if base in ("node", "perl", "ruby"):
        return base
    return "shell" if base in SHELLS else None


def command_start(words: list[str]) -> int | None:
    """Index of the command word: past assignments, keywords, wrappers and their options."""
    at, wrapped = 0, False
    while at < len(words):
        word = words[at]
        if word in RUNNER_WRAPPERS or (
            word in ("uv", "poetry") and words[at + 1 : at + 2] == ["run"]
        ):
            wrapped, at = True, at + (2 if word in ("uv", "poetry") else 1)
        elif (
            word in KEYWORDS
            or ASSIGNMENT.match(word)
            or (wrapped and re.fullmatch(r"\d+[smhd]?", word))
        ):
            at += 1
        elif wrapped and word.startswith("-") and word != "-":
            at += 1
            nxt = words[at] if at < len(words) else "-"
            if (
                "=" not in word
                and not nxt.startswith("-")
                and nxt not in RUNNER_WRAPPERS | {"uv", "poetry"}
                and not WRAPPER_VALUE_WORD.match(nxt)
            ):
                at += 1
        else:
            return at
    return None


def reads_code_from_stdin(flavor: str, args: list[str], stdin_open: bool) -> bool:
    """The words after an interpreter: does its code come from stdin (or from a process
    substitution), with no script file or module before it? stdin_open: a pipe or a here-document
    feeds it. An option that takes a value, `--`, a glued option cluster such as `-euo` are read as
    the interpreter reads them."""
    rules = FLAVORS[flavor]
    shell = flavor == "shell"
    at = 0
    while at < len(args):
        word = args[at]
        at += 1
        if word == PROCESS_SUBSTITUTION or word == "-":
            return True
        if word == "--":
            if at == len(args):
                return stdin_open
            return args[at] in ("-", PROCESS_SUBSTITUTION)
        if word.startswith("--"):
            name, glued, _ = word.partition("=")
            if name in rules.long_code:
                return True
            if name in rules.long_value and not glued:
                at += 1
            continue
        if word[:1] == "-" or (shell and word[:1] == "+" and len(word) > 1):
            for place, letter in enumerate(word[1:], 1):
                if letter in rules.code:
                    return True
                if letter in rules.module or (shell and letter == "c"):
                    return False
                if shell and letter == "s":
                    return stdin_open
                if shell and letter in "oO":
                    at += 1
                elif letter in rules.value:
                    if place + 1 == len(word):  # the value is the next word
                        at += 1
                    break
            continue
        return stdin_open and word in STDIN_FILES
    return stdin_open


def strip_comments(command: str) -> str:
    """The text without its comments: an unquoted word that starts with `#` runs to the next line
    break, which stays (`;`, `|` and `&` do not end it). A `#` in a word or in quotes is text."""
    out: list[str] = []
    quote = ""
    at = 0
    while at < len(command):
        char = command[at]
        if char == "\\" and quote != "'":
            out.append(command[at : at + 2])
            at += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (not out or out[-1][-1] in " \t\n;&|()<>"):
            while at < len(command) and command[at] != "\n":
                at += 1
            continue
        out.append(char)
        at += 1
    return "".join(out)


def scan_commands(command: str) -> list[tuple[list[str], bool, bool]] | None:
    """Each simple command of the text as (words, fed by a pipe or a group after one, has a
    here-document, here-string or `< <(...)`). None when the quotes do not balance. A group, a
    subshell, a substitution and a backtick pair are scanned as commands of their own; the
    commands of a group that follows a pipe, and of `>(...)`, count as fed by it."""
    backticks = 0

    def swap(_: re.Match[str]) -> str:
        nonlocal backticks
        backticks += 1
        return " ( " if backticks % 2 else " ) "

    lexer = shlex.shlex(
        re.sub("`", swap, strip_comments(command).replace("\n", " ; ")),
        posix=True,
        punctuation_chars=True,
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    items: list[tuple[bool, str]] = []
    for token in tokens:
        if set(token) <= set("();<>|&"):
            items.extend((True, operator) for operator in PUNCTUATION.findall(token))
        else:
            items.append((False, token))
    found: list[tuple[list[str], bool, bool]] = []
    # What a group or a substitution suspends while its own commands are scanned.
    frames: list[tuple[list[str], bool, bool, bool]] = []
    words: list[str] = []
    piped = group_piped = heredoc = False
    redirect = ""

    def finish() -> None:
        if words:
            found.append((list(words), piped, heredoc))

    for is_operator, text in items:
        previous, redirect = redirect, ""
        if not is_operator or (previous and text not in ("<(", ">(")):
            if previous:  # the target of a redirect is not an argument
                continue
            if text == "{" and not words:
                frames.append((words, heredoc, piped, group_piped))
                words, heredoc, group_piped = [], False, piped
            elif text == "}" and not words and frames:
                words, heredoc, piped, group_piped = frames.pop()
            else:
                words.append(text)
        elif text in REDIRECTS:
            if words and words[-1].isdigit():
                words.pop()  # the file descriptor of `2>&1`
            heredoc = heredoc or text in ("<<", "<<<")
            redirect = text
        elif text in ("<(", ">(", "("):
            if text == "<(" and previous == "<":
                heredoc = True
            elif text == "<(":
                words.append(PROCESS_SUBSTITUTION)
            frames.append((words, heredoc, piped, group_piped))
            fed = {"<(": False, ">(": True, "(": piped}[text]
            words, heredoc, piped, group_piped = [], False, fed, fed
        elif text == ")":
            finish()
            if frames:
                words, heredoc, piped, group_piped = frames.pop()
            else:
                words, heredoc, piped = [], False, group_piped
        else:
            finish()
            words, heredoc = [], False
            piped = text in PIPE_TOKENS or group_piped
    finish()
    return found


def stdin_code_runners(command: str) -> set[str]:
    """The interpreters (python, node, perl, ruby, shell) that run the text they read from stdin
    or from a process substitution as code, in the commands of this text."""
    commands = scan_commands(command)
    if commands is None:  # the quotes do not balance: any such name counts
        names = re.finditer(r"\b(?:" + CODE_RUNNERS + r")\b", command)
        return {runner_flavor(found[0]) or "shell" for found in names}
    kinds: set[str] = set()
    for words, piped, heredoc in commands:
        at = command_start(words)
        if at is None:
            continue
        flavor = runner_flavor(words[at])
        if flavor and reads_code_from_stdin(flavor, words[at + 1 :], piped or heredoc):
            kinds.add(flavor)
    return kinds


def secret_shown(command: str) -> str | None:
    """Why the command shows a secret (the reason for the owner), None when it does not."""
    if PROC_ENVIRON.search(command):
        return SECRET_ENVIRON
    text = ENV_FILE_OPTION.sub(" ", command)
    if ENV_TEXT.search(text) and (INLINE_CODE.search(text) or stdin_code_runners(text)):
        return SECRET_ENV
    for found in SUBSTITUTION.finditer(command):
        reason = secret_shown(found[1] or found[2] or "")
        if reason:
            return reason
    parsed = shell_words(command)
    if parsed is None:
        return SECRET_ENV if ENV_TEXT.search(text) else None
    segments, stdin_files = parsed
    if any(ENV_FILE.search(file) for file in stdin_files):
        return SECRET_ENV
    for segment in segments:
        reason = secret_in_segment(segment)
        if reason:
            return reason
    return None


def commit_gap(low: str) -> list[str]:
    """What a `git commit` still lacks on this working tree, empty when it may go ahead: a full
    verify always, and for changed code also a check and a reviewer verdict that is not `return`."""
    from scripts.agent_state import (
        ACCEPTED,
        Stamp,
        code_changes,
        code_changes_since,
        read_stamp,
        tree_hash,
    )

    current = tree_hash(ROOT)

    def covers(stamp: Stamp | None) -> bool:
        # The same rule as stop_gate.py: a stamp covers the tree it was written on and any tree
        # that differs from it only in Markdown and docs/.
        if stamp is None:
            return False
        try:
            return stamp.fresh or not code_changes_since(ROOT, stamp, current)
        except subprocess.CalledProcessError:  # the stamped tree is gone from the object store
            return False

    missing = []
    verify = read_stamp(ROOT, "verify", current)
    if not VERIFY_THEN_COMMIT.search(low) and not (
        verify is not None and verify.mode == "full" and covers(verify)
    ):
        missing.append("a full make verify")
    if not code_changes(ROOT):
        return missing
    if not covers(read_stamp(ROOT, "check", current)):
        missing.append("make check")
    review = read_stamp(ROOT, "review", current)
    if review is None or not covers(review):
        missing.append("a reviewer verdict")
    elif review.mode not in ACCEPTED:
        missing.append("a reviewer verdict other than 'return'")
    return missing


def listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


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
        if inside is not None and STAMP_FILE.search(inside):
            deny(f"writes a gate stamp by hand: {path}", STAMP_FIX)
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
    verdicts: list[VerdictError] = []
    for text in dict.fromkeys([LINE_CONTINUATION.sub(r"\1", command), command]):
        try:
            check_bash(text)
        except VerdictError as verdict:
            verdicts.append(verdict)
        except Exception as error:  # the other text may still deny
            verdicts.append(
                VerdictError(
                    "ask",
                    f"guard.py failed ({error.__class__.__name__}: {error}),"
                    " check the call by hand",
                )
            )
    if verdicts:
        raise next((v for v in verdicts if v.kind == "deny"), verdicts[0])


def check_bash(command: str) -> None:
    if reads_only(command):
        # The one read that is not free: its words are data, but the file it opens is a secret.
        secret = secret_shown(command)
        if secret:
            ask(secret)
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
    if (
        STAMP_NAME.search(command)
        or STAMP_CLI.search(command)
        or (
            "agent_state" in command
            and (INLINE_PYTHON.search(command) or "python" in stdin_code_runners(command))
        )
    ):
        deny("writes a gate stamp by hand", STAMP_FIX)
    if bends_make_check(command):
        deny("runs make check in a form that can stamp failing checks", "run plain make check")
    if COMMIT.search(low):
        missing = commit_gap(low)
        if missing:
            deny(
                f"git commit without {listed(missing)} on this working tree",
                "see docs/planning/13-harness.md, section 5",
            )
    if SHELL_WRITE_RULES.search(command):
        ask("edits the agent roles or rules")
    secret = secret_shown(command)
    if secret:
        ask(secret)
    for pattern, reason in ASK:
        if pattern.search(low):
            ask(reason)


try:
    check(json.load(sys.stdin))
except VerdictError as verdict:
    verdict.emit()
except Exception as error:  # a broken guard must not wave the call through
    VerdictError(
        "ask", f"guard.py failed ({error.__class__.__name__}: {error}), check the call by hand"
    ).emit()
sys.exit(0)
