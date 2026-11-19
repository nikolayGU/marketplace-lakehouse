"""State the agent hooks check (`.claude/hooks/`): the tree each step of the commit gate passed on.

Three git-ignored stamps, each one line `<mode> <written_at> <tree>`, the tree being the git tree
id of the working tree, untracked files included:

- `.verify-stamp`, mode `fast` or `full`: written by `make verify-fast` and `make verify`. A `fast`
  verify keeps a `full` stamp whose tree differs from the new one in no path of the `verify` level
  or above (see `gate_level`: Markdown, `docs/`, `tests/`, `.github/`, `.claude/` and the lint
  configs do not count), since the full run already covers it.
- `.check-stamp`, mode `check`: written by `make check` (`run_check`), after `make lint` and
  `make test` passed on a tree that did not change while they ran.
- `.review-stamp`, mode `accept`, `accept-with-notes` or `return`: kept by the hook
  `.claude/hooks/review_stamp.py` through `record_review`. An accepting verdict on code is stamped
  for the tree id the reviewer printed (`tree`) when the review began; `вернуть` or a garbled
  report on code stamps `return` for the working tree.

Any edit or new file makes a stamp stale; staging or committing the checked content does not.
Which edits matter to a stamp depends on the path: `gate_level` names the level a path needs
(`none < check < verify < full`) and `uncovered` lists the changed paths from a floor upwards.
`remember_session_base` keeps the tree a session started on, in the git directory.
Stdlib only: the hooks run under the system python3, outside the project environment.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
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


_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_BASE_PREFIX = "claude-base-"
_BASE_MAX_AGE = 7 * 24 * 3600


def _base_path(root: Path, session_id: str) -> Path | None:
    """The file of a session base, in the git directory of this worktree (`git rev-parse
    --git-path`): a linked worktree keeps its own. None for an id out of `[A-Za-z0-9_-]{1,128}`,
    or when git cannot say."""
    if not _SESSION_ID.fullmatch(session_id):
        return None
    try:
        out = _git(root, "rev-parse", "--git-path", f"{_BASE_PREFIX}{session_id}")
    except (subprocess.CalledProcessError, OSError):
        return None
    return root / os.fsdecode(out).strip()  # git prints it relative to root, or absolute


def remember_session_base(root: Path, session_id: str) -> str | None:
    """Keep the tree id the session started on, only if the session has none yet (a second call
    does not move it), and drop bases of other sessions older than 7 days. Returns the base, None
    for an id out of `[A-Za-z0-9_-]{1,128}` or when git cannot answer."""
    path = _base_path(root, session_id)
    if path is None:
        return None
    try:
        for old in path.parent.glob(f"{_BASE_PREFIX}*"):
            if old != path and time.time() - old.stat().st_mtime > _BASE_MAX_AGE:
                old.unlink(missing_ok=True)
        if not path.exists():
            tree = tree_hash(root)
            try:
                with path.open("x") as handle:
                    handle.write(f"{tree}\n")
            except FileExistsError:
                pass
    except (subprocess.CalledProcessError, OSError):
        return None
    return session_base(root, session_id)


def session_base(root: Path, session_id: str) -> str | None:
    """The tree id `remember_session_base` kept for the session, None when there is none or the id
    is out of `[A-Za-z0-9_-]{1,128}`."""
    path = _base_path(root, session_id)
    if path is None:
        return None
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return text if _TREE_ID.fullmatch(text) else None


def _store(root: Path, name: str, mode: str, tree: str) -> None:
    written_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / name).write_text(f"{mode} {written_at} {tree}\n")


def _kept_full(root: Path, tree: str) -> str | None:
    """A message when `.verify-stamp` holds a `full` stamp whose tree differs from `tree` in no path
    of the `verify` level or above (Markdown, `docs/`, `tests/`, `.github/`, `.claude/` and the lint
    configs may change), so a `fast` verify has nothing to add to it. None when there is no such
    stamp, or when the tree it names is gone from the object store."""
    stamp = read_stamp(root, current=tree)
    if stamp is None or stamp.mode != "full" or uncovered(root, stamp, tree, "verify"):
        return None
    return f"kept the full verify stamp of {stamp.written_at}: it covers this tree"


def write_stamp(root: Path, mode: str, tree: str | None = None) -> str:
    """Stamp a tree: `fast` and `full` in `.verify-stamp`, `check` in `.check-stamp`. `tree` is the
    tree id to stamp, the working tree as it is now by default; an id that is no tree of this
    repository is refused. A `fast` stamp does not replace a `full` one when no path of the `verify`
    level or above changed since it (a change in `tests/`, `.github/` or `.claude/` does not count).
    A review verdict is stamped only by `record_review`. Returns what was done."""
    if mode in MODES:
        name = STAMP
    elif mode == CHECK_MODE:
        name = CHECK_STAMP
    else:
        raise ValueError(f"unknown stamp mode {mode!r}, expected one of {(*MODES, CHECK_MODE)}")
    if tree is None:
        tree = tree_hash(root)
    elif not (_TREE_ID.fullmatch(tree) and _is_tree(root, tree)):
        raise ValueError(f"{tree!r} is not a tree of this repository")
    if mode == "fast":
        kept = _kept_full(root, tree)
        if kept:
            return kept
    _store(root, name, mode, tree)
    return f"wrote the {mode} stamp for tree {tree}"


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
    """One line for `show`: `fresh` for the working tree, `covers` when nothing at or above the
    floor of the kind changed since the stamped tree, else `stale` with the reason. The floor is
    `verify` for the verify stamp and `check` for a check or review stamp. `covers (only Markdown
    and docs/ changed since)` means only paths of level `none` changed; a verify stamp also covers
    changes of level `check` (tests, CI, hooks, lint configs) and says so. `covers` states the
    relation of the two trees only: whether the commit gate takes the stamp also depends on its
    mode (a `fast` verify never opens it, a `check` or review stamp is judged by its own rule).
    A missing stamp file gives `none` before git is asked anything."""
    name, _ = _kind(kind)
    if not (root / name).exists():
        return "none"
    current = tree_hash(root)
    stamp = read_stamp(root, kind, current)
    if stamp is None:
        return "none"
    head = f"{stamp.mode} at {stamp.written_at}"
    if stamp.fresh:
        return f"{head}, fresh"
    floor = "verify" if kind == "verify" else "check"
    try:
        changed = _changed_paths(root, stamp.tree, current)
    except subprocess.CalledProcessError:
        return f"{head}, stale (the stamped tree is gone)"
    open_paths = [p for p in changed if _rank(gate_level(p)) >= _rank(floor)]
    if open_paths:
        count = len(open_paths)
        return f"{head}, stale (code changed: {count} path{'' if count == 1 else 's'})"
    if gate_need(changed) == "none":
        return f"{head}, covers (only Markdown and docs/ changed since)"
    return (
        f"{head}, covers (only paths below the {floor} level changed since: tests, CI, agent "
        "files or lint configs)"
    )


LEVELS = ("none", "check", "verify", "full")
_FULL_PREFIXES = ("streaming/", "contracts/")
_CHECK_PREFIXES = ("tests/", ".github/", ".claude/")
# Root files only: `dbt/.sqlfluff` is read by the dbt lint inside the verify run.
_CHECK_FILES = (".pre-commit-config.yaml", ".yamllint", ".sqlfluff", "scripts/agent_state.py")


def _is_code(path: str) -> bool:
    # dbt reads the `{% docs %}` blocks of dbt/**/*.md, so Markdown there changes the models.
    return not (path.endswith(".md") and not path.startswith("dbt/")) and not path.startswith(
        "docs/"
    )


def _rank(level: str) -> int:
    return LEVELS.index(level)


def gate_level(path: str) -> str:
    """The gate a change of `path` needs: `none` (Markdown outside `dbt/`, `docs/`), `check` (tests,
    CI, agent files, lint configs, this module), `full` (`streaming/`, `contracts/`, whose result
    only a full verify shows) or `verify` (everything else)."""
    if not _is_code(path):
        return "none"
    if path.startswith(_FULL_PREFIXES):
        return "full"
    if path.startswith(_CHECK_PREFIXES) or path in _CHECK_FILES:
        return "check"
    return "verify"


def gate_need(paths: Iterable[str]) -> str:
    """The highest `gate_level` of the paths, `none` for no paths."""
    return max((gate_level(p) for p in paths), key=_rank, default="none")


def _paths(output: bytes) -> list[str]:
    """The paths of a `-z` listing: NUL-separated and never quoted, whatever the name holds."""
    return [os.fsdecode(raw) for raw in output.split(b"\0") if raw]


def code_changes(root: Path) -> list[str]:
    """Changed or untracked paths other than Markdown and `docs/`: what a check must cover."""
    # --no-renames: a staged `git mv` is listed as `old -> new`, and only the new name was read.
    # -z: otherwise git quotes a path with a space, a quote or a non-ASCII letter, and the quoted
    # name starts with `"`, so it always counted as code. An entry is `XY path`.
    entries = _paths(
        _git(root, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all")
    )
    return sorted(p for p in (entry[3:] for entry in entries) if _is_code(p))


def _code_diff(root: Path, old: str, new: str) -> list[str]:
    # Without --no-renames a moved file is listed by its new name only, and code moved to docs/ or
    # renamed to .md would look like a Markdown change. -z as in code_changes: no quoted names.
    names = _paths(_git(root, "diff", "--name-only", "-z", "--no-renames", old, new))
    return sorted(p for p in names if _is_code(p))


def _changed_paths(root: Path, old: str, new: str) -> list[str]:
    """Every path that differs between two trees, renames listed as a delete and an add."""
    return sorted(_paths(_git(root, "diff", "--name-only", "-z", "--no-renames", old, new)))


def uncovered(root: Path, stamp: Stamp, current: str, floor: str) -> list[str]:
    """Paths of level `floor` or above that differ between the stamped tree and `current`. When git
    cannot compare (the stamped tree is gone), the stamp covers nothing: one entry says so."""
    try:
        changed = _changed_paths(root, stamp.tree, current)
    except subprocess.CalledProcessError:
        return [f"(tree {stamp.tree} of the stamp is gone: nothing is covered)"]
    return [p for p in changed if _rank(gate_level(p)) >= _rank(floor)]


def code_changes_since(root: Path, stamp: Stamp, current: str | None = None) -> list[str]:
    """Paths other than Markdown and `docs/` that differ from the tree the stamp covers. The
    stamped tree was written to the object store by `tree_hash`, so git can diff against it."""
    now = current if current is not None else tree_hash(root)
    return _code_diff(root, stamp.tree, now)


_VERDICT_WORD = re.compile("вердикт", re.IGNORECASE)
_VERDICT_PHRASE = re.compile(rf"(?<!\w)(?:{_phrases(VERDICTS)})(?!\w)", re.IGNORECASE)
_TAKES_BACK_RE = re.compile(_TAKES_BACK, re.IGNORECASE)
_TREE_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_RETURN_WORD = re.compile(r"(?<!\w)вернуть(?!\w)", re.IGNORECASE)


def _two_subjects(found: re.Match[str]) -> bool:
    """A subject line that names more than one subject ("план и код") is no subject: `код` among
    other words must not read as a review of code, nor `план` hide a review of code."""
    line = found.string[found.start(1) :].lower()
    return sum(subject in line for subject in SUBJECTS) > 1


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
        if not any(head.match(line) for head, _ in _FIELDS.values()):
            # "Итог. Вердикт: вернуть", "Вердикт - вернуть", "Итог. Вердикт: не принять": a verdict
            # out of format that returns, or takes an accept back, still revokes.
            if _VERDICT_WORD.search(line) and (
                _RETURN_WORD.search(line)
                or (_VERDICT_PHRASE.search(line) and _TAKES_BACK_RE.search(line))
            ):
                garbled.add("verdict")
            continue
        for name, (head, valid) in _FIELDS.items():
            if not head.match(line):
                continue
            found = valid.match(line)
            if found and "|" not in found[2] and not (name == "subject" and _two_subjects(found)):
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
    accepting verdict in force. That covers a line that mentions `вердикт` and `вернуть` but does
    not start with the `Вердикт:` head ("Итог. Вердикт: вернуть", "Вердикт - вернуть"), a line
    without the head that has the word `вердикт`, an accepting phrase and a word of refusal
    ("Итог. Вердикт: не принять"), and a
    subject line that names more than one of `код`, `план`, `документ` ("Предмет: план и код").
    Returns what happened."""
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


def _covers(root: Path, limit: int = 20) -> str:
    """The code a review of the working tree now would cover: the paths changed since HEAD."""
    changed = code_changes(root)
    if not changed:
        return "covers no code changed since HEAD"
    more = f" and {len(changed) - limit} more" if len(changed) > limit else ""
    return f"covers code changed since HEAD: {', '.join(changed[:limit])}{more}"


def main() -> None:
    usage = (
        f"usage: {sys.argv[0]} stamp fast|full <repo root> [<tree id>] | stamp check <repo root>"
        " | show [verify|check|review] <repo root> | tree <repo root> | check <repo root>"
    )
    match sys.argv[1:]:
        case ["stamp", mode, root, *rest] if len(rest) <= 1 and (mode in MODES or not rest):
            try:
                print(write_stamp(Path(root), mode, *rest), file=sys.stderr)
            except ValueError as error:
                sys.exit(str(error))
        case ["show", root]:
            print(describe_stamp(Path(root)))
        case ["show", kind, root] if kind in KINDS:
            print(describe_stamp(Path(root), kind))
        case ["tree", root]:
            print(tree_hash(Path(root)))
            print(_covers(Path(root)), file=sys.stderr)
        case ["check", root]:
            sys.exit(run_check(Path(root)))
        case _:
            sys.exit(usage)


if __name__ == "__main__":
    main()
