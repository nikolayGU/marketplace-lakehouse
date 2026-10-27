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
        "psql -c \"select pg_replication_slot_advance('shop_slot', '0/5A000000')\"",
        "psql -c \"select pg_drop_replication_slot('shop_slot')\"",
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
        "cp /tmp/guard.py .claude/hooks/guard.py",
        "sed -i s/ask/allow/ .claude/hooks/guard.py",
        "echo '{}' > .claude/settings.local.json",
        "rm .claude/hooks/stop_gate.py",
        "chmod -x .claude/hooks/guard.py",
        f"cp /tmp/guard.py {REPO}/.claude/hooks/guard.py",
        "psql -c \"select pg_logical_emit_message(true, 'p', 'x')\"",
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
        # The W5-D13 ladder by any route, not only through make.
        "docker compose --profile core run --rm --no-deps spark-silver maintenance expire "
        "--days 7 silver.sellers",
        "docker compose --profile core run --rm --no-deps spark-silver",
        "docker run --rm lakehouse/spark:dev maintenance orphans --no-dry-run silver.orders",
        "trino --execute \"call lake.system.rollback_to_snapshot('silver.orders', 1)\"",
        "airflow dags unpause iceberg_maintenance",
        "docker compose exec -T airflow-scheduler airflow dags trigger iceberg_orphans",
        "airflow dags trigger x --conf '{\"dry_run\": false}'",
        "airflow dags trigger x --conf '{\"expire_and_compact\": true}'",
        "curl -X PATCH 127.0.0.1:8080/api/v2/dags/iceberg_orphans -d '{\"is_paused\": false}'",
        "airflow tasks clear dq_checks",
        # Retention and offsets of a live topic.
        "kafka-configs.sh --bootstrap-server localhost:9092 --alter --entity-type topics "
        "--entity-name oltp.message --add-config segment.ms=3600000",
        "kafka-topics.sh --bootstrap-server localhost:9092 --delete --topic lab.orders.x",
        "kafka-consumer-groups.sh --bootstrap-server localhost:9092 --reset-offsets --group g",
        # The MinIO images exist only in the local image store.
        "docker image prune -a -f",
        "docker rmi quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z",
        # A changed image recreates spark-bronze, which turns on the bronze metadata property.
        "TRINO_XMX=2g make start",
        "make up PROFILE=obs",
        "docker compose -f docker/compose.yaml up -d --force-recreate spark-bronze",
        # Visible outside the laptop.
        "gh workflow run smoke.yml --ref main",
        "gh pr create --fill",
        "gh api -X DELETE repos/o/r/actions/caches",
        "docker push ghcr.io/o/minio:frozen",
        # The catalog, the bucket, the source database.
        "curl -X DELETE 127.0.0.1:8181/management/v1/warehouse/w/protection",
        "bash scripts/lakekeeper/protect.sh",
        "mc rm --recursive --force lake/lakehouse/warehouse/x",
        "psql -c \"update shop.orders set order_status = 'x' where order_id = '1'\"",
        'psql -c "alter publication dbz_publication add table cdc.heartbeat"',
        "powercfg.exe /change standby-timeout-ac 0",
        # Uncommitted work.
        "git checkout -- airflow/dags/dq_checks.py",
        "git clean -fd",
        "git stash drop",
        "rm -r data/checkpoints/x",
        # Found by the cold-start review of 27.10.
        "airflow dags unpause --treat-dag-id-as-regex 'iceberg_.*'",
        "airflow dags test iceberg_orphans",
        "airflow tasks test iceberg_maintenance optimize",
        "docker compose -f docker/compose.yaml down",
        "docker compose down --rmi all",
        "docker image remove lakehouse/minio:x",
        "docker --context x image prune -a",
        "docker rm -f lakehouse-spark-bronze-1",
        "docker compose rm -f minio",
        "docker compose stop kafka",
        "$COMPOSE stop kafka",
        "$COMPOSE down",
        "$COMPOSE --profile core run --rm --no-deps spark-silver maintenance expire silver.x",
        "docker kill lakehouse-spark-bronze-1",
        "docker compose start oltp-replayer",
        "bash scripts/replay-burst.sh 60 720",
        "bash scripts/chaos/kafka-down.sh",
        "make replay-load",
        "make cdc-snapshot",
        "make migrate",
        "make watermark-demo",
        "curl --request DELETE 127.0.0.1:8181/management/v1/warehouse/w",
        "curl -d @w.json 127.0.0.1:8181/management/v1/warehouse",
        "curl -X POST 127.0.0.1:8083/connectors/shop-connector/restart",
        "mc cp --recursive lake/lakehouse/warehouse /backup",
        "gh -R o/r workflow run smoke.yml",
        "gh api repos/o/r/actions/workflows/smoke.yml/dispatches -f ref=main",
        "psql -c \"delete from shop.orders where order_id = '1'\"",
        'psql -c "create publication p for table cdc.heartbeat"',
        "psql -c \"select pg_create_logical_replication_slot('s', 'pgoutput')\"",
        "wsl.exe --shutdown",
        "echo '[wsl2]' >> ~/.wslconfig",
        # The agent roles and rules by a shell write, not only through Edit.
        "sed -i s/a/b/ AGENTS.md",
        "cat /tmp/x > CLAUDE.md",
        "cp /tmp/x .claude/agents/scout.md",
        "tee docs/agent-rules.md < /tmp/x",
        "python3 -c \"open('AGENTS.md', 'w').write('')\"",
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
        # Routine steps of the pre-commit cycle and read-only probes stay a click-free path.
        "docker compose --env-file .env -f docker/compose.yaml --profile core build spark-bronze",
        "docker compose exec -T airflow-scheduler airflow dags pause silver_upsert",
        "docker compose exec -T airflow-scheduler airflow dags list-runs iceberg_maintenance",
        "docker compose stop airflow-scheduler",
        "kafka-configs.sh --bootstrap-server localhost:9092 --describe --entity-type topics",
        "gh run list --limit 5",
        "gh run view 40290595866 --log-failed",
        "uv run ruff check airflow/dags/iceberg_orphans.py",
        "uv run pytest tests/unit/test_dags.py -k dry_run -q",
        "curl -s 127.0.0.1:8181/management/v1/warehouse",
        "docker image ls",
        'grep -rn "dry_run": docs',
        "make dags-check",
        "cp .claude/hooks/guard.py /tmp/scratchpad/guard.py",
        # A copy of the hooks outside the repository is where their changes are prepared.
        "cp /tmp/x /tmp/scratchpad/copy/.claude/hooks/guard.py",
        "sed -i s/a/b/ /tmp/scratchpad/copy/.claude/settings.json",
        "docker compose start airflow-scheduler",
        "$COMPOSE stop airflow-scheduler && make verify && $COMPOSE start airflow-scheduler",
        "$COMPOSE --profile core build spark-bronze",
        "docker compose exec -T airflow-scheduler airflow dags unpause silver_upsert",
        "docker run --rm --entrypoint sh lakehouse/spark:dev -c 'sha256sum spark_jobs/*.py'",
        "docker compose logs --tail=200 airflow-scheduler",
        "curl -s 127.0.0.1:8083/connectors/shop-connector/status",
    ],
)
def test_guard_allows(command: str) -> None:
    assert decision(bash(command)) == "allow"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", "deny"),
        ("certs/server.key", "deny"),
        (".env.example", "allow"),
        ("a.md", "allow"),
        # The guard must not be able to edit itself or its settings.
        (".claude/hooks/guard.py", "deny"),
        (".claude/settings.json", "deny"),
        (".claude/settings.local.json", "deny"),
        # Role definitions and the rules: a click from the owner.
        (".claude/agents/reviewer.md", "ask"),
        ("AGENTS.md", "ask"),
        ("CLAUDE.md", "ask"),
        ("docs/agent-rules.md", "ask"),
        ("docs/planning/13-harness.md", "ask"),
        ("docs/HANDOFF.md", "allow"),
        ("/tmp/scratchpad/copy/.claude/hooks/guard.py", "allow"),
        ("/tmp/scratchpad/copy/AGENTS.md", "allow"),
    ],
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


def test_docs_changed_after_a_full_verify_can_be_committed(repo: Path) -> None:
    # The stop gate needs no check for Markdown and docs/; a commit of them needs none either.
    write_stamp(repo, "full")
    (repo / "NOTES.md").write_text("x")
    assert decision(bash("git add -A && git commit -m notes", repo)) == "allow"

    (repo / "job.py").write_text("x = 9\n")
    assert decision(bash("git add -A && git commit -m code", repo)) == "deny"


def test_docs_after_a_fast_verify_do_not_open_the_commit(repo: Path) -> None:
    write_stamp(repo, "fast")
    (repo / "NOTES.md").write_text("x")

    assert decision(bash("git commit -m notes", repo)) == "deny"


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
