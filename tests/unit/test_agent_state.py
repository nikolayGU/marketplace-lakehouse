import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_state import code_changes, describe_stamp, read_stamp, tree_hash, write_stamp

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "agent_state.py"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(".verify-stamp\ntarget/\n")
    (tmp_path / "job.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_tree_hash_follows_content_not_staging_or_commits(repo: Path) -> None:
    clean = tree_hash(repo)
    (repo / "job.py").write_text("x = 2\n")
    edited = tree_hash(repo)
    (repo / "new.py").write_text("y = 1\n")
    untracked = tree_hash(repo)
    git(repo, "add", ".")
    staged = tree_hash(repo)
    git(repo, "commit", "-q", "-m", "next")

    assert len({clean, edited, untracked}) == 3
    assert staged == untracked == tree_hash(repo)
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
        ).stdout
        == ""
    )


def test_tree_hash_ignores_gitignored_files(repo: Path) -> None:
    before = tree_hash(repo)
    (repo / "target").mkdir()
    (repo / "target" / "out.json").write_text("{}")
    (repo / ".verify-stamp").write_text("anything")

    assert tree_hash(repo) == before


def test_stamp_is_fresh_only_for_the_tree_it_was_written_for(repo: Path) -> None:
    write_stamp(repo, "fast")
    stamp = read_stamp(repo)
    assert stamp is not None and stamp.mode == "fast" and stamp.fresh

    (repo / "job.py").write_text("x = 3\n")
    stale = read_stamp(repo)
    assert stale is not None and not stale.fresh


def test_missing_or_garbled_stamp_reads_as_none(repo: Path) -> None:
    assert read_stamp(repo) is None
    (repo / ".verify-stamp").write_text("garbage\n")
    assert read_stamp(repo) is None


def test_write_stamp_refuses_an_unknown_mode(repo: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        write_stamp(repo, "partial")


def test_code_changes_skip_markdown_and_docs(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.txt").write_text("x")
    (repo / "README.md").write_text("x")
    assert code_changes(repo) == []

    (repo / "job.py").write_text("x = 4\n")
    assert code_changes(repo) == ["job.py"]


def test_describe_stamp(repo: Path) -> None:
    assert describe_stamp(repo) == "none"
    write_stamp(repo, "full")
    assert describe_stamp(repo).startswith("full at ") and describe_stamp(repo).endswith("fresh")
    (repo / "job.py").write_text("x = 5\n")
    assert describe_stamp(repo).endswith("stale")


def test_cli_refuses_an_unknown_command(repo: Path) -> None:
    result = subprocess.run([sys.executable, str(SCRIPT), "erase", str(repo)], capture_output=True)
    assert result.returncode != 0


def test_cli_writes_a_stamp(repo: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPT), "stamp", "full", str(repo)], check=True)
    stamp = read_stamp(repo)

    assert stamp is not None and stamp.mode == "full" and stamp.fresh
