#!/usr/bin/env python3
"""PreToolUse guard for AGENTS.md's hard rules.

It reads the text of a command, so it catches a mistake in the usual form, not a bypass
(docs/planning/13-harness.md, section 2): a renamed, encoded or split command, or a script written
first and run later, is forbidden by the rules and is not looked for here.

deny (exit 2, stderr is the reason): writes to secret files, force push, DROP, TRUNCATE, DELETE
without WHERE, advancing or dropping a replication slot, pg_logical_emit_message, shell writes to
.env, writes to the hooks and settings in this repository's .claude/, a gate stamp written by hand
(a file tool on .verify-stamp, .check-stamp or .review-stamp; a command that names one of them and
is not a read; `agent_state.py stamp` or `check` run directly; Python that names agent_state and one
of its writers; `agent_state.py tree` and `show` are reads), and `git commit` unless the gate holds
on this working tree. The gate asks for as many stamps as the change proves, by the highest
`gate_level` of the changed paths: Markdown and docs/ nothing; tests, CI, agent files and lint
configs `make check` (.check-stamp) and a reviewer verdict other than "return" (.review-stamp,
written by review_stamp.py); other code also a verify of any mode (.verify-stamp) or a
`make verify &&` chain right before the commit (`make verify-fast &&` below the full level); a
command other than a read, `git add`, `cd`, `make verify` or `make check` before the commit in
the same text is refused, since the gate sees the tree as it is before the text runs;
streaming/ and contracts/
a full `make verify`. A stamp counts when no path at or above its floor changed since its tree
(`uncovered`): the `verify` level for the verify stamp, the `check` level for the others; a stamp
whose tree is gone from the object store covers nothing.
ask (a permission prompt, so the owner's ok is a click): replay and scenarios, source, bronze,
silver, gold and other lake writes, Iceberg maintenance and its DAGs, push, rebase, history
rewrites, discarded work (`checkout -- path`, `switch -f`), volume, image and recursive deletes
(`find -delete` too), stopped, removed or recreated containers (`make down` as well; not the
scheduler stop of the verify cycle, when the scheduler is the only target), Kafka topic settings,
connector, catalog and Postgres settings (a publication too), DDL, actions on GitHub, Windows and
WSL settings, edits of the agent roles, skills and rules and of scripts/agent_state.py, which
decides what a stamp means; and a command that shows a secret: a read of .env (cat, grep, jq,
source, a `<` redirect, `$(<.env)` and the like; not .env.example and not `--env-file .env`), the
name .env in a command with an interpreter or `eval` (it may read the file), `docker compose
config` without -q or a listing flag (--services, --profiles, --images, --volumes), `docker
inspect` without a --format or with one that prints Env or the whole object (`json`, a lone dot,
`.Config` with no field), and `env` or `printenv` run by `docker exec` or `compose exec|run`, or a
read of /proc/<pid>/environ.
The words are checked in the commands that run something. The text is cut into commands at
separators outside quotes (a newline in quotes does not end one), a comment is dropped as bash
does, and the lines of a here-document belong to the command that has the `<<` (the last
command of its line may be another one). A command made
only of searches and reads (grep, rg, echo, cat, git log and the like, no substitution or
redirect) runs none of the words in it, so they are data, unless a command after it in the same
pipeline runs the text (`echo "drop table t" | psql`; every command of a group `( ... )` or
`{ ...; }` before a pipe feeds it). The quoted message of `git commit -m` is data too (cut
inside that one command, also in a chain) when it has no substitution. Two more are data only
when the whole text is that one simple command, with no `;`, `&&`, `||`, `|`, `&` or second
command: the body of a here-document that a `cat` writes to a file (and the body only when the
delimiter is quoted or it has no `$(...)` or backtick), and the message that is
`"$(cat <<'EOF' ... EOF)"`. In a longer text they are read as any command is.
The scan gives way where it does not model the text: with a substitution, a process
substitution, a compound command (`for`, `while`, `if`, `case`, `eval`...), a here-document of a
command other than `cat`, a redirect between the bracket of a group and its pipe, or quotes that
do not balance, no read is data and the whole text is the text that runs, as for any command.
The rules for writes to .env, the hooks, the rules and the stamp code read the whole text when
something runs (a stamp name only in the commands that run). The secret check looks at the
whole command, and the connector and catalog HTTP rule at the whole text that runs something.
The match is on the command text, and on the text with each backslash-newline joined too (a
comment ends at the newline, so the joined text can hide a command): the stricter answer wins.
If the guard itself fails, or fails on one of the two texts, it asks instead of letting the call
through (a deny of the other text still wins).
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

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
    + r"|--?\w[\w-]*(=\S+)?))*\s+[\"']?"
)
FORCE_PUSH = re.compile(GIT + r"push\b[^\n;&|]*(\s--force(-with-lease)?\b|\s-[a-z]*f\b|\s\+\S)")
DROP = re.compile(r"\bdrop\s+(table|view|schema|namespace|database|materialized\s+view)\b")
TRUNCATE = re.compile(r"\btruncate\s+(table\s+)?[a-z_\"][\w.\"]*")
DELETE = re.compile(r"\bdelete\s+from\s+[\w.\"]+([^;]*)")
# Moving the slot past records skips them for good; dropping it forces a new initial snapshot.
SLOT_SKIP = re.compile(r"\bpg_(replication_slot_advance|drop_replication_slot)\b")
# A file named `.env`, not any `*.env`: docker/airflow/airflow.env is no secret file.
SHELL_WRITE_ENV = re.compile(
    r"(>>?|\btee\b(\s+-a)?)\s*[\"']?([^\s;|&]*/)?\.env\b(?!\.example)"
    r"|\bsed\b[^\n;|&]*\s-i\S*[^\n;|&]*(?<![\w.-])\.env\b(?!\.example)"
    r"|\b(cp|mv|install|ln)\b[^\n;|&]*\s[\"']?([^\s;|&]*/)?\.env(\.(?!example\b)[^\s;|&\"']*)?[\"']?"
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
    """A shell command that writes, moves or removes a file of this repository matching target.
    `open(path)` counts only with a mode that writes (a `w`, `a`, `x` or `+` in the mode, given
    second or as `mode=`): a read of the file is no edit."""
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
        + r"[^)]*(?:,\s*[\"'][^\"')]*[wax+]|\bmode\s*=\s*[\"'][^\"')]*[wax+])"
    )


SHELL_WRITE_HARNESS = shell_write(r"\.claude/(hooks|settings)")
SHELL_WRITE_RULES = shell_write(
    r"(\.claude/(agents|skills)/|AGENTS\.md|CLAUDE\.md|docs/agent-rules\.md"
    r"|docs/planning/13-harness\.md|scripts/agent_state\.py)"
)
# A gate stamp named by a command that is not a read, the stamp code run directly, or Python that
# names the module and one of the functions that write a stamp.
STAMP_NAME = re.compile(r"\.(verify|check|review)-stamp\b")
STAMP_CLI = re.compile(r"\bagent_state(\.py)?[\"']?\s+[\"']?(stamp|check)\b")
STAMP_WRITERS = re.compile(r"\b(write_stamp|record_review|_store|run_check)\b")
PYTHON = re.compile(r"\b(python|pypy)[\d.]*\b")
# A backslash right before a newline joins the two lines (an even run of backslashes does not).
LINE_CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
# A here-document: `<<` or `<<-` and its delimiter, quoted (`'EOF'`, `"EOF"`, `\EOF`) or not. The
# lines up to the delimiter belong to the command that has the `<<`, not to a command of their
# own. A quoted delimiter turns off expansion in the body, and the body of a `cat` that writes
# to a file is then data; an unquoted one expands `$(...)` and backticks, which run. Only a
# delimiter that is one word is read (`<<END-NOTES` is not), and a body counts as data only when
# its delimiter line is found; otherwise the lines are checked as commands (stricter).
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(?:'(\w+)'|\"(\w+)\"|(\\?)(\w+))(?=[\s;&|<>()]|$)")
# Compound commands: the scan reads their words one command at a time and does not follow what
# they group, so a text that has one takes no read as data.
COMPOUND = {
    "for", "while", "until", "if", "then", "else", "elif", "fi", "case", "esac", "select",
    "function", "do", "done", "eval",
}  # fmt: skip
# The quoted message of `git commit -m` (several -m are several messages), and the message that
# is `"$(cat <<'EOF' ... EOF)"`. Both are cut inside the one command they belong to.
COMMIT_MESSAGE = re.compile(
    r"(?P<head>\s(?:-[a-zA-Z]*m|--message)[\s=]*)(?P<message>\"(?:[^\"\\]|\\.)*\"|'[^']*')"
)
CAT_MESSAGE = re.compile(
    r"(?P<head>\s(?:-[a-zA-Z]*m|--message)[\s=]*)"
    r"\"\$\(\s*cat\s*<<-?\s*(?P<quote>['\"]?)(?P<delimiter>\w+)(?P=quote)[ \t]*\n"
    r"(?:.*?\n)?[ \t]*(?P=delimiter)[ \t]*\n?[ \t]*\)\"",
    re.S,
)
# The Debezium connector (8083) and the Lakekeeper catalog (8181) change by any HTTP write, with
# the address anywhere in the text (`C=...:8083/x; curl -X PUT $C/y`).
HTTP_WRITE = r"(?=[^\n]*:(8083|8181)/)[^\n]*"
COMMIT = re.compile(GIT + r"commit\b")

ASK = [
    (
        re.compile(
            r"\bmake\b[^;&|\n]*\s(replay-burst|replay-start|replay-live|replay-reset|replay-load|"
            r"silver|bootstrap|nuke|iceberg-demo|chaos-[\w-]+|cdc-snapshot|migrate|"
            r"watermark-demo|watermark-live)(?=[\s;&|<>()]|$)"
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
    (re.compile(r"\brm\s+(-[a-z]*r|--recursive)|\bfind\b[^\n;&|]*\s-delete\b"), "recursive delete"),
    (
        re.compile(
            GIT + r"(clean\b[^\n;&|]*\s-[a-z]*f"
            r"|checkout\b[^\n;&|]*\s(--|-f|--force|\.)(?=[\s;&|<>()]|$)|restore\b"
            r"|switch\b[^\n;&|]*\s(-f|--force|--discard-changes)\b"
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
    # `compose` also catches $COMPOSE, the Makefile's name for the compose command. The scheduler
    # stop of the verify cycle is free only when the scheduler is the one target.
    (
        re.compile(
            r"\b(docker|compose)\b(?![^\n;&|]*\bexec\b)[^\n;&|]*\s(down|rm|container\s+(rm|prune))\b"
            r"|\b(docker|compose)\b(?![^\n;&|]*\bexec\b)[^\n;&|]*\s(stop|kill|restart|pause)\b"
            r"(?!\s+airflow-scheduler\s*(?:$|[;&|\n]))"
        ),
        "stops or removes stack containers (the scheduler stop of the verify cycle is free)",
    ),
    # A changed image recreates spark-bronze, and its start sets the bronze metadata property.
    # `make down` runs `compose down`, which the rule above asks for by its own words.
    (
        re.compile(
            r"\bmake\b[^;&|\n]*\s(start|up|down)(?=[\s;&|<>()]|$)"
            r"|\bcompose\b[^\n;&|]*\sup(?=[\s;&|<>()]|$)"
        ),
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
        re.compile(r"scripts/lakekeeper/(protect|register|bootstrap)\.sh|connect/register\.sh"),
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
            r"|\b(create|alter|drop)\s+(publication|subscription)\b|\balter\s+(role|database)\b"
            r"|\bpg_(terminate_backend|create_logical_replication_slot)\b"
        ),
        "writes to the source database or its replication setup",
    ),
    (
        re.compile(
            r"\b(insert\s+into|update|delete\s+from|merge\s+into)\s+\"?(lake\.)?\"?"
            r"(bronze|silver|gold)\"?\."
        ),
        "writes to bronze, silver or gold by hand (silver only through make silver, gold only dbt)",
    ),
    (
        re.compile(
            r"\b(powercfg|wsl|powershell|pwsh)\.exe\b|\bpowercfg\b|\bwsl\s+--|\.wslconfig\b"
        ),
        "Windows and WSL settings are the owner's",
    ),
    (re.compile(r"\balter\s+system\b"), "changes Postgres settings"),
    # `show create table` reads the DDL; it does not write it.
    (
        re.compile(r"(?<!show )\b(alter|create)\s+(table|schema|view|namespace)\b"),
        "DDL outside migrations",
    ),
]

HTTP_ASK = re.compile(
    HTTP_WRITE + r"(-x\s*|--request[\s=]*)(post|put|patch|delete)\b"
    r"|" + HTTP_WRITE + r"\s(-d|--data(-raw|-binary|-urlencode)?|--json)[\s=]"
)

READERS = {
    "cd", "ls", "cat", "head", "tail", "wc", "cut", "nl", "grep", "egrep", "fgrep", "rg",
    "echo", "printf", "stat", "test", "[", "file", "du", "diff", "pwd", "true", "realpath",
}  # fmt: skip
GIT_READERS = {
    "git log",
    "git show",
    "git diff",
    "git grep",
    "git blame",
    "git status",
    "git check-ignore",
}
NULL_REDIRECT = re.compile(r"[ \t]([12]?>[ \t]*/dev/null|2>&1)(?=[ \t]|$)")
# Substitution, ANSI-C quoting shlex reads differently: a command inside the text runs words that
# no word split shows.
RUNS_MORE = re.compile(r"\$[(\x27\"]|`|[<>]\(")
# rg --pre and --hostname-bin, git grep -O / --open-files-in-pager (any prefix git accepts) run a
# program; git log and diff --output write a file.
RUNS_PROGRAM = re.compile(r"--pre|--hostname-bin|--op|--output|-[a-zA-Z]*O")
OPERATORS = set("();<>|&")
LONE_PIPE = re.compile(r"(?<!\|)\|(?!\|)")

# Showing a secret: a read of .env, the compose file with the values of .env filled in, the Env of
# a container. Checked on the words of each command: `--env-file .env` hands the file to compose
# and `grep .env docs` only searches for the name, neither shows what is in it.
ENV_FILE = re.compile(r"(^|/)\.env(\.(?!example$)[^/]*)?$")
ENV_TEXT = re.compile(r"(?:^|[\s\"'=/(])\.env(?:\.(?!example\b)\w+)?(?![\w.-])")
# `--env-file .env` hands the file to compose; the command does not read it.
ENV_FILE_OPTION = re.compile(r"--env-file[=\s]+\S+")
# An interpreter, a shell or `eval` in the same text as the name .env: it may read the file by a
# name the words do not show (a variable, a pipe, a path built in code).
INTERPRETER = re.compile(
    r"(?<![\w./-])(?:[\w.-]*/)*(python|pypy|perl|ruby|node|bash|sh|zsh|dash|ksh|eval)[\d.]*(?![\w.-])"
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


PIPES = ("|", "|&")


class Command(NamedTuple):
    text: str  # as written, with the comments and the message of a commit gone
    words: list[str]
    piped: bool  # a pipe follows: the next command reads its output
    read: bool  # a search or a read whose words nothing runs
    end: str  # the operator after it: `;`, `&&`, `|`, a newline, a bracket, empty at the end


def is_read(words: list[str]) -> bool:
    """A search or a read: no redirect, subshell or program to run."""
    return (words[0] in READERS or " ".join(words[:2]) in GIT_READERS) and not any(
        set(word) <= OPERATORS or RUNS_PROGRAM.match(word) for word in words
    )


def heredoc_end(text: str, start: int, delimiter: str) -> tuple[int, int]:
    """Where the body of a here-document that starts at `start` ends: the start of the delimiter
    line, and the end of that line (the end of the text when there is none)."""
    line_start = start
    while line_start < len(text):
        line_end = text.find("\n", line_start)
        line_end = len(text) if line_end < 0 else line_end
        if text[line_start:line_end].strip() == delimiter:
            return line_start, line_end
        line_start = line_end + 1
    return len(text), len(text)


def scan(text: str) -> list[tuple[str, str]] | None:
    """The text cut into commands, each with the operator that ends it: `;`, `&&`, `||`, `|`,
    `|&`, `&`, a bracket, a backtick or a newline, outside quotes. A comment (a word that starts
    with `#`, outside quotes) runs to the line break and is dropped. A backslash before a line
    break joins the lines. The lines of a here-document, up to its delimiter, stay in the command
    that has the `<<` (not in the last command of the line): no comment is dropped in them and no
    quote counts; the body is cut only when that command is a `cat` that writes a file (the `>`
    in the same command), the body is data (a quoted delimiter, or no substitution in it) and
    the text is that one command: no command before it, one here-document, nothing after it.
    None when the quotes do not balance."""
    parts: list[tuple[str, str]] = []
    current: list[str] = []
    # Here-documents whose body starts at the next newline: delimiter, quoted, and the number of
    # the command that has the `<<` (the commands cut so far).
    pending: list[tuple[str, bool, int]] = []
    quote = ""
    at = 0
    while at < len(text):
        char = text[at]
        last = current[-1][-1:] if current else ""
        if quote:
            if char == "\\" and quote == '"':
                current.append(text[at : at + 2])
                at += 2
                continue
            quote = "" if char == quote else quote
        elif char == "\\":
            current.append(" " if text[at + 1 : at + 2] == "\n" else text[at : at + 2])
            at += 2
            continue
        elif char in "'\"":
            quote = char
        elif char == "#" and (not last or last in " \t\n;|&()<>`"):
            line_end = text.find("\n", at)
            at = len(text) if line_end < 0 else line_end
            continue
        elif char == "<" and last != "<" and (heredoc := HEREDOC.match(text, at)):
            pending.append(
                (
                    heredoc[2] or heredoc[3] or heredoc[5],
                    bool(heredoc[2] or heredoc[3] or heredoc[4]),
                    len(parts),
                )
            )
            current.append(heredoc[0])
            at = heredoc.end()
            continue
        elif char == "\n" and pending:
            line = "".join(current)
            body_start = at + 1
            for delimiter, quoted, owner in pending:
                body_end, after = heredoc_end(text, body_start, delimiter)
                body = text[body_start:body_end]
                own = line if owner == len(parts) else ""  # still the command with the `<<`
                writes_file = re.match(r"\s*cat\b", own) and ">" in own
                # Data only when the text is that one command and nothing else.
                alone = not parts and len(pending) == 1 and not text[after:].strip()
                found = body_end < len(text)  # the delimiter line exists
                data = found and alone and writes_file and (quoted or not RUNS_MORE.search(body))
                piece = "\n" + ("" if data else body) + text[body_end:after]
                if owner == len(parts):
                    current.append(piece)
                else:  # the body belongs to an earlier command of the line
                    parts[owner] = (parts[owner][0] + piece, parts[owner][1])
                body_start = after + 1
            pending = []
            at = after  # the newline after the delimiter ends the command
            continue
        elif char in ";\n()`" or char in "|&":  # an operator; a quoted `f(x)` is a word
            if char == "&" and ((last and last in "<>") or text[at + 1 : at + 2] == ">"):
                current.append(char)  # the `&` of `2>&1` and `&>`
                at += 1
                continue
            pair = text[at : at + 2]
            operator = pair if pair in ("&&", "||", "|&") else char
            parts.append(("".join(current), operator))
            current = []
            at += len(operator)
            continue
        current.append(char)
        at += 1
    if quote:  # unbalanced quotes: the commands are unknown, the caller reads the whole text
        return None
    parts.append(("".join(current), ""))
    return parts


def words_of(text: str) -> list[str]:
    lexer = shlex.shlex(NULL_REDIRECT.sub(" ", text), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # bash reads `#` inside a word as text, shlex as a comment
    try:
        return list(lexer)
    except ValueError:
        return text.split()


def without_message(text: str, alone: bool = False) -> str:
    """The command of one `git commit` without its messages: the quoted text after `-m` or
    `--message`, and, when the text is that one command (`alone`), the message that is
    `"$(cat <<'EOF' ... EOF)"`. A message with another substitution runs it and stays."""
    if not COMMIT.search(text.lower()):  # `git -C dir commit`: the pattern reads lower case
        return text

    def cat_message(found: re.Match[str]) -> str:
        expands = not found["quote"] and RUNS_MORE.search(found[0][len(found["head"]) + 3 :])
        return found[0] if expands or not alone else found["head"] + '""'

    text = CAT_MESSAGE.sub(cat_message, text)

    def cut(found: re.Match[str]) -> str:
        message = found["message"]
        return found[0] if "$(" in message or "`" in message else found["head"] + '""'

    return COMMIT_MESSAGE.sub(cut, text)


def commands(command: str) -> list[Command] | None:
    """The simple commands of the text. A separator, a bracket, a backtick or a newline outside
    quotes starts a new one (a newline in quotes does not); a redirect stays in its command with
    its target. Every command of a group `( ... )` or `{ ...; }` that a pipe follows feeds that
    pipe. Where the scan is not sure what it read, nothing counts as a read (the whole text is
    then the text that runs, as before the reads were data): a substitution, a process
    substitution, a compound command (`for`, `while`, `if`, `case`, `eval`...), a here-document of
    a command other than `cat`, a redirect between the bracket of a group and the pipe after it.
    None when the quotes do not balance."""
    parts = scan(command)
    if parts is None:
        return None
    items: list[tuple[str, list[str], str]] = []
    piped: set[int] = set()
    parens: list[int] = []
    braces: list[int] = []
    group: tuple[int, int] | None = None  # the commands of a group that just closed
    unsure = False
    alone = sum(1 for part, _ in parts if part.strip()) == 1  # the text is one command
    for text, end in parts:
        if text.strip():
            at = len(items)
            words = words_of(text) or text.split()
            kept = without_message(text, alone)
            if words[0] == "{":
                braces.append(at)
            unsure = (
                unsure or words[0] in COMPOUND or bool(HEREDOC.search(kept) and words[0] != "cat")
            )
            unsure = unsure or bool(group and re.match(r"\s*\d*[<>&]", text))
            if words[0] == "}" and braces:
                start = braces.pop()
                unsure = unsure or len(words) > 1  # a redirect after the brace
                if end in PIPES:
                    piped.update(range(start, at))
            items.append((kept, words, end))
            if end in PIPES:
                piped.add(at)
        elif end in PIPES and group:  # a pipe after the bracket that closed a group
            piped.update(range(*group))
        if end == "(":
            parens.append(len(items))
        group = (parens.pop() if parens else len(items), len(items)) if end == ")" else None
    trusted = not unsure and not RUNS_MORE.search("".join(text + end for text, _, end in items))
    return [
        Command(text, words, at in piped, trusted and is_read(words), end)
        for at, (text, words, end) in enumerate(items)
    ]


def joined(found: list[Command]) -> str:
    return "".join(item.text + item.end for item in found)


def arguments(words: list[str]) -> tuple[list[str], list[str]]:
    """The words of a command without its redirects, and the files a `<` redirect reads."""
    args: list[str] = []
    stdin_files: list[str] = []
    redirect = ""
    for word in words:
        if redirect:  # the word after a redirect operator is its target, not an argument
            if redirect == "<":
                stdin_files.append(word)
            redirect = ""
        elif set(word) <= set("<>&") and set(word) & set("<>"):
            redirect = word
        else:
            args.append(word)
    return args, stdin_files


def running(found: list[Command]) -> list[Command]:
    """The commands that run something: those that are no read, and a read that feeds a command
    after it in its pipeline (`echo "drop table t" | psql`)."""
    kept: list[Command] = []
    feeds_a_run = False
    for item in reversed(found):
        if not item.piped:  # the last command of its pipeline
            feeds_a_run = False
        if not item.read:
            feeds_a_run = True
        if feeds_a_run:
            kept.append(item)
    return kept[::-1]


def verified_before_commit(found: list[Command]) -> str | None:
    """`full` when every command that commits has a `make verify` chained with && before it (the
    commit only runs if the verify passed), `fast` when a `make verify-fast` does as well, None
    when a commit has neither, or there is none. A second commit with no verify of its own is not
    covered by the verify of the first. Extra words (`make verify -n`) make it no verify."""
    commits = 0
    level: str | None = "full"
    for at, item in enumerate(found):
        if item.read or not COMMIT.search(item.text.lower()):
            continue
        commits += 1
        before = at - 1
        while before >= 0 and found[before].end == "&&":
            words = found[before].words
            if words in (["make", "verify"], ["make", "verify-fast"]):
                if words[1] == "verify-fast":
                    level = "fast"
                break
            before -= 1
        else:
            return None
    return level if commits else None


PREPARES = (["make", "verify"], ["make", "verify-fast"], ["make", "check"])


def changes_before_commit(found: list[Command]) -> bool:
    """A command other than a read, `git add`, `cd`, `make verify` or `make check` runs before a
    commit of the same text: the gate reads the tree as it is before the text runs, so what that
    command writes (an apply, a stash pop, a redirect) would reach the commit unseen."""
    for at, item in enumerate(found):
        if item.read or not COMMIT.search(item.text.lower()):
            continue
        for before in found[:at]:
            if before.read or before.words[0] == "cd" or before.words in PREPARES:
                continue
            if not re.match(GIT + r"add\b", before.text.lower().strip()):
                return True
    return False


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


def secret_shown(command: str) -> str | None:
    """Why the command shows a secret (the reason for the owner), None when it does not."""
    if PROC_ENVIRON.search(command):
        return SECRET_ENVIRON
    text = ENV_FILE_OPTION.sub(" ", command)
    if ENV_TEXT.search(text) and INTERPRETER.search(text):
        return SECRET_ENV
    for found in SUBSTITUTION.finditer(command):
        reason = secret_shown(found[1] or found[2] or "")
        if reason:
            return reason
    parsed = commands(command)
    if parsed is None:
        return SECRET_ENV if ENV_TEXT.search(text) else None
    for item in parsed:
        args, stdin_files = arguments(item.words)
        if any(ENV_FILE.search(file) for file in stdin_files):
            return SECRET_ENV
        reason = secret_in_segment(args)
        if reason:
            return reason
    return None


def writes_stamp(run: str, whole: str) -> bool:
    """A stamp named in the commands that run something (the text of a read that feeds none is
    no write), the stamp code run directly, or Python that names agent_state and one of its
    writers (`agent_state.py tree` and `show` only read). The last two read the whole text."""
    return bool(
        STAMP_CLI.search(whole)
        or ("agent_state" in whole and PYTHON.search(whole) and STAMP_WRITERS.search(whole))
        or STAMP_NAME.search(run)
    )


def commit_gap(chained: str | None) -> list[str]:
    """What a `git commit` still lacks on this working tree, empty when it may go ahead. The need
    is the highest `gate_level` of the changed paths: `none` nothing; `check` a check and a
    reviewer verdict that is not `return`; `verify` also a verify of any mode; `full` also a full
    verify. A `make verify &&` run right before the commit (chained `full`) stands for the verify,
    a `make verify-fast &&` (chained `fast`) for one below the `full` level. A stamp covers when
    no path at or above its floor changed since its tree."""
    from scripts.agent_state import (
        ACCEPTED,
        Stamp,
        code_changes,
        gate_need,
        read_stamp,
        tree_hash,
        uncovered,
    )

    need = gate_need(code_changes(ROOT))
    if need == "none":
        return []
    current = tree_hash(ROOT)

    def covers(stamp: Stamp | None, floor: str) -> bool:
        return stamp is not None and not uncovered(ROOT, stamp, current, floor)

    missing = []
    chain_covers = chained == "full" or (chained == "fast" and need == "verify")
    if need in ("verify", "full") and not chain_covers:
        verify = read_stamp(ROOT, "verify", current)
        if need == "full":
            if verify is None or verify.mode != "full" or not covers(verify, "verify"):
                missing.append("a full make verify")
        elif not covers(verify, "verify"):
            missing.append("a make verify-fast or make verify")
    if not covers(read_stamp(ROOT, "check", current), "check"):
        missing.append("make check")
    review = read_stamp(ROOT, "review", current)
    if not covers(review, "check"):
        missing.append("a reviewer verdict")
    elif review is not None and review.mode not in ACCEPTED:
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
    found = commands(command)
    # The whole text: the command less its comments, the message of a commit and the data body of
    # a `cat` that writes a file. The word rules read the commands that run something: a pattern
    # of grep is no action, and a command of only reads runs nothing. Where the scan is not sure
    # (quotes that do not balance, a substitution, a compound command) every command counts as
    # running, so the whole text is read. The one read that is not free is the one that opens a
    # secret: that check looks at the whole command as it was typed.
    whole = command if found is None else joined(found)
    run = whole if found is None else joined(running(found))
    something_runs = found is None or any(not item.read for item in found)
    writes = whole if something_runs else ""
    low = run.lower()
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
    if SHELL_WRITE_ENV.search(writes):
        deny("shell write to .env")
    if SHELL_WRITE_HARNESS.search(writes):
        deny(
            "shell write to the agent hooks or settings",
            "prepare a copy in the scratchpad, the owner applies it with cp",
        )
    if writes_stamp(run, writes):
        deny("writes a gate stamp by hand", STAMP_FIX)
    if COMMIT.search(low):
        if found is not None and changes_before_commit(found):
            deny(
                "git commit after a command that changes the tree in the same text",
                "run it first, then commit",
            )
        missing = commit_gap(None if found is None else verified_before_commit(found))
        if missing:
            deny(
                f"git commit without {listed(missing)} on this working tree",
                "see docs/planning/13-harness.md, section 5",
            )
    if SHELL_WRITE_RULES.search(writes):
        ask("edits the agent roles or rules")
    secret = secret_shown(command)
    if secret:
        ask(secret)
    for pattern, reason in ASK:
        if pattern.search(low):
            ask(reason)
    if run and HTTP_ASK.search(whole.lower()):
        ask("changes the Debezium connector or the Lakekeeper catalog")


def main() -> None:
    try:
        check(json.load(sys.stdin))
    except VerdictError as verdict:
        verdict.emit()
    except Exception as error:  # a broken guard must not wave the call through
        VerdictError(
            "ask", f"guard.py failed ({error.__class__.__name__}: {error}), check the call by hand"
        ).emit()
    sys.exit(0)


if __name__ == "__main__":
    main()
