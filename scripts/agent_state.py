"""State the agent hooks check (`.claude/hooks/`): which tree `make verify` last passed on.

`make verify` and `make verify-fast` write `.verify-stamp` (git-ignored) with the mode and the git
tree id of the working tree, untracked files included. Any edit or new file makes the stamp stale;
staging or committing the verified content does not. Stdlib only: the hooks run under the
system python3, outside the project environment.
"""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STAMP = ".verify-stamp"
MODES = ("fast", "full")


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


def write_stamp(root: Path, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown verify mode {mode!r}, expected one of {MODES}")
    written_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / STAMP).write_text(f"{mode} {written_at} {tree_hash(root)}\n")


def read_stamp(root: Path) -> Stamp | None:
    path = root / STAMP
    if not path.exists():
        return None
    parts = path.read_text().split()
    if len(parts) != 3 or parts[0] not in MODES:
        return None
    mode, written_at, digest = parts
    return Stamp(mode, written_at, digest == tree_hash(root), digest)


def describe_stamp(root: Path) -> str:
    stamp = read_stamp(root)
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


def code_changes_since(root: Path, stamp: Stamp) -> list[str]:
    """Paths other than Markdown and `docs/` that differ from the tree the stamp verified. The
    stamped tree was written to the object store by `tree_hash`, so git can diff against it."""
    names = _git(root, "diff", "--name-only", stamp.tree, tree_hash(root)).decode().splitlines()
    return sorted(p for p in names if _is_code(p))


def main() -> None:
    usage = f"usage: {sys.argv[0]} stamp fast|full <repo root> | show <repo root>"
    match sys.argv[1:]:
        case ["stamp", mode, root]:
            write_stamp(Path(root), mode)
        case ["show", root]:
            print(describe_stamp(Path(root)))
        case _:
            sys.exit(usage)


if __name__ == "__main__":
    main()
