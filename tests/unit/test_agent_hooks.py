import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.agent_state import VERDICTS, read_stamp, record_review, tree_hash, write_stamp

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
PHRASE = {mode: phrase for phrase, mode in VERDICTS.items()}
COMMIT = "git add -A && git commit -m change"


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
    (tmp_path / ".gitignore").write_text(".verify-stamp\n.check-stamp\n.review-stamp\n")
    (tmp_path / "job.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def lines(*parts: str) -> str:
    return "".join(f"{part}\n" for part in parts)


def review(root: Path, mode: str = "accept") -> None:
    """The reviewer's verdict on the working tree as it is now, recorded the way the hook does."""
    tree = tree_hash(root)
    record_review(root, lines(f"Вердикт: {PHRASE[mode]}", "Предмет: код", f"Дерево: {tree}"))


def gate_stamps(root: Path, review_mode: str = "accept") -> None:
    """Every step of the gate passed on the working tree as it is now."""
    write_stamp(root, "full")
    write_stamp(root, "check")
    review(root, review_mode)


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
        "echo 'full 2026-10-29T10:00:00Z abc' > .verify-stamp",
        "echo x >> .check-stamp",
        "cp /tmp/x .review-stamp",
        "tee .review-stamp < /tmp/x",
        "touch .check-stamp",
        "rm .review-stamp",
        "sed -i s/a/b/ .verify-stamp",
        "mv /tmp/x .check-stamp 2>/dev/null",
        f"echo x > {REPO}/.review-stamp",
        "python3 scripts/agent_state.py stamp full .",
        "uv run python scripts/agent_state.py stamp check .",
        "python3 -m scripts.agent_state stamp check .",
        "python3 'scripts/agent_state.py' 'stamp' full .",
        'python3 -c "from scripts.agent_state import record_review"',
        "python3 -c \"from scripts.agent_state import write_stamp; write_stamp(None, 'full')\"",
        "python3 - <<'EOF'\nfrom scripts import agent_state as s\ns.write_stamp(None, 'full')\nEOF",
        "python3 -c \"open('.review-stamp', 'w').write('accept x y')\"",
        # Review 29.10, finding 3: forms the first patch let through.
        "python3 -c \"from pathlib import Path; Path('.review-stamp').write_text('x')\"",
        "python3 -c \"import shutil; shutil.copy('/tmp/x', '.review-stamp')\"",
        "python3 -c \"import os; os.replace('/tmp/x', '.check-stamp')\"",
        "dd if=/tmp/x of=.review-stamp",
        "python3 -c \"import scripts.agent_state as s; s._store(s.Path(), s.REVIEW_STAMP, 'a')\"",
        # make check is the only way to the check stamp.
        "python3 scripts/agent_state.py check .",
    ],
)
def test_guard_denies_a_gate_stamp_written_by_hand(command: str) -> None:
    result = bash(command)

    assert decision(result) == "deny"
    assert "writes a gate stamp by hand" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "make -i check",
        "make check -i",
        "make -k check",
        "make --ignore-errors check",
        "make check -o lint -o test",
        "make -o test check",
        "make -C . check",
        "PYTEST_ADDOPTS=--collect-only make check",
        "MAKEFLAGS=-i make check",
        "make check MAKEFLAGS=-i",
        "env PYTEST_ADDOPTS=-x make check",
        "export MAKEFLAGS=i; make check",
    ],
)
def test_guard_denies_make_check_bent_to_stamp_failing_checks(command: str) -> None:
    result = bash(command)

    assert decision(result) == "deny"
    assert "runs make check in a form that can stamp failing checks" in result.stderr


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize("name", [".verify-stamp", ".check-stamp", ".review-stamp"])
def test_guard_denies_every_file_tool_on_a_gate_stamp(tool: str, name: str) -> None:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    result = hook("guard.py", {"tool_name": tool, "tool_input": {key: str(REPO / name)}})

    assert decision(result) == "deny"
    assert "writes a gate stamp by hand" in result.stderr


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
        # The skills, and the code that says what a stamp means.
        "cp /tmp/x .claude/skills/task/SKILL.md",
        "tee .claude/skills/task/SKILL.md < /tmp/x",
        "sed -i s/a/b/ scripts/agent_state.py",
        "cp /tmp/x scripts/agent_state.py",
        f"cat /tmp/x > {REPO}/scripts/agent_state.py",
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
        # The gate is run through make and the hooks; its stamps and tree id are read freely.
        "make check",
        "python3 scripts/agent_state.py tree .",
        "python3 scripts/agent_state.py show review .",
        "git check-ignore .review-stamp",
        "cat .verify-stamp .check-stamp .review-stamp",
        'grep -rn "agent_state.py stamp" scripts Makefile',
        "uv run pytest tests/unit/test_agent_state.py -k record_review -q",
        "uv run pytest tests/unit/test_agent_state.py::test_record_review_ignores_a_line -q",
        "cp scripts/agent_state.py /tmp/scratchpad/agent_state.py",
        # Review 29.10, finding 7: reads and tests of the stamp code are no stamp writes.
        "uv run mypy scripts/agent_state.py && uv run pytest tests/unit -q -k record_review",
        "make check 2>&1 | tail -5",
        "cd /home/user/marketplace-lakehouse && make check",
        "make lint",
        "make test",
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
        # The skills and the code that says what a stamp means: a click from the owner.
        (".claude/skills/task/SKILL.md", "ask"),
        ("scripts/agent_state.py", "ask"),
        ("tests/unit/test_agent_state.py", "allow"),
        ("/tmp/scratchpad/copy/.claude/skills/task/SKILL.md", "allow"),
        ("/tmp/scratchpad/copy/scripts/agent_state.py", "allow"),
        # A stamp outside this repository is no gate stamp.
        ("/tmp/scratchpad/copy/.review-stamp", "allow"),
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
    write_stamp(repo, "check")
    review(repo)
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


def test_commit_of_code_lists_every_step_of_the_gate_it_lacks(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")

    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without a full make verify, make check and a reviewer verdict" in (
        result.stderr
    )
    assert "see docs/planning/13-harness.md, section 5" in result.stderr

    write_stamp(repo, "full")
    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without make check and a reviewer verdict on" in result.stderr

    write_stamp(repo, "check")
    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without a reviewer verdict on" in result.stderr

    review(repo)
    assert decision(bash(COMMIT, repo)) == "allow"


def test_commit_of_code_needs_the_check_and_the_review_even_with_a_full_verify(
    repo: Path,
) -> None:
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "full")
    review(repo)
    result = bash(COMMIT, repo)
    assert decision(result) == "deny" and "git commit without make check on" in result.stderr

    (repo / ".review-stamp").unlink()
    write_stamp(repo, "check")
    result = bash(COMMIT, repo)
    assert decision(result) == "deny" and "git commit without a reviewer verdict on" in (
        result.stderr
    )


@pytest.mark.parametrize("mode", ["accept", "accept-with-notes"])
def test_commit_of_code_goes_with_an_accepting_verdict(repo: Path, mode: str) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo, mode)

    assert decision(bash(COMMIT, repo)) == "allow"


def test_commit_of_code_is_refused_after_a_return_verdict(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo, "return")

    result = bash(COMMIT, repo)

    assert decision(result) == "deny"
    assert "a reviewer verdict other than 'return'" in result.stderr


def test_code_edited_after_the_stamps_needs_all_of_them_again(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo)
    (repo / "job.py").write_text("x = 3\n")

    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "a full make verify, make check and a reviewer verdict" in result.stderr

    gate_stamps(repo)
    assert decision(bash(COMMIT, repo)) == "allow"


def test_a_review_of_older_code_does_not_cover_newer_code(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    review(repo)
    (repo / "job.py").write_text("x = 3\n")
    write_stamp(repo, "full")
    write_stamp(repo, "check")

    result = bash(COMMIT, repo)

    assert decision(result) == "deny"
    assert "git commit without a reviewer verdict on" in result.stderr


def test_a_new_file_after_the_stamps_needs_all_of_them_again(repo: Path) -> None:
    gate_stamps(repo)
    (repo / "extra.py").write_text("y = 1\n")

    assert decision(bash(COMMIT, repo)) == "deny"


def test_docs_changed_after_every_stamp_keep_the_commit_open(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo)
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.txt").write_text("x")
    (repo / "NOTES.md").write_text("x")

    assert decision(bash(COMMIT, repo)) == "allow"


def test_only_docs_changed_needs_a_full_verify_and_nothing_else(repo: Path) -> None:
    (repo / "NOTES.md").write_text("x")
    assert decision(bash("git commit -m notes", repo)) == "deny"

    write_stamp(repo, "full")
    assert not (repo / ".check-stamp").exists() and not (repo / ".review-stamp").exists()
    assert decision(bash("git commit -m notes", repo)) == "allow"


def test_a_verify_before_the_commit_in_one_chain_does_not_replace_check_and_review(
    repo: Path,
) -> None:
    chain = "make verify && git add -A && git commit -m x"
    (repo / "job.py").write_text("x = 2\n")
    result = bash(chain, repo)
    assert decision(result) == "deny"
    assert "git commit without make check and a reviewer verdict on" in result.stderr

    write_stamp(repo, "check")
    review(repo)
    assert decision(bash(chain, repo)) == "allow"
    assert decision(bash("make verify-fast && git commit -m x", repo)) == "deny"


def test_a_stamp_of_a_tree_that_is_gone_counts_as_missing(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "full")
    review(repo)
    (repo / ".check-stamp").write_text(f"check 2026-10-29T10:00:00Z {'0' * 40}\n")

    result = bash(COMMIT, repo)

    assert decision(result) == "deny"
    assert "git commit without make check on" in result.stderr


def reviewer_report(root: Path, mode: str = "accept") -> str:
    tree = tree_hash(root)
    return lines(
        f"Вердикт: {PHRASE[mode]}",
        "Предмет: код",
        "Проверено и чисто: make test",
        f"Дерево: {tree}",
    )


def test_a_late_return_without_a_tree_closes_the_gate_an_accept_opened(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo)
    assert decision(bash(COMMIT, repo)) == "allow"

    late = lines("Вердикт: вернуть", "Предмет: код", "Проверено и чисто: ничего")
    assert hook("review_stamp.py", handback(late), repo).returncode == 0

    result = bash(COMMIT, repo)
    assert decision(result) == "deny" and "other than 'return'" in result.stderr


def test_a_plan_review_neither_opens_nor_closes_the_gate(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "full")
    write_stamp(repo, "check")
    plan = reviewer_report(repo).replace("Предмет: код", "Предмет: план")

    assert hook("review_stamp.py", handback(plan), repo).returncode == 0
    assert decision(bash(COMMIT, repo)) == "deny"

    review(repo)
    assert (
        hook("review_stamp.py", handback(plan.replace("принять", "вернуть")), repo).returncode == 0
    )
    assert decision(bash(COMMIT, repo)) == "allow"


def handback(report: str, agent: str = "reviewer") -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "SubagentHandback",
        "agent_type": agent,
        "agent_id": "a1",
        "tool_input": {"message": report},
        "tool_response": "delivered",
    }


def stopped(report: str | None, agent: str = "reviewer") -> dict[str, Any]:
    event: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "agent_type": agent,
        "agent_id": "a1",
        "stop_hook_active": False,
    }
    if report is not None:
        event["last_assistant_message"] = report
    return event


def test_a_handback_of_the_reviewer_records_its_verdict(repo: Path) -> None:
    result = hook("review_stamp.py", handback(reviewer_report(repo)), repo)

    stamp = read_stamp(repo, "review")
    assert result.returncode == 0 and result.stdout == ""
    assert stamp is not None and stamp.mode == "accept" and stamp.fresh
    assert "accept" in result.stderr


def test_the_report_of_another_agent_is_not_recorded(repo: Path) -> None:
    report = reviewer_report(repo)

    for agent in ("scout", "implementer", "Explore", "pr-review-toolkit:code-reviewer", ""):
        assert hook("review_stamp.py", handback(report, agent), repo).returncode == 0
        assert hook("review_stamp.py", stopped(report, agent), repo).returncode == 0
    no_agent = {"hook_event_name": "PostToolUse", "tool_input": {"message": report}}
    assert hook("review_stamp.py", no_agent, repo).returncode == 0

    assert read_stamp(repo, "review") is None


def test_subagent_stop_of_the_reviewer_records_its_verdict(repo: Path) -> None:
    result = hook("review_stamp.py", stopped(reviewer_report(repo, "accept-with-notes")), repo)

    stamp = read_stamp(repo, "review")
    assert result.returncode == 0
    assert stamp is not None and stamp.mode == "accept-with-notes" and stamp.fresh


@pytest.mark.parametrize("closing", [None, "", "Report delivered."])
def test_subagent_stop_after_a_handback_leaves_the_stamp_as_it_is(
    repo: Path, closing: str | None
) -> None:
    hook("review_stamp.py", handback(reviewer_report(repo)), repo)
    before = (repo / ".review-stamp").read_text()

    result = hook("review_stamp.py", stopped(closing), repo)

    assert result.returncode == 0
    assert (repo / ".review-stamp").read_text() == before


def test_a_closing_text_with_a_return_verdict_revokes_the_stamp(repo: Path) -> None:
    hook("review_stamp.py", handback(reviewer_report(repo)), repo)

    result = hook("review_stamp.py", stopped("Вердикт: вернуть"), repo)

    stamp = read_stamp(repo, "review")
    assert result.returncode == 0 and "revoked" in result.stderr
    assert stamp is not None and stamp.mode == "return"


def test_each_event_is_read_from_its_own_field(repo: Path) -> None:
    report = reviewer_report(repo)
    stop_with_a_message = {**stopped(None), "tool_input": {"message": report}}
    handback_with_a_closing_text = {**handback(""), "last_assistant_message": report}

    assert hook("review_stamp.py", stop_with_a_message, repo).returncode == 0
    assert hook("review_stamp.py", handback_with_a_closing_text, repo).returncode == 0

    assert read_stamp(repo, "review") is None


def test_a_verdict_for_code_that_changed_since_is_not_recorded(repo: Path) -> None:
    report = reviewer_report(repo)
    (repo / "job.py").write_text("x = 2\n")

    result = hook("review_stamp.py", handback(report), repo)

    assert result.returncode == 0 and "nothing recorded" in result.stderr
    assert read_stamp(repo, "review") is None


def test_the_review_hook_never_fails_the_session(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    for garbage in ("not json", "", "[]", '"x"', "null", '{"agent_type": "reviewer"}'):
        result = subprocess.run(
            [sys.executable, str(HOOKS / "review_stamp.py")],
            input=garbage,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0, garbage
    assert read_stamp(repo, "review") is None

    # The repo fixture made tmp_path a repository; this directory is outside any.
    outside = tmp_path_factory.mktemp("not-a-repo")
    result = hook(
        "review_stamp.py", handback(lines("Вердикт: принять", f"Дерево: {'a' * 40}")), outside
    )
    assert result.returncode == 0 and "could not record" in result.stderr
    assert list(outside.iterdir()) == []


def test_settings_wire_the_review_hook_and_make_the_guard_fail_closed() -> None:
    settings = json.loads((REPO / ".claude" / "settings.json").read_text())
    hooks = settings["hooks"]

    def commands(event: str, matcher: str) -> list[str]:
        return [
            handler["command"]
            for group in hooks[event]
            if group.get("matcher") == matcher
            for handler in group["hooks"]
        ]

    assert any("review_stamp.py" in c for c in commands("PostToolUse", "SubagentHandback"))
    assert any("review_stamp.py" in c for c in commands("SubagentStop", "reviewer"))
    guards = [
        h for group in hooks["PreToolUse"] for h in group["hooks"] if "guard.py" in h["command"]
    ]
    assert guards and all(handler.get("onFailure") == "block" for handler in guards)
    for plugin in (
        "feature-dev@claude-plugins-official",
        "pr-review-toolkit@claude-plugins-official",
    ):
        assert settings["enabledPlugins"][plugin] is False
    assert (HOOKS / "review_stamp.py").exists()
