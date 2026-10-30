"""State the agent hooks check (`.claude/hooks/`): the tree each step of the commit gate passed on.

Three git-ignored stamps, each one line `<mode> <written_at> <tree>`, the tree being the git tree
id of the working tree, untracked files included:

- `.verify-stamp`, mode `fast` or `full`: written by `make verify-fast` and `make verify`.
- `.check-stamp`, mode `check`: written by `make check` (`run_check`), after `make lint` and
  `make test` passed on a tree that did not change while they ran.
- `.review-stamp`, mode `accept`, `accept-with-notes` or `return`: kept by the hook
  `.claude/hooks/review_stamp.py` through `record_review`. An accepting verdict on code is stamped
  for the tree id the reviewer printed (`tree`) when the review began; `вернуть` or a garbled
  report on code stamps `return` for the working tree.

Any edit or new file makes a stamp stale; staging or committing the checked content does not.
Stdlib only: the hooks run under the system python3, outside the project environment.
"""

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STAMP = ".verify-stamp"
CHECK_STAMP = ".check-stamp"
REVIEW_STAMP = ".review-stamp"
MODES = ("fast", "full")
CHECK_MODE = "check"
# The verdict words of .claude/agents/reviewer.md and the stamp mode each one becomes.
VERDICTS = {
    "принять": "accept",
    "принять с замечаниями": "accept-with-notes",  # noqa: RUF001
    "вернуть": "return",
}
ACCEPTED = ("accept", "accept-with-notes")
# The subject line of a reviewer report: only a review of code opens or closes the commit gate.
CODE = "код"
SUBJECTS = (CODE, "план", "документ")
KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "verify": (STAMP, MODES),
    "check": (CHECK_STAMP, (CHECK_MODE,)),
    "review": (REVIEW_STAMP, tuple(VERDICTS.values())),
}
# What `make check` runs, and the variables that would pass a flag such as `-i` from `make -i check`
# or pytest options into it.
CHECK_COMMAND = ("make", "--no-print-directory", "lint", "test")
CHECK_ENV_DROPPED = (
    "MAKEFLAGS",
    "MFLAGS",
    "GNUMAKEFLAGS",
    "MAKELEVEL",
    "MAKEFILES",
    "PYTEST_ADDOPTS",
)

# What a reviewer may wrap a line in: indentation, emphasis, a heading, a quote or a list bullet.
_MARKUP = r"[\s*_`#>-]*"


def _phrases(values: Iterable[str]) -> str:
    return "|".join(
        r"\s+".join(map(re.escape, value.split()))
        for value in sorted(values, key=len, reverse=True)
    )


def _field(name: str, values: str, tail: str = r"\b.*") -> tuple[re.Pattern[str], re.Pattern[str]]:
    """The head of a report line (`<name>:` after markup) and the whole line with a valid value."""
    head = rf"{_MARKUP}{name}{_MARKUP}:"
    line = rf"{head}{_MARKUP}({values})({tail})"
    return re.compile(head, re.IGNORECASE), re.compile(line, re.IGNORECASE)


# After a verdict only the end of the line, spaces, a full stop, Markdown marks and one remark in
# parentheses may follow, so "принять нельзя, вернуть" is no accept. A line that goes on is garbled,
# and so is a remark with a word that takes the verdict back: "принять (нельзя, вернуть)".
_TAKES_BACK = r"верн|нельзя|\bне\b|\bнет\b|отклон|отказ"  # noqa: RUF001
_VERDICT_TAIL = rf"(?![^\W_])[\s.*_`]*(?:\((?![^()|]*(?:{_TAKES_BACK}))[^()|]*\)[\s.*_`]*)?$"

_FIELDS = {
    "verdict": _field("вердикт", _phrases(VERDICTS), _VERDICT_TAIL),
    "subject": _field("предмет", _phrases(SUBJECTS)),
    "tree": _field("дерево", r"[0-9a-f]{64}|[0-9a-f]{40}"),
}


@dataclass(frozen=True)
class Stamp:
    mode: str
    written_at: str
    fresh: bool
    tree: str


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, env=env
    ).stdout


def tree_hash(root: Path) -> str:
    """Git tree id of the working tree as `git add -A` would stage it, built in a throwaway index:
    staging does not change it, an edit or a new file does, and ignored files never count."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(root, "read-tree", "HEAD", env=env)
        _git(root, "add", "-A", env=env)
        return _git(root, "write-tree", env=env).decode().strip()


def _store(root: Path, name: str, mode: str, tree: str) -> None:
    written_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / name).write_text(f"{mode} {written_at} {tree}\n")


def write_stamp(root: Path, mode: str) -> None:
    """Stamp the working tree as it is now: `fast` and `full` in `.verify-stamp`, `check` in
    `.check-stamp`. A review verdict is stamped only by `record_review`."""
    if mode in MODES:
        name = STAMP
    elif mode == CHECK_MODE:
        name = CHECK_STAMP
    else:
        raise ValueError(f"unknown stamp mode {mode!r}, expected one of {(*MODES, CHECK_MODE)}")
    _store(root, name, mode, tree_hash(root))


def _kind(kind: str) -> tuple[str, tuple[str, ...]]:
    if kind not in KINDS:
        raise ValueError(f"unknown stamp kind {kind!r}, expected one of {tuple(KINDS)}")
    return KINDS[kind]


def read_stamp(root: Path, kind: str = "verify", current: str | None = None) -> Stamp | None:
    """The stamp of `kind` (`verify`, `check` or `review`), None when it is missing or garbled.
    `current` is the tree id of the working tree if the caller has computed it already."""
    name, modes = _kind(kind)
    path = root / name
    if not path.exists():
        return None
    parts = path.read_text().split()
    if len(parts) != 3 or parts[0] not in modes:
        return None
    mode, written_at, digest = parts
    now = current if current is not None else tree_hash(root)
    return Stamp(mode, written_at, digest == now, digest)


def describe_stamp(root: Path, kind: str = "verify") -> str:
    stamp = read_stamp(root, kind)
    if stamp is None:
        return "none"
    return f"{stamp.mode} at {stamp.written_at}, {'fresh' if stamp.fresh else 'stale'}"


def _is_code(path: str) -> bool:
    return not path.endswith(".md") and not path.startswith("docs/")


def code_changes(root: Path) -> list[str]:
    """Changed or untracked paths other than Markdown and `docs/`: what a check must cover."""
    lines = _git(root, "status", "--porcelain", "--untracked-files=all").decode().splitlines()
    paths = [line[3:].split(" -> ")[-1] for line in lines]
    return sorted(p for p in paths if _is_code(p))


def _code_diff(root: Path, old: str, new: str) -> list[str]:
    names = _git(root, "diff", "--name-only", old, new).decode().splitlines()
    return sorted(p for p in names if _is_code(p))


def code_changes_since(root: Path, stamp: Stamp, current: str | None = None) -> list[str]:
    """Paths other than Markdown and `docs/` that differ from the tree the stamp covers. The
    stamped tree was written to the object store by `tree_hash`, so git can diff against it."""
    now = current if current is not None else tree_hash(root)
    return _code_diff(root, stamp.tree, now)


@dataclass(frozen=True)
class _Report:
    """The verdict, subject and tree lines of a reviewer report: the values of the lines that hold
    one, and the fields with a line that has the head but no valid value. A line that goes on
    with `|` is the template listing the values, not a value."""

    values: dict[str, set[str]]
    garbled: set[str]


def _read_report(report: str) -> _Report:
    values: dict[str, set[str]] = {name: set() for name in _FIELDS}
    garbled: set[str] = set()
    for line in report.splitlines():
        for name, (head, valid) in _FIELDS.items():
            if not head.match(line):
                continue
            found = valid.match(line)
            if found and "|" not in found[2]:
                values[name].add(" ".join(found[1].lower().split()))
            else:
                garbled.add(name)
            break
    return _Report(values, garbled)


def _gate_problem(root: Path, report: _Report) -> str | None:
    """Why a report on code is not one verdict on one tree of this repository, None when it is."""
    if report.garbled:
        return f"garbled {' and '.join(sorted(report.garbled))} line"
    for name in ("subject", "verdict", "tree"):
        if len(report.values[name]) != 1:
            return f"expected one {name} line, found {len(report.values[name])}"
    tree = next(iter(report.values["tree"]))
    if not _is_tree(root, tree):
        return f"{tree} is not a tree of this repository"
    return None


def _is_tree(root: Path, digest: str) -> bool:
    try:
        return _git(root, "cat-file", "-t", digest).decode().strip() == "tree"
    except subprocess.CalledProcessError:
        return False


def record_review(root: Path, report: str) -> str:
    """Keep `.review-stamp` in step with a `reviewer` report (13-harness.md, section 4).

    A text without a verdict line (the closing text after a hand-back) and a review of a plan or a
    document leave the stamp as it is. A review of code with one verdict, the subject `код` and
    the id of a tree of this repository (a repeated identical line counts once) stamps an
    accepting verdict for that tree, unless code changed since it (Markdown and `docs/` do not
    count), and `return` for the working tree. Any other report with a verdict line revokes the
    stamp, `return` for the working tree, so a garbled or late `вернуть` never leaves an earlier
    accepting verdict in force. Returns what happened."""
    parsed = _read_report(report)
    verdicts, subjects = parsed.values["verdict"], parsed.values["subject"]
    if not verdicts and "verdict" not in parsed.garbled:
        return "nothing recorded: no verdict line in the report"
    if subjects and CODE not in subjects and "subject" not in parsed.garbled:
        return f"nothing recorded: not a review of code ({', '.join(sorted(subjects))})"
    current = tree_hash(root)
    problem = _gate_problem(root, parsed)
    if problem:
        _store(root, REVIEW_STAMP, "return", current)
        return f"review stamp revoked ({problem}): return for tree {current}"
    verdict, tree = VERDICTS[next(iter(verdicts))], next(iter(parsed.values["tree"]))
    if verdict not in ACCEPTED:
        _store(root, REVIEW_STAMP, verdict, current)
        return f"review stamp: {verdict} for tree {current}"
    changed = _code_diff(root, tree, current)
    if changed:
        more = f" and {len(changed) - 5} more" if len(changed) > 5 else ""
        return f"nothing recorded: code changed since tree {tree}: {', '.join(changed[:5])}{more}"
    _store(root, REVIEW_STAMP, verdict, tree)
    return f"review stamp: {verdict} for tree {tree}"


def run_check(root: Path, command: Sequence[str] = CHECK_COMMAND) -> int:
    """`make check`: run lint and test, and stamp `.check-stamp` only if they passed on the tree
    they started on, so an edit made while they ran is not stamped as checked. The make and
    pytest option variables are dropped from their environment. Returns the exit code."""
    before = tree_hash(root)
    env = {key: value for key, value in os.environ.items() if key not in CHECK_ENV_DROPPED}
    result = subprocess.run(list(command), cwd=root, env=env, check=False)
    if result.returncode != 0:
        print(f"make check failed (exit {result.returncode}), no check stamp", file=sys.stderr)
        return result.returncode
    if tree_hash(root) != before:
        print("the working tree changed while make check ran, run it again", file=sys.stderr)
        return 1
    _store(root, CHECK_STAMP, CHECK_MODE, before)
    return 0


def main() -> None:
    usage = (
        f"usage: {sys.argv[0]} stamp fast|full|check <repo root>"
        " | show [verify|check|review] <repo root> | tree <repo root> | check <repo root>"
    )
    match sys.argv[1:]:
        case ["stamp", mode, root]:
            try:
                write_stamp(Path(root), mode)
            except ValueError as error:
                sys.exit(str(error))
        case ["show", root]:
            print(describe_stamp(Path(root)))
        case ["show", kind, root] if kind in KINDS:
            print(describe_stamp(Path(root), kind))
        case ["tree", root]:
            print(tree_hash(Path(root)))
        case ["check", root]:
            sys.exit(run_check(Path(root)))
        case _:
            sys.exit(usage)


if __name__ == "__main__":
    main()
