import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.agent_state import write_stamp

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"


def hook(
    name: str, event: dict[str, Any], root: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root or REPO)}
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def bash(command: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    return hook("guard.py", {"tool_name": "Bash", "tool_input": {"command": command}}, root)


def decision(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 2:
        return "deny"
    if result.stdout.strip():
        return str(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"])
    return "allow"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(".verify-stamp\n")
    (tmp_path / "job.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push -f",
        "git push origin +main",
        "git push --force-with-lease",
        'trino --execute "DROP TABLE silver.orders"',
        'psql -c "truncate shop.orders"',
        'psql -c "DELETE FROM shop.orders"',
        "echo X=1 >> .env",
        "sed -i s/a/b/ .env",
        "cp /tmp/x .env",
        "git -C /repo push --force",
        'grep -l x f | xargs psql -c "drop table t"',
        'grep x $(psql -c "drop table t")',
        'grep x f\ntrino --execute "drop table t"',
        'cat q.sql; psql -c "truncate t"',
        'git log -1 && trino --execute "drop table t"',
        'grep "drop table" f & psql -c "delete from t"',
        "grep KEY f > .env",
        'grep x#; psql -c "drop table t"',
        "grep $'x' f; psql -c 'drop table t'",
        "git --git-dir .git push --force",
        "git 'push' -f",
        "grep x f\n>/dev/null psql -c 'drop table t'",
        "cat README.md\n2>&1 git push --force origin main",
        "rg --hostname-bin=sh 'drop table t' .",
        "cp /tmp/x .env 2>/dev/null",
        "cp /tmp/x .env.local",
        "rg '--pre=sh' 'drop table t' .",
        "git grep '-Osh' 'drop table t'",
        "git grep --open 'drop table t'",
    ],
)
def test_guard_denies(command: str) -> None:
    result = bash(command)

    assert decision(result) == "deny"
    assert "blocked by .claude/hooks/guard.py" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "make replay-burst SECONDS=60",
        "make replay-live",
        "make silver",
        "make bootstrap",
        "make nuke",
        "make chaos-spark-kill",
        "make iceberg-demo",
        "PYTHONPATH=oltp uv run python -m replayer start",
        "git push origin main",
        "git rebase origin/main",
        "git reset --hard HEAD~1",
        "docker compose -f docker/compose.yaml down -v",
        "docker volume rm lakehouse_minio",
        "rm -rf ../somewhere",
        "bash connect/register.sh",
        "curl -X PUT 127.0.0.1:8083/connectors/shop-connector/config -d @c.json",
        'psql -c "alter system set max_wal_size = 2GB"',
        'trino --execute "create table gold.x (a int)"',
        "git -C /repo push origin main",
        "git --no-pager rebase main",
        'grep -n "make silver" Makefile && make silver',
        "git --git-dir .git --work-tree . push origin main",
    ],
)
def test_guard_asks_the_owner(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "AGENTS.md hard rule" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "make verify-fast",
        "make reconcile",
        "make replay-status",
        "make dbt-build",
        "make test-spark",
        "git status && git log -1",
        'psql -c "delete from cdc.debezium_signal where id = 1"',
        "truncate -s 0 /tmp/x.log",
        "cp .env.example /tmp/a && grep REPLAY .env",
        "rm /tmp/one-file",
        'grep -rn "DROP TABLE" docs',
        'grep -rnE "make silver|delete from shop.orders" docs 2>/dev/null | head -5',
        "git log --grep push --oneline",
        'cd /x && git show HEAD -- Makefile | grep "make replay-burst"',
        "rg -n 'truncate table|git push --force' .",
    ],
)
def test_guard_allows(command: str) -> None:
    assert decision(bash(command)) == "allow"


@pytest.mark.parametrize(
    ("path", "expected"),
    [(".env", "deny"), ("certs/server.key", "deny"), (".env.example", "allow"), ("a.md", "allow")],
)
def test_guard_on_file_writes(path: str, expected: str) -> None:
    event = {"tool_name": "Write", "tool_input": {"file_path": str(REPO / path)}}

    assert decision(hook("guard.py", event)) == expected


def test_commit_needs_a_full_verify_of_this_tree(repo: Path) -> None:
    commit = "git add -A && git commit -m change"
    (repo / "job.py").write_text("x = 2\n")
    assert decision(bash(commit, repo)) == "deny"

    write_stamp(repo, "fast")
    assert decision(bash(commit, repo)) == "deny"

    write_stamp(repo, "full")
    assert decision(bash(commit, repo)) == "allow"

    (repo / "job.py").write_text("x = 3\n")
    assert decision(bash(commit, repo)) == "deny"


def test_commit_message_words_are_not_subcommands(repo: Path) -> None:
    write_stamp(repo, "full")

    assert decision(bash('git commit -m "docs: rebase and push rules"', repo)) == "allow"
    assert decision(bash("git log --grep commit", repo)) == "allow"
    (repo / "job.py").write_text("x = 2\n")
    assert decision(bash("git commit-tree HEAD^{tree}", repo)) == "deny"


def test_guard_fails_closed() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOKS / "guard.py")],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )

    assert decision(result) == "ask"
    assert "guard.py failed" in result.stdout


def test_commit_chained_after_a_full_verify_is_allowed(repo: Path) -> None:
    assert decision(bash("make verify && git add -A && git commit -m x", repo)) == "allow"
    assert decision(bash("make verify-fast && git commit -m x", repo)) == "deny"
    assert decision(bash("make verify; git commit -m x", repo)) == "deny"


def test_stop_gate_blocks_code_changes_without_a_fresh_stamp(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    result = hook("stop_gate.py", {"stop_hook_active": False}, repo)

    assert json.loads(result.stdout)["decision"] == "block"
    assert "job.py" in json.loads(result.stdout)["reason"]


def test_stop_gate_lets_the_turn_end(repo: Path) -> None:
    assert hook("stop_gate.py", {}, repo).stdout == ""

    (repo / "docs").mkdir()
    (repo / "docs" / "notes.txt").write_text("x")
    (repo / "NOTES.md").write_text("x")
    assert hook("stop_gate.py", {}, repo).stdout == ""

    (repo / "job.py").write_text("x = 2\n")
    assert hook("stop_gate.py", {"stop_hook_active": True}, repo).stdout == ""

    write_stamp(repo, "fast")
    assert hook("stop_gate.py", {}, repo).stdout == ""


def test_session_context_reports_state_goal_and_stamp(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "HANDOFF.md").write_text(
        "# HANDOFF\n\n## Состояние на 17.10\n\nW3-T01 done.\n\n### Done\n\ndetails\n"
    )
    (repo / "docs" / "NEXT_SESSION.md").write_text(
        "# Next session: W3-T02\n\n```text\nGoal: marts.\n\nmore\n```\n"
    )
    result = hook("session_context.py", {"source": "startup"}, repo)
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "W3-T01 done." in context
    assert "details" not in context
    assert "Goal: marts." in context
    assert "Verify stamp: none" in context
    assert "Uncommitted: 1 paths\n?? docs/" in context


def test_session_context_survives_missing_docs(repo: Path) -> None:
    result = hook("session_context.py", {}, repo)
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "docs/HANDOFF.md is missing" in context
