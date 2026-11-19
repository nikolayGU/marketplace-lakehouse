import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.agent_state import VERDICTS, read_stamp, record_review, tree_hash, write_stamp

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
PHRASE = {mode: phrase for phrase, mode in VERDICTS.items()}
COMMIT = "git add -A && git commit -m change"


def _load_guard() -> Any:
    spec = importlib.util.spec_from_file_location("guard_in_process", HOOKS / "guard.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(REPO)  # guard.py reads it once, at import
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is None:
            del os.environ["CLAUDE_PROJECT_DIR"]
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
    return module


GUARD = _load_guard()


def run_guard(event: dict[str, Any], root: Path | None = None) -> subprocess.CompletedProcess[str]:
    """guard.py's main() in this process: the exit code, stdout and stderr of a hook run."""
    out, err = io.StringIO(), io.StringIO()
    saved_root, saved_stdin = GUARD.ROOT, sys.stdin
    GUARD.ROOT = root or REPO
    sys.stdin = io.StringIO(json.dumps(event))
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            GUARD.main()
    except SystemExit as exit_:
        code = int(exit_.code or 0)
    finally:
        GUARD.ROOT, sys.stdin = saved_root, saved_stdin
    return subprocess.CompletedProcess([], code, out.getvalue(), err.getvalue())


def hook(
    name: str, event: dict[str, Any], root: Path | None = None
) -> subprocess.CompletedProcess[str]:
    if name == "guard.py":
        return run_guard(event, root)
    return hook_process(name, event, root)


def hook_process(
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
    """deny, ask or allow; the ask of a guard that failed is `crash`, never a rule's ask."""
    if "guard.py failed" in result.stdout:
        return "crash"
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
        # The writer in text the interpreter reads from a pipe, after a flag and across a line
        # break (moved from the forms of an unusual interpreter call).
        "echo \"from scripts import agent_state as s; s.write_stamp(None, 'full')\" | python3",
        "python3 -X 'a;b' -c \"from scripts.agent_state import write_stamp\"",
        'python3 \\\n-c "from scripts.agent_state import write_stamp"',
    ],
)
def test_guard_denies_a_gate_stamp_written_by_hand(command: str) -> None:
    result = bash(command)

    assert decision(result) == "deny"
    assert "writes a gate stamp by hand" in result.stderr


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
        # Stopping the stack by make is the same act as stopping it by compose.
        "make down",
        "make down PROFILE=tools",
        "make down PROFILE=obs,query",
        "PROFILE=bi make down",
    ],
)
def test_guard_asks_the_owner(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "AGENTS.md hard rule" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        # A read of .env is a read of every password of the stack, even though it only reads.
        "cat .env",
        "cat ./.env",
        f"cat {REPO}/.env",
        "cat .env.local",
        'cat "$PWD/.env"',
        "less .env",
        "more .env",
        "head -5 .env",
        "tail -n 3 .env",
        "tac .env | head -2",
        "grep REPLAY .env",
        "grep -n PASSWORD ./.env",
        "grep -f .env README.md",
        "rg POSTGRES .env",
        "awk -F= '{print $1}' .env",
        "sed -n 1,5p .env",
        "source .env",
        ". .env",
        "set -a; . ./.env; set +a",
        "cat < .env",
        "cat<.env",
        "export $(cat .env | xargs)",
        "echo `cat .env`",
        "bash -c 'cat .env'",
        "cd /tmp && cat .env",
        "git status\ncat .env",
        "diff .env .env.example",
        "cp .env /tmp/copy",
        "env X=1 cat .env",
        "python3 -c \"print(open('.env').read())\"",
        "uv run python -c \"from pathlib import Path; print(Path('.env').read_text())\"",
        "python3 - <<'EOF'\nprint(open('.env').read())\nEOF",
        # The compose file with the values of .env filled in, and the environment of a container.
        "docker compose --env-file .env -f docker/compose.yaml config",
        "docker compose --env-file .env -f docker/compose.yaml --profile '*' config",
        "docker compose --env-file .env -f docker/compose.yaml --profile core config | head -20",
        "$COMPOSE --profile core config",
        "docker-compose -f docker/compose.yaml config",
        "docker --context x compose -f docker/compose.yaml config",
        "docker compose -f docker/compose.yaml config --format json",
        "docker compose -f docker/compose.yaml config -o /tmp/resolved.yaml",
        "docker compose -f docker/compose.yaml config --no-interpolate --format json",
        "docker inspect lakehouse-postgres-oltp-1",
        "docker container inspect lakehouse-postgres-oltp-1",
        "docker inspect lakehouse-postgres-oltp-1 | jq '.[0].Config.Env'",
        "docker inspect lakehouse-trino-1 -f '{{.Config.Env}}'",
        "docker inspect --format '{{json .Config.Env}}' lakehouse-trino-1",
        "docker inspect --format='{{range .Config.Env}}{{println .}}{{end}}' lakehouse-trino-1",
        "docker inspect --format '{{json .}}' lakehouse-trino-1",
        "docker inspect -f '{{json .Config}}' lakehouse-trino-1",
        "docker inspect -f '{{.State.Status}}' a -f '{{.Config.Env}}' b",
        # The whole object, which holds Config.Env, by the json shortcut or a pipe.
        "docker inspect --format json lakehouse-trino-1",
        "docker inspect --format=json lakehouse-trino-1",
        "docker inspect -f json lakehouse-trino-1",
        "docker inspect -f '{{.Config | json}}' lakehouse-trino-1",
        "docker inspect -f '{{ . | json }}' lakehouse-trino-1",
        "docker inspect -f '{{(index . 0).Config}}' lakehouse-trino-1",
        # The first segment is a free cp; the read of .env after it is not. The command must come
        # out as ask: a deny of the cp (a SHELL_WRITE_ENV that reaches over `&&`) is a wrong answer.
        "cp .env.example /tmp/a && grep REPLAY .env",
        # A quoted word with parentheses is an argument, not the start of another command.
        "grep 'foo(' .env",
        'grep "print(1)" ./.env',
        "cat 'a (b)' .env",
        # More ways to open .env, and to print the environment of a container.
        "jq -R . .env",
        "jq -Rr 'split(\"=\")[1]' ./.env",
        "yq . .env",
        'echo "$(<.env)"',
        "echo $(<.env)",
        'echo "$(cat .env)"',
        'x="$(head -1 .env)"; echo "$x"',
        'echo "`cat .env`"',
        "docker exec lakehouse-postgres-oltp-1 env",
        "docker exec lakehouse-postgres-oltp-1 printenv",
        "docker exec -it lakehouse-postgres-oltp-1 printenv POSTGRES_PASSWORD",
        "docker exec -e A=b lakehouse-postgres-oltp-1 env",
        "docker exec lakehouse-postgres-oltp-1 sh -c env",
        "docker exec lakehouse-postgres-oltp-1 cat /proc/1/environ",
        "docker compose --env-file .env -f docker/compose.yaml exec postgres-oltp env",
        "docker compose --env-file .env -f docker/compose.yaml exec -T trino printenv",
        "docker compose --env-file .env -f docker/compose.yaml exec -T -u root kafka printenv",
        "$COMPOSE exec -T kafka env",
        "docker compose --env-file .env -f docker/compose.yaml run --rm spark-silver env",
    ],
)
def test_guard_asks_before_a_command_shows_a_secret(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "AGENTS.md hard rule" in result.stdout
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        # The example file holds no secret, and `--env-file .env` hands the file to compose.
        "cat .env.example",
        "head -5 .env.example",
        "grep -n BIND_IP .env.example",
        "sed -n 1,5p .env.example",
        "cat < .env.example",
        "diff .env.example /tmp/other",
        "cp .env.example /tmp/a && grep REPLAY .env.example",
        "cat docker/airflow/airflow.env",
        "ls -la .env",
        "git check-ignore .env",
        # A pattern that names .env is not a file that is read.
        "grep -rn '.env' docs",
        'grep -rn "\\.env" docs',
        "rg -n '.env' Makefile",
        'echo "copy .env.example to .env"',
        "docker compose --env-file .env -f docker/compose.yaml config -q",
        "docker compose --env-file .env -f docker/compose.yaml --profile '*' config --quiet",
        "$COMPOSE --profile '*' config -q",
        "docker compose --env-file .env -f docker/compose.yaml config --services",
        "docker compose --env-file .env -f docker/compose.yaml config --profiles",
        "docker compose --env-file .env -f docker/compose.yaml config --images",
        "docker compose --env-file .env -f docker/compose.yaml config --volumes",
        "docker compose --env-file .env -f docker/compose.yaml --profile core ps",
        "docker compose --env-file .env -f docker/compose.yaml logs --tail=50 config",
        "docker inspect lakehouse-trino-1 -f '{{.State.Status}}'",
        "docker inspect --format '{{.State.Health.Status}}' lakehouse-trino-1 lakehouse-kafka-1",
        "docker inspect --format='{{.HostConfig.RestartPolicy.Name}}' lakehouse-trino-1",
        "docker container inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' lakehouse-trino-1",
        "docker inspect -f '{{.Config.Image}}' lakehouse-trino-1",
        "docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' lakehouse-trino-1",
        "docker inspect -f '{{json .State}}' lakehouse-trino-1",
        "docker inspect -f '{{.Config.Labels | json}}' lakehouse-trino-1",
        # `--env-file .env` hands the file to compose; it does not make the command read it.
        "docker compose --env-file .env -f docker/compose.yaml exec -T airflow-scheduler "
        "python -c 'print(1)'",
        "docker compose --env-file=.env -f docker/compose.yaml exec -T airflow-scheduler "
        "python -c 'print(1)'",
        "docker compose --env-file .env -f docker/compose.yaml exec -T airflow-scheduler "
        "airflow dags list",
        # Running something in a container is not printing its environment.
        "docker exec lakehouse-postgres-oltp-1 pg_isready",
        "docker exec lakehouse-postgres-oltp-1 psql -c 'select 1'",
        "docker exec lakehouse-postgres-oltp-1 env PGOPTIONS=x psql -c 'select 1'",
        "docker compose --env-file .env -f docker/compose.yaml exec -T trino trino --version",
        "make status",
        "make downstream",
        "grep down Makefile",
        "make -n downgrade",
    ],
)
def test_guard_lets_a_command_that_shows_no_secret_pass(command: str) -> None:
    assert decision(bash(command)) == "allow"


# B11 was rolled back: the guard pairs inline code with .env over the whole command, so a
# mention of .env in another command still opens the window (an accepted false positive). A
# pairing per command missed the forms below, each of which reads .env and must ask.
@pytest.mark.parametrize(
    "command",
    [
        "python3 -c \"import os; print(open('.env').read())\"",
        "python3 -c\"print(open('.env').read())\"",
        "python3 - <<'EOF'\nimport os; print(open('.env').read())\nEOF",
        "python3 - <<< \"print(open('.env').read())\"",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' $(pwd)/.env",
        "f=.env; python3 -c \"print(open('$f').read())\"",
        "echo .env | xargs python3 -c 'import sys; print(open(sys.argv[1]).read())'",
        "node -e\"console.log(require('fs').readFileSync('.env','utf8'))\"",
        "perl -e 'open(F, \".env\"); print <F>' && echo done",
        "python3 -c \\\n\"print(open('.env').read())\"",
    ],
)
def test_inline_code_that_names_env_is_still_asked(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


READS_ENV = "print(open('.env').read())"


# B14: the interpreter gets its code without `-c` and `-`, or the line is cut between the
# interpreter and its flag, or an option value hides a `;` from the segment. Each form reads .env.
@pytest.mark.parametrize(
    "command",
    [
        f"cat <<'EOF' | python3\n{READS_ENV}\nEOF",
        f'echo "{READS_ENV}" | python3',
        "echo 'f=.env; cat $f' | sh",
        "bash <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        "echo 'cat .env' | xargs -I{} bash -c {}",
        "cat \\\n.env",
    ],
)
def test_guard_asks_when_the_code_reaches_the_interpreter_in_an_unusual_way(
    command: str,
) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'EOF' | python3\nprint(1)\nEOF",
        "echo 'print(1)' | python3",
        "cat <<'EOF' | bash\necho hi\nEOF",
        "cat <<'EOF' | sh\ncat .env.example\nEOF",
        "echo 'cat .env.example' | bash",
        "python3 \\\n-c 'print(1)'",
        "cat \\\n.env.example",
        "python3 -X 'a;b' -c 'print(1)'",
        "cat Makefile | python3 -m json.tool",
        "ls scripts | grep sh",
    ],
)
def test_guard_lets_the_unusual_forms_without_env_pass(command: str) -> None:
    assert decision(bash(command)) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "echo 'print(1)' | python3 -u",
        "python3 -X 'a;b' scripts/agent_state.py tree .",
        "cat scripts/agent_state.py | head -5",
        "git diff scripts/agent_state.py | python3 render.py",
    ],
)
def test_guard_allows_the_unusual_forms_that_do_not_touch_the_stamp_code(command: str) -> None:
    assert decision(bash(command)) == "allow"


# A comment runs to the end of the line, and a backslash in it does not continue it. Joining the
# lines would hide the command on the next line inside the comment, so both texts are checked.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ls # list files \\\ncat .env", "ask"),
        ("echo start # note \\\ncat .env", "ask"),
        ("git status # see \\\ngrep PASS .env", "ask"),
        ("make test # run \\\nhead .env", "ask"),
        ("ls # x \\\npython3 scripts/agent_state.py stamp full", "deny"),
        ("ls # x \\\ntouch .verify-stamp", "deny"),
        # The name is cut by the continuation: only the joined text shows it, and deny beats ask.
        ("cat .env; touch .verify\\\n-stamp", "deny"),
        # Not a comment: the continuation joins the lines, as before.
        ("python3 \\\n  -c \"print(open('.env').read())\"", "ask"),
        ("cat \\\n.env", "ask"),
        ("cat \\\n.env.example", "allow"),
        ("make test \\\n  2>&1 | tail -3", "allow"),
        ("echo hi \\\n && echo there", "allow"),
    ],
)
def test_a_backslash_in_a_comment_does_not_hide_the_next_line(command: str, expected: str) -> None:
    assert decision(bash(command)) == expected


def test_a_secret_read_is_asked_before_the_early_exit_of_read_only_commands() -> None:
    # cat is a reader and passes on its own words; .env is what makes the difference.
    assert decision(bash("cat Makefile")) == "allow"
    assert decision(bash("cat Makefile .env")) == "ask"
    assert decision(bash("git log -1 && cat .env")) == "ask"


def test_a_shell_write_to_env_is_still_denied_not_asked() -> None:
    assert decision(bash("cp /tmp/x .env")) == "deny"
    assert decision(bash("grep KEY f > .env")) == "deny"
    assert decision(bash("sed -i s/a/b/ .env")) == "deny"


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


def forms(finding: str, *commands: str) -> list[Any]:
    """The commands of one audit finding as test cases, numbered under its id."""
    return [pytest.param(command, id=f"{finding}-{at}") for at, command in enumerate(commands, 1)]


COMPOSE = "docker compose --env-file .env -f docker/compose.yaml"


# HG-01..HG-04: the usual forms of a write to the lake, a publication drop, a stop of the stack
# and lost work that the guard once let through.
@pytest.mark.parametrize(
    "command",
    [
        *forms(
            "HG-02",
            f'{COMPOSE} exec -T postgres-oltp psql -U postgres -d shop -c "DROP PUBLICATION dbz"',
        ),
        *forms(
            "HG-01",
            f'{COMPOSE} exec -T trino trino --execute "update lake.silver.orders set '
            "order_status = 'x' where order_id = '1'\"",
            f'{COMPOSE} exec -T trino trino --execute "delete from lake.silver.orders '
            "where order_id = '1'\"",
            f'{COMPOSE} exec -T trino trino --execute "insert into lake.bronze.cdc_events '
            'select * from lake.bronze.cdc_events limit 1"',
            f'{COMPOSE} exec -T trino trino --execute "merge into lake.silver.orders t '
            'using x s on t.id = s.id when matched then delete"',
        ),
        *forms(
            "HG-12",
            "make silver; make reconcile",
            "(cd /repo && make silver)",
            "make silver|tail -3",
            "make silver&&make reconcile",
            "make bootstrap;",
            "make down; make start",
            "(make start)",
            "make silver>/tmp/silver.log 2>&1",
            "git checkout .; git status",
            "(git checkout .)",
            "git checkout .&& git status",
            "git checkout -f; git status",
            "docker compose up; docker compose ps",
            "(docker compose up)",
        ),
        *forms(
            "HG-03",
            "docker compose stop airflow-scheduler kafka",
            f"{COMPOSE} stop airflow-scheduler spark-bronze",
        ),
        *forms(
            "HG-04",
            "git checkout HEAD -- airflow/dags/dq_checks.py",
            "git checkout main -- .",
            "git switch -f main",
            "git checkout -f main",
            "find data/checkpoints -name '*.crc' -delete",
        ),
    ],
)
def test_guard_asks_for_the_usual_forms_it_once_let_through(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "AGENTS.md hard rule" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "git checkout -b x",
        "git checkout main",
        "git switch main",
        "find data -name '*.crc' -print",
        f"{COMPOSE} stop airflow-scheduler && make verify && {COMPOSE} start airflow-scheduler",
        "$COMPOSE stop airflow-scheduler && make verify && $COMPOSE start airflow-scheduler",
        "docker compose stop airflow-scheduler",
    ],
)
def test_the_neighbours_of_the_usual_forms_stay_free(command: str) -> None:
    assert decision(bash(command)) == "allow"


# The words of a command that runs are put back in one line for the patterns: a word with a space
# keeps its quotes, a variable stays a variable.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git -c 'user.name=a b' push origin main", "ask"),
        ("git --git-dir=$REPO/.git push origin main", "ask"),
        ("git -C $REPO push --force", "deny"),
        ("psql -c 'select 1; drop table t'", "deny"),
        ("psql -c 'select 1; delete from t where x = 1'", "allow"),
    ],
)
def test_the_patterns_still_see_a_command_with_an_odd_word(command: str, expected: str) -> None:
    assert decision(bash(command)) == expected


# an apostrophe in a comment does not join the lines around it.
# The decisions are those of the guard before this change.
FORMS_A = [
    (
        "ls # it's here\ngit push orgin main\nls # that's it",
        "ask",
    ),
    (
        "echo start # don't\nmake silver\necho done # that's all",
        "ask",
    ),
    (
        "cat README.md # what's here\ndocker compose down\nls # that's it",
        "ask",
    ),
    (
        "ls # it's\necho X=1 >> .env\nls # it's",
        "deny",
    ),
    (
        "ls # it's\ncp /tmp/g.py .claude/hooks/guard.py\nls # it's",
        "deny",
    ),
    (
        "ls # it's\ntouch .verify-stamp\nls # it's",
        "deny",
    ),
    (
        "ls # it's\npsql -c \"drop table shop.orders\"\nls # it's",
        "deny",
    ),
    (
        "ls # it's\ngit push --force orgin main\nls # it's",
        "deny",
    ),
    (
        "git status # what's changed\ngit push orgin main\ngit log -1 # that's the head",
        "ask",
    ),
]

# the message of a commit is dropped as an argument of that commit only.
# The decisions are those of the guard before this change.
FORMS_B = [
    (
        'grep -rn \'git commit -m "\' docs; git push orgin main; echo "done"',
        "ask",
    ),
    (
        "git commit -m 'x' && git push orgin main",
        "ask",
    ),
    (
        'git commit -m "it\'s" && git push orgin main && echo "ok"',
        "ask",
    ),
    (
        "git log --grep \"git commit -m 'x\" ; git push orgin main ; echo 'y'",
        "ask",
    ),
    (
        "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\" && git push orgin main",
        "ask",
    ),
]

# a here-document belongs to the command it follows, not to an earlier cat.
# The decisions are those of the guard before this change.
FORMS_C = [
    (
        "cat a.sql 2>/dev/null; psql -d shop <<'SQL'\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "cat a.sql; psql -d shop <<'SQL' > /tmp/out.txt\ndelete from shop.orders;\nSQL",
        "deny",
    ),
    (
        "cat x; bash <<'EOF' > /tmp/log\ncp /tmp/g.py .claude/hooks/guard.py\nEOF",
        "deny",
    ),
    (
        "cat x; bash <<'EOF' > /tmp/log\ngit push orgin main\nEOF",
        "ask",
    ),
    (
        "wc -l x.sql && cat x.sql && bash <<'EOF' 2>&1\nmake silver\nEOF",
        "ask",
    ),
    (
        "cat > >(psql -d shop) <<'SQL'\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "cat <<'SQL' > /tmp/x.sql && psql -f /tmp/x.sql\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "cat <<'EOF' | bash\ngit push orgin main\nEOF",
        "ask",
    ),
    (
        "psql -d shop <<'SQL'\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "bash <<'EOF' 2>&1\nmake silver\nEOF",
        "ask",
    ),
    (
        "cat > /tmp/n.md <<'EOF'\nnotes\nEOF\ngit push orgin main",
        "ask",
    ),
    (
        "cat > /tmp/n.md <<-'EOF'\n\tnotes\n\tEOF\ngit push orgin main",
        "ask",
    ),
    (
        "cat > /tmp/a <<'A'\nx\nA\npsql <<'SQL'\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "cat x.sql | psql -d shop; cat > /tmp/n.md <<'EOF'\ndrop table shop.orders\nEOF",
        "deny",
    ),
    (
        "ls; cat > /tmp/n.md <<'EOF'; git push orgin main\nbody\nEOF",
        "ask",
    ),
]

# every command of a group before a pipe feeds it.
# The decisions are those of the guard before this change.
FORMS_D = [
    (
        '(echo "drop table shop.orders;"; echo "select 1;") | psql -d shop',
        "deny",
    ),
    (
        '(echo "git push orgin main"; echo) | bash',
        "ask",
    ),
    (
        '(echo "drop table shop.orders;" && echo x) | psql',
        "deny",
    ),
    (
        '( echo "drop table shop.orders;" ) | psql',
        "deny",
    ),
    (
        'echo "drop table shop.orders;" | (psql)',
        "deny",
    ),
    (
        '{ echo "drop table shop.orders;"; echo x; } | psql',
        "deny",
    ),
    (
        "echo .verify-stamp | xargs touch",
        "deny",
    ),
    (
        "ls .verify-stamp .check-stamp | xargs cp /tmp/fake",
        "deny",
    ),
    (
        "printf '%s\\n' \"drop table shop.orders;\" | psql",
        "deny",
    ),
    (
        'echo "drop table shop.orders;" |& psql',
        "deny",
    ),
    (
        'echo "drop table shop.orders;" | tee /tmp/q.sql | psql',
        "deny",
    ),
    (
        'echo "drop table shop.orders;" > /tmp/q.sql && psql -f /tmp/q.sql',
        "deny",
    ),
    (
        'echo "drop table shop.orders;" \\\n | psql',
        "deny",
    ),
    (
        'if true; then echo "drop table shop.orders;"; fi | psql',
        "deny",
    ),
    (
        'echo "drop table shop.orders;" | sudo -u postgres psql',
        "deny",
    ),
    (
        "grep -h 'drop table shop.orders' a.sql | psql",
        "deny",
    ),
]

# the HTTP write rule sees the whole text.
# The decisions are those of the guard before this change.
FORMS_E = [
    (
        "C=http://localhost:8083/connectors; curl -s -X PUT -H 'Conte"
        "nt-Type: application/json' $C/olist/config -d @connect/x.jso"
        "n",
        "ask",
    ),
    (
        "URL=localhost:8181/catalog/v1; curl -X POST $URL/x -d '{}'",
        "ask",
    ),
    (
        "export C=http://localhost:8083/connectors && curl -X DELETE $C/olist",
        "ask",
    ),
    (
        "curl -X PUT http://localhost:8083/connectors/x/config -d @f.json",
        "ask",
    ),
]

# a newline inside quotes does not end the command.
# The decisions are those of the guard before this change.
FORMS_F = [
    (
        'psql -c "delete from shop.orders\nwhere id = 1"',
        "ask",
    ),
    (
        'trino --execute "delete from shop.orders\n  where x = 1"',
        "ask",
    ),
]

# the usual forms of a write keep the decision they had.
# The decisions are those of the guard before this change, except
# G-38: HG-04
FORMS_G = [
    (
        "echo X=1 >> .env",
        "deny",
    ),
    (
        "cp /tmp/g.py .claude/hooks/guard.py",
        "deny",
    ),
    (
        "sed -i s/a/b/ .claude/settings.json",
        "deny",
    ),
    (
        "touch .verify-stamp",
        "deny",
    ),
    (
        "git push orgin main",
        "ask",
    ),
    (
        "git push --force orgin main",
        "deny",
    ),
    (
        "git -C /repo push origin main",
        "ask",
    ),
    (
        'git -C "$HOME/marketplace-lakehouse" push',
        "ask",
    ),
    (
        "git --git-dir=/repo/.git push",
        "ask",
    ),
    (
        'psql -c "drop table shop.orders"',
        "deny",
    ),
    (
        'psql -c "delete from shop.orders"',
        "deny",
    ),
    (
        "make silver",
        "ask",
    ),
    (
        "docker compose down",
        "ask",
    ),
    (
        "docker compose down -v",
        "ask",
    ),
    (
        "make down",
        "ask",
    ),
    (
        "cd /tmp && git push orgin main",
        "ask",
    ),
    (
        "(git push orgin main)",
        "ask",
    ),
    (
        "time git push orgin main",
        "ask",
    ),
    (
        "sudo git push orgin main",
        "ask",
    ),
    (
        "env X=1 git push orgin main",
        "ask",
    ),
    (
        "nohup make silver &",
        "ask",
    ),
    (
        "make silver 2>&1 | tee /tmp/log",
        "ask",
    ),
    (
        "make silver > /tmp/log 2>&1",
        "ask",
    ),
    (
        "bash -c 'git push orgin main'",
        "ask",
    ),
    (
        "timeout 600 make silver",
        "ask",
    ),
    (
        "$COMPOSE down",
        "ask",
    ),
    (
        "echo y | make silver",
        "ask",
    ),
    (
        "git -c user.name=x push",
        "ask",
    ),
    (
        "cp /tmp/a.md AGENTS.md",
        "ask",
    ),
    (
        "cat /tmp/x > .claude/hooks/guard.py",
        "deny",
    ),
    (
        "tee .env < /tmp/x",
        "deny",
    ),
    (
        "cp /tmp/x .env",
        "deny",
    ),
    (
        "git push origin HEAD:main --force-with-lease",
        "deny",
    ),
    (
        "git push origin +main",
        "deny",
    ),
    (
        "git push orgin main # it's",
        "ask",
    ),
    (
        'echo "a" && git push orgin main # it\'s',
        "ask",
    ),
    (
        "rm -rf data/checkpoints",
        "ask",
    ),
    (
        "find data -delete",
        "ask",
    ),
    (
        "python3 -c \"from scripts.agent_state import write_stamp; write_stamp(None, 'full')\"",
        "deny",
    ),
    (
        "uv run python scripts/agent_state.py stamp .",
        "deny",
    ),
    (
        "echo x > .verify-stamp",
        "deny",
    ),
    (
        "cat /tmp/x | tee .verify-stamp",
        "deny",
    ),
    (
        "git -C /repo push 2>&1 | tail -3",
        "ask",
    ),
    (
        "ls && git push orgin main",
        "ask",
    ),
    (
        "echo ok; make silver",
        "ask",
    ),
    (
        "true && make silver",
        "ask",
    ),
    (
        "[ -f x ] && make silver",
        "ask",
    ),
    (
        "cat a | grep b | make silver",
        "ask",
    ),
    (
        "git log -1 | git push orgin main",
        "ask",
    ),
]

# more forms of the same families.
# The decisions are those of the guard before this change, except
# H-15: the body of a cat that writes a file is data
FORMS_H = [
    (
        'git commit -m "$(git push origin main)"',
        "ask",
    ),
    (
        'git commit -m "`git push origin main`"',
        "ask",
    ),
    (
        'git commit -m "x $(cp /tmp/g.py .claude/hooks/guard.py)"',
        "deny",
    ),
    (
        '(cat a.sql; echo "truncate shop.orders;") | psql -d shop',
        "deny",
    ),
    (
        'docker compose exec -T postgres-oltp psql -U postgres -d shop -c "truncate shop.orders"',
        "deny",
    ),
    (
        "diff <(echo a) <(git push origin main)",
        "ask",
    ),
    (
        'echo "drop table shop.orders" > >(psql)',
        "deny",
    ),
    (
        'ls # say "hi\ngit push origin main\nls # "',
        "ask",
    ),
    (
        "ls # it's\ngit push origin main\nls # it's\nmake lint",
        "ask",
    ),
    (
        "make lint # it's\ngit push origin main\nls # it's",
        "ask",
    ),
    (
        'echo "drop table shop.orders;" | psql # it\'s',
        "deny",
    ),
    (
        'cat x 2>/dev/null; echo ".env" | xargs cat',
        "allow",
    ),
    (
        "echo $'git push origin main' | bash",
        "ask",
    ),
    (
        '(echo "BEGIN;"; cat x.sql; echo "drop table shop.orders;"; echo "COMMIT;") | psql -d shop',
        "deny",
    ),
    (
        "cat <<'EOF' >> /tmp/n.md\ndocker compose down\nEOF",
        "allow",
    ),
    (
        "cat <<'EOF' >/tmp/n.md && git push origin main\nnote\nEOF",
        "ask",
    ),
    (
        "cat a; docker compose down <<'EOF' > /tmp/x\nyes\nEOF",
        "ask",
    ),
    (
        "cat a; psql <<'SQL' >/dev/null\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "head -1 x; cat y; touch .verify-stamp <<'EOF' >/tmp/l\nEOF",
        "deny",
    ),
    (
        "cat a; bash <<'EOF' >/tmp/l\ntouch .verify-stamp\nEOF",
        "deny",
    ),
    (
        "cat a; bash <<'EOF' >/tmp/l\necho X=1 >> .env\nEOF",
        "deny",
    ),
]

# groups with a redirect before the pipe, the body of a here-document.
# The decisions are those of the guard before this change, except
# I-8: the body of a cat that writes a file is data when its delimiter is quoted
# I-16: the body of a cat that writes a file is data
FORMS_I = [
    (
        '(echo "drop table shop.orders;"; echo "select 1;") 2>&1 | psql -d shop',
        "deny",
    ),
    (
        '{ echo "drop table shop.orders;"; echo "select 1;"; } 2>&1 | psql -d shop',
        "deny",
    ),
    (
        '(echo "drop table shop.orders;"; echo "select 1;") |& psql -d shop',
        "deny",
    ),
    (
        '(echo "drop table shop.orders;"; echo "select 1;") >&2 | psql -d shop',
        "deny",
    ),
    (
        "cat > /tmp/x <<EOF\n$(git push orgin main)\nEOF",
        "ask",
    ),
    (
        "cat > /tmp/x <<EOF\n`cp /tmp/g.py .claude/hooks/guard.py`\nEOF",
        "deny",
    ),
    (
        "cat > /tmp/x <<EOF\nnote $(touch .verify-stamp)\nEOF",
        "deny",
    ),
    (
        "cat > /tmp/x <<'EOF'\n$(git push orgin main)\nEOF",
        "allow",
    ),
    (
        "psql -d shop <<'SQL'\necho it's\nSQL\ngit push orgin main\necho that's",
        "ask",
    ),
    (
        "psql -d shop <<'SQL'\n# note\ndrop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "echo $#; git push orgin main",
        "ask",
    ),
    (
        "cat > /tmp/x.sh <<'EOF'\ngit push orgin main\nEOF\nbash /tmp/x.sh",
        "ask",
    ),
    (
        "cat > /tmp/f <<'EOF' # it's\nbody\nEOF\ngit push orgin main",
        "ask",
    ),
    (
        'psql <<< "drop table shop.orders"',
        "deny",
    ),
    (
        "cat <<EOF | psql\ndrop table shop.orders\nEOF",
        "deny",
    ),
    (
        "cat > /tmp/n.md <<'EOF'\n# it's a title\ndrop table shop.orders\nEOF",
        "allow",
    ),
    (
        "ls # it's\ngit push orgin main\nls # it's",
        "ask",
    ),
]

# compound commands, groups and bodies of here-documents in a pipe, writes in a body.
# The decisions are those of the guard before this change, except
# J-12: a quoted delimiter expands nothing
FORMS_J = [
    (
        '{ echo x; echo "drop table shop.orders;"; } | psql -d shop',
        "deny",
    ),
    (
        '{ echo x; echo "drop table shop.orders;"; } 2>&1 | psql -d shop',
        "deny",
    ),
    (
        '( echo x; echo "drop table shop.orders;" ) | psql -d shop',
        "deny",
    ),
    (
        'if true; then echo x; echo "drop table shop.orders;"; fi | psql -d shop',
        "deny",
    ),
    (
        'for t in a b; do echo x; echo "drop table shop.orders;"; done | psql -d shop',
        "deny",
    ),
    (
        'for t in a b; do echo "drop table shop.orders;"; echo x; done | psql -d shop',
        "deny",
    ),
    (
        'while read t; do echo x; echo "drop table shop.orders;"; done < list.txt | psql -d shop',
        "deny",
    ),
    (
        'if true; then echo x; else echo "drop table shop.orders;"; fi | psql -d shop',
        "deny",
    ),
    (
        'case x in x) echo x; echo "drop table shop.orders;";; esac | psql -d shop',
        "deny",
    ),
    (
        'for i in 1; do echo x; echo "git push orgin main"; done | bash',
        "ask",
    ),
    (
        'git commit -m "$(cat <<EOF\nmsg $(git push orgin main)\nEOF\n)"',
        "ask",
    ),
    (
        "git commit -m \"$(cat <<'EOF'\nmsg $(git push orgin main)\nEOF\n)\"",
        "allow",
    ),
    (
        'git commit -m "$(cat <<EOF\nmsg `cp /tmp/g.py .claude/hooks/guard.py`\nEOF\n)"',
        "deny",
    ),
    (
        "psql -d shop <<'SQL'\n# note; drop table shop.orders;\nSQL",
        "deny",
    ),
    (
        "cat >> /tmp/log <<EOF\nrun at $(date)\nEOF",
        "allow",
    ),
    (
        "python3 - <<'EOF'\nfile = open('.claude/hooks/guard.py', 'w')\nfile.write('x')\nEOF",
        "deny",
    ),
    (
        "python3 - <<'EOF'\nf = open('.claude/hooks/guard.py', 'w')\nf.write('x')\nEOF",
        "deny",
    ),
    (
        "python3 - <<'EOF'\ntest = open('AGENTS.md', 'w')\nEOF",
        "ask",
    ),
    (
        "python3 -c \"file = open('.claude/hooks/guard.py', 'w')\"",
        "deny",
    ),
    (
        "python3 - <<'EOF'\nhead = open('/tmp/x').read()\nEOF",
        "allow",
    ),
]


def numbered(tag: str, rows: list[tuple[str, str]]) -> list[Any]:
    return [
        pytest.param(command, expected, id=f"{tag}-{at}")
        for at, (command, expected) in enumerate(rows, 1)
    ]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        *numbered("A", FORMS_A),
        *numbered("B", FORMS_B),
        *numbered("C", FORMS_C),
        *numbered("D", FORMS_D),
        *numbered("E", FORMS_E),
        *numbered("F", FORMS_F),
        *numbered("G", FORMS_G),
        *numbered("H", FORMS_H),
        *numbered("I", FORMS_I),
        *numbered("J", FORMS_J),
    ],
)
def test_the_forms_of_the_review_keep_the_decision_of_the_old_guard(
    repo: Path, command: str, expected: str
) -> None:
    write_stamp(repo, "full")

    assert decision(bash(command, repo)) == expected


def stage_full_level_code_with_check_and_review(repo: Path) -> None:
    """Code of the `full` level on the tree, a check and a review of it, and no verify: only the
    verify is left for the commit, so the case decides on the chain alone."""
    add_file(repo, "streaming/job.py")
    write_stamp(repo, "check")
    review(repo)


# The gate holds only on a tree with a full verify of code of the `full` level; a commit chained
# after `make verify` runs it first. Words of other commands (a comment, a quoted
# `make verify && git commit`) are no chain.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git status  # what's staged\ngit commit -m \"wip\"\ngit log -1  # that's it", "deny"),
        ("ls # it's\ngit commit -am wip\nls # it's", "deny"),
        ("git commit -m wip", "deny"),
        ('grep -rn \'git commit -m "\' docs; git commit -am wip; echo "done"', "deny"),
        ('echo "make verify && git commit"; git commit -am wip', "deny"),
        ("make verify; git commit -am wip", "deny"),
        ("make verify || git commit -am wip", "deny"),
        ("make verify && git commit -am wip", "allow"),
        ("make verify && git add -A && git commit -am wip", "allow"),
    ],
)
def test_a_commit_is_gated_whatever_surrounds_it(repo: Path, command: str, expected: str) -> None:
    stage_full_level_code_with_check_and_review(repo)

    assert decision(bash(command, repo)) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git commit -m wip; make verify && git commit -m wip", "deny"),
        ("make verify && git commit -m wip; git commit -m wip", "deny"),
        ("make verify && cd /tmp && git commit -m wip", "allow"),
        ("make verify && (git commit -m wip)", "allow"),
        ("(make verify && git commit -m wip)", "allow"),
    ],
)
def test_every_commit_of_a_text_needs_a_verify_of_its_own(
    repo: Path, command: str, expected: str
) -> None:
    stage_full_level_code_with_check_and_review(repo)

    assert decision(bash(command, repo)) == expected


# The body of a here-document belongs to the command that has the `<<`, not to the last command
# of its line: it is data only when that command is the `cat` that writes the file.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("psql -d shop <<'SQL'; cat > /tmp/f\ndrop table shop.orders;\nSQL", "deny"),
        ("psql -d shop <<'SQL' && cat > /tmp/log\ndrop table shop.orders;\nSQL", "deny"),
        ("psql -d shop <<'A' && cat > /tmp/b <<'B'\ndrop table shop.orders;\nA\nnote\nB", "deny"),
        ("bash <<'A'; cat > /tmp/b <<'B'\ngit push orgin main\nA\nnote\nB", "ask"),
        ("bash <<'A' && cat > /tmp/b\ncp /tmp/g.py .claude/hooks/guard.py\nA", "deny"),
        ("cat > /tmp/b <<'B' && bash <<'A'\nnote\nB\ngit push orgin main\nA", "ask"),
        ("cat > /tmp/n.md <<'EOF'\n  EOF\nnote\nEOF\ngit push orgin main", "ask"),
        ("cat <<'SQL' > /tmp/x.sql && psql -f /tmp/x.sql\ndrop table shop.orders;\nSQL", "deny"),
    ],
)
def test_the_body_of_a_here_document_is_data_only_for_the_cat_that_owns_it(
    command: str, expected: str
) -> None:
    assert decision(bash(command)) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # A here-document of a command other than cat, a brace with a redirect: no read is data.
        ("echo ok; psql -d shop <<SQL\nselect 1;\nSQL\necho 'drop table shop.orders;'", "deny"),
        ("{ echo x; echo 'drop table shop.orders;'; } >&2 | psql -d shop", "deny"),
        # The stamp code run by hand is denied next to a command that runs.
        ("{ echo x; echo 'drop table shop.orders;'; } >&2; make lint", "deny"),
        ('echo "scripts/agent_state.py stamp ."; make lint', "deny"),
    ],
)
def test_the_scan_gives_way_and_the_stamp_cli_is_read_in_the_whole_text(
    command: str, expected: str
) -> None:
    assert decision(bash(command)) == expected


# The body belongs to the command that has the `<<`, even when a pipe and more commands follow it
# on the line; and a body that a cat writes to a file, or a `$(cat <<'EOF' ...)` message, is data
# only when the whole text is that one command.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("cat <<EOF | psql\ndrop table shop.orders\nEOF", "deny"),
        ("cat <<EOF | psql && echo done\ndrop table shop.orders\nEOF", "deny"),
        ("cat <<EOF | psql; echo done\ndrop table shop.orders\nEOF", "deny"),
        ("cat <<EOF | psql -d shop && ls\ndrop table shop.orders\nEOF", "deny"),
        ("cat <<'EOF' | bash && echo ok\ngit push orgin main\nEOF", "ask"),
        ("cat <<EOF | psql && make lint\ndrop table shop.orders\nEOF", "deny"),
        ("cat > /tmp/n.md <<'EOF'\ndrop table shop.orders\nEOF", "allow"),
        ("cat > /tmp/n.md <<'EOF' && git add n.md\ndrop table shop.orders\nEOF", "deny"),
        ("cat > /tmp/n.md <<'EOF'\ndrop table shop.orders\nEOF\ngit add n.md", "deny"),
        ("ls; cat > /tmp/n.md <<'EOF'\ndrop table shop.orders\nEOF", "deny"),
        ("git add -A && git commit -m \"$(cat <<'EOF'\ndocs: make silver note\nEOF\n)\"", "ask"),
        ("git commit -m \"$(cat <<'EOF'\ndocs: make silver note\nEOF\n)\"", "allow"),
        ('git add -A && git commit -m "docs: make silver note"', "allow"),
        (
            "git add -A && git commit -m \"$(cat <<'EOF'\ndocs: the dbt drop table step\n\n"
            'git push and make silver need an ok; .verify-stamp\nEOF\n)"',
            "deny",
        ),
        # A command after the delimiter on the first line runs inside `$(...)`: no message.
        ("git commit -m \"$(cat <<'EOF'; git push origin main\nmsg\nEOF\n)\"", "ask"),
        (
            "git commit -m \"$(cat <<'EOF' && cp /tmp/g.py .claude/hooks/guard.py\nmsg\nEOF\n)\"",
            "deny",
        ),
        ("git commit -m \"$(cat <<'EOF' | sh\ngit push origin main\nEOF\n)\"", "ask"),
    ],
)
def test_a_body_or_a_message_is_data_only_in_a_text_of_one_command(
    repo: Path, command: str, expected: str
) -> None:
    write_stamp(repo, "full")

    assert decision(bash(command, repo)) == expected


def test_the_rules_for_writes_read_the_whole_text_when_something_runs() -> None:
    # Only a command of reads is free; next to a command that runs, a read is read too.
    assert decision(bash("echo 'sed -i s/a/b/ .claude/hooks/guard.py'")) == "allow"
    assert decision(bash("make lint; echo 'sed -i s/a/b/ .claude/hooks/guard.py'")) == "deny"
    assert decision(bash("make lint; echo 'cp /tmp/x .env'")) == "deny"
    assert decision(bash("make lint; echo 'cp /tmp/x AGENTS.md'")) == "ask"


def test_a_here_document_that_only_mentions_cat_is_not_the_body_of_a_cat() -> None:
    command = "psql -c 'select cat' <<'SQL' > /tmp/out.txt\ndrop table shop.orders;\nSQL"

    assert decision(bash(command)) == "deny"


def test_the_address_of_an_http_write_may_be_in_a_read_before_it() -> None:
    assert decision(bash("echo localhost:8083/connectors; curl -X PUT $C/x -d @f.json")) == "ask"
    assert decision(bash("grep -n 8083 notes.md; curl -s $C/x")) == "allow"


def test_a_comment_with_an_apostrophe_hides_no_secret_and_no_read_is_lost() -> None:
    assert decision(bash("ls # it's\ncat .env\nls # it's")) == "ask"
    assert decision(bash("ls # it's\ncat .env.example\nls # it's")) == "allow"
    assert decision(bash("cat Makefile # what's .env\nls")) == "allow"


# Words that a stamp name hides in: a read that feeds a command that runs, an unbalanced quote.
@pytest.mark.parametrize(
    "command",
    [
        "echo .verify-stamp | xargs touch",
        "ls .verify-stamp .check-stamp | xargs cp /tmp/fake",
        'touch .verify-stamp "',
        "echo it's; touch .verify-stamp",
    ],
)
def test_a_stamp_named_for_a_command_that_runs_is_denied(command: str) -> None:
    assert decision(bash(command)) == "deny"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # A here-document of a command other than the cat before it is not data.
        ("cat <<'EOF'\ndrop table shop.orders\nEOF", "deny"),
        ("cat x; cat <<'EOF'\ndrop table shop.orders\nEOF", "deny"),
        ("cat > /tmp/n.md <<'EOF'\ndrop table shop.orders\nEOF", "allow"),
        ("ls; cat > /tmp/n.md <<'EOF'\nthe drop table step\nEOF\nls", "deny"),
        # The message of a commit is dropped only when it holds no substitution, or is the
        # `$(cat <<'EOF' ... EOF)` form.
        ('git commit -m "$(git push origin main)"', "ask"),
        ('git commit -m "$(psql -c \\"drop table t\\")"', "deny"),
        ('git commit -m "$(cat <<\'EOF\'\nsay "hi" and drop table t\nEOF\n)"', "allow"),
        (
            "git commit -m \"$(cat <<'EOF'\nthe drop table step\nEOF\n)\" && git push origin main",
            "deny",
        ),
        ('git commit -m "a" -m "drop table t"', "allow"),
        # A delimiter the scan does not read whole is no here-document it knows: bash closes on
        # it, and the lines after it run.
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\ngit push --force", "deny"),
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\nmake silver", "ask"),
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\necho x > .verify-stamp", "deny"),
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\ncp /tmp/g.py .claude/hooks/guard.py", "deny"),
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\ndocker compose down", "ask"),
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\ncat .env", "ask"),
        ('cat > /tmp/n.md <<E"OF"\nx\nEOF\ngit push --force', "deny"),
        ("cat > /tmp/n.md <<'EOF'x\nx\nEOFx\ngit push --force", "deny"),
        ("cat > /tmp/n.md <<END.NOTES\nx\nEND.NOTES\ngit push origin main", "ask"),
        # A line that is only the start of the real delimiter must not close the body.
        ("cat > /tmp/n.md <<END-NOTES\nx\nEND-NOTES\ngit push --force\nEND", "deny"),
        ("cat > /tmp/n.md <<END.NOTES\nx\nEND.NOTES\nmake silver\nEND", "ask"),
        # No delimiter line: no body to cut.
        ("cat > /tmp/n.md <<'EOF'\ndrop table t", "deny"),
    ],
)
def test_data_is_cut_only_where_it_is_data(repo: Path, command: str, expected: str) -> None:
    write_stamp(repo, "full")

    assert decision(bash(command, repo)) == expected


@pytest.mark.parametrize("delimiter", ["END-NOTES", "END.NOTES"])
def test_a_commit_after_an_unread_delimiter_still_meets_the_gate(
    repo: Path, delimiter: str
) -> None:
    # No stamp: the gate is closed, so only a commit the scan did not cut as data is denied.
    command = f"cat > /tmp/n.md <<{delimiter}\nx\n{delimiter}\ngit commit -m x"

    assert decision(bash(command, repo)) == "deny"


LONG_FORMS = {
    "commands": ("echo x; " * 2000 + "make lint", "allow"),
    "here-document": ("cat > /tmp/n.md <<'EOF'\n" + "word " * 3200 + "\nEOF", "allow"),
    "unquoted here-document": ("cat > /tmp/n.md <<EOF\n" + "word " * 3200 + "\nEOF", "allow"),
    "here-document of psql": ("psql <<SQL\n" + "select 1;\n" * 1600 + "SQL", "allow"),
    "many here-documents": ("cat <<EOF\n" * 3000, "allow"),
    "env path": ("cat " + "a/" * 12000 + ".env", "ask"),
    "env path in text": ("echo " + "a/" * 8000 + ".env", "allow"),
    "paths to env": ("cat a/" * 4000 + ".env", "ask"),
    "separators": ("ls" + " ; |" * 3500, "allow"),
    "git options": ("git" + " --x" * 22 + " status", "allow"),
    "git values": ("git" + " -c a" * 40 + " status", "allow"),
    "compound commands": ("for i in 1; do echo x; done\n" * 1000, "allow"),
}


@pytest.mark.parametrize(("command", "expected"), LONG_FORMS.values(), ids=list(LONG_FORMS.keys()))
def test_a_long_command_that_runs_something_is_decided_in_under_a_second(
    command: str, expected: str
) -> None:
    started = time.monotonic()
    result = bash(command)

    assert time.monotonic() - started < 1
    assert decision(result) == expected


# HG-05..HG-11: a read, a word in data and a file that only looks like a secret or a rule were
# denied or asked. Each command here is what the audit of 13.11 ran, and each is allowed.
@pytest.mark.parametrize(
    "command",
    [
        *forms(
            "HG-05",
            "mkdir -p /tmp/s/audit && cat .verify-stamp .check-stamp",
            "cat .verify-stamp 2>/dev/null || echo none",
            "cat .verify-stamp; echo ---; cat .check-stamp",
            "stat .verify-stamp",
            "test -f .review-stamp && echo yes",
            "ls -la .verify-stamp && make report",
        ),
        *forms(
            "HG-06",
            "cat > /tmp/s/notes.md <<'EOF'\nnext: make silver after the owner says ok, "
            "then git commit\nEOF",
            "cat > /tmp/s/notes.md <<'EOF'\nthe dbt run does DROP TABLE in gold\nEOF",
            "cat > /tmp/s/notes.md <<'EOF'\ndocker compose down removes containers\nEOF",
            "echo 'truncate the output'",
            "echo done && echo 'git push is class C'",
            f'{COMPOSE} logs --tail=500 airflow-scheduler | grep -i "drop table"',
            'docker logs lakehouse-airflow-scheduler-1 2>&1 | grep -c "drop table"',
            'cd /tmp/s && python3 probe.py a.py < fp.json | grep -A1 "commit\\|drop table\\|DROP"',
            'uv run pytest tests/unit -q 2>&1 | grep -n "git push"',
            "gh pr view 3 | grep -i 'drop table'",
        ),
        *forms(
            "HG-07",
            "make check > /tmp/s/check.log 2>&1",
            "make -j4 check",
        ),
        *forms(
            "HG-08",
            'uv run python -c "from scripts.agent_state import tree_hash; '
            "from pathlib import Path; print(tree_hash(Path('.')))\"",
            "uv run python - <<'EOF'\nfrom scripts.agent_state import read_stamp\n"
            "print(read_stamp(__import__('pathlib').Path('.'), 'verify'))\nEOF",
        ),
        *forms(
            "HG-09",
            "python3 -c \"import json; print(json.load(open('.claude/settings.local.json')))\"",
            "python3 -c \"print(open('AGENTS.md').read()[:200])\"",
            "python3 -c \"open('AGENTS.md', 'r').read()\"",
            "python3 -c \"open('AGENTS.md', 'rb').read()\"",
            "python3 -c \"open('AGENTS.md', encoding='utf-8').read()\"",
            "python3 -c \"open('.claude/settings.local.json', 'r').read()\"",
            "python3 -c \"open('.claude/settings.local.json', 'rb').read()\"",
            "python3 -c \"open('.claude/settings.local.json', encoding='utf-8').read()\"",
        ),
        *forms(
            "HG-10",
            f'{COMPOSE} exec -T trino trino --execute "show create table lake.silver.orders"',
            f'{COMPOSE} exec -T trino trino --execute "show create view lake.gold.v"',
            "docker exec lakehouse-airflow-scheduler-1 rm /tmp/probe.txt",
        ),
        *forms(
            "HG-11",
            "echo x > docker/airflow/test.env",
            "sed -i s/a/b/ docker/airflow/airflow.env",
            "cp /tmp/x docker/airflow/airflow.env",
        ),
    ],
)
def test_guard_allows_the_false_positives_of_the_audit(command: str) -> None:
    assert decision(bash(command)) == "allow"


# HG-06: the message of a commit and the body of a here-document are data, not commands. The gate
# is open (a full verify on a clean tree), so only the words of the text decide.
@pytest.mark.parametrize(
    "command",
    [
        *forms(
            "HG-06",
            'git commit -m "docs: run make check before the commit"',
            'git commit -m "harness: .verify-stamp is written by make verify"',
            'git commit -m "docs: make silver needs the owner\'s ok"',
            'git commit -m "docs: note that git push needs an ok"',
            'git commit -m "docs: delete from the table the stale row"',
            'git commit -m "docs: truncate long lines in the report"',
            "git commit -m \"$(cat <<'EOF'\ndocs: the dbt drop table step and make check\n\n"
            'more text\nEOF\n)"',
            'git commit -m "docs: docker compose down and make down are class C"',
            "git -C /repo commit -am 'infra: drop table guard words'",
            'make verify && git add -A && git commit -m "docs: x"',
        ),
    ],
)
def test_the_message_of_a_commit_is_data(repo: Path, command: str) -> None:
    write_stamp(repo, "full")

    assert decision(bash(command, repo)) == "allow"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('git commit -m "x" && git push origin main', "ask"),
        ('git commit -m "x" --amend', "ask"),
        ('git commit -m "x" && psql -c "drop table t"', "deny"),
    ],
)
def test_a_command_after_the_message_of_a_commit_is_still_checked(
    repo: Path, command: str, expected: str
) -> None:
    write_stamp(repo, "full")

    assert decision(bash(command, repo)) == expected


# What the audit keeps asking or denying: a command that runs the words, a secret, a stamp.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("find docs -name '*.md' | xargs grep -l \"git push --force\"", "deny"),
        ("awk '/DROP TABLE/ {print FILENAME\": \"$0}' dbt/target/run/*.sql", "deny"),
        ("awk '/DROP TABLE/ {print FILENAME}' dbt/target/run/x.sql", "deny"),
        ("rm -rf /tmp/claude-1000/x/scratchpad/audit/HG-work/old", "ask"),
        ("git restore --staged docs/HANDOFF.md", "ask"),
        ("uv run pytest tests/unit/test_maintenance.py -k expire_snapshots -q", "ask"),
        ("python3 -c 'print(1)'; git check-ignore .env", "ask"),
        ("sed -n 1,5p .verify-stamp", "deny"),
        ("echo x > .verify-stamp", "deny"),
        ("test -f .verify-stamp || touch .verify-stamp", "deny"),
        ('python3 -c "from scripts.agent_state import write_stamp"', "deny"),
        ("echo X=1 >> .env", "deny"),
        ("python3 -c \"open('AGENTS.md', 'w')\"", "ask"),
        ("python3 -c \"open('AGENTS.md', 'r+')\"", "ask"),
        ("python3 -c \"open('AGENTS.md', 'rb+')\"", "ask"),
        ("python3 -c \"open('AGENTS.md', encoding='utf-8', mode='w')\"", "ask"),
        ("python3 -c \"open('.claude/settings.local.json', 'r+').write('{}')\"", "deny"),
        ("python3 -c \"open('.claude/settings.local.json', 'rb+')\"", "deny"),
        ("python3 -c \"open('.claude/hooks/guard.py', mode='a')\"", "deny"),
        ("python3 -c \"open('.claude/hooks/guard.py', encoding='utf-8', mode='w')\"", "deny"),
        (
            "python3 - <<'EOF'\nwith open('.claude/settings.local.json', 'r+') as f:\n"
            "    f.write('x')\nEOF",
            "deny",
        ),
        ("python3 -c \"open('scripts/agent_state.py', 'r+')\"", "ask"),
        ("cp /tmp/x .env.local", "deny"),
        ("echo x >> docker/.env", "deny"),
    ],
)
def test_the_forms_the_audit_keeps_asking_or_denying(command: str, expected: str) -> None:
    assert decision(bash(command)) == expected


# The words of a read are data, unless a command after it in the same pipeline runs them.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('echo "drop table shop.orders" | psql -d shop', "deny"),
        ("echo 'truncate shop.orders' | psql", "deny"),
        ('echo "update shop.orders set x = 1" | psql', "ask"),
        ("echo 'git push origin main' | bash", "ask"),
        ("echo 'docker compose down' | bash", "ask"),
        ('docker logs x 2>&1 | grep -c "drop table"', "allow"),
        ('grep "drop table" notes.md; psql -c "select 1"', "allow"),
        ('echo "drop table t"; echo ok | cat', "allow"),
        ('echo "drop table t" | cat | psql', "deny"),
        ('echo "$(psql -c "drop table t")"', "deny"),
    ],
)
def test_a_read_in_a_pipeline_is_checked_when_a_command_after_it_runs(
    command: str, expected: str
) -> None:
    assert decision(bash(command)) == expected


LONG_COMMANDS = {
    "echo": "echo " + "word " * 2500,
    "grep files": "grep -n x " + " ".join(f"{n}.md" for n in range(2000)),
    "ls chain": " ; ".join(["ls"] * 2000),
    "echo pipe": "echo x | " * 1000 + "cat",
    "git log paths": "git log -- " + " ".join(f"a{n}" for n in range(2500)),
}


@pytest.mark.parametrize("command", LONG_COMMANDS.values(), ids=LONG_COMMANDS.keys())
def test_a_long_command_is_decided_in_under_a_second(command: str) -> None:
    assert 8_000 <= len(command) <= 16_500
    started = time.monotonic()
    result = bash(command)
    elapsed = time.monotonic() - started

    assert decision(result) == "allow"
    assert elapsed < 1


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
    add_file(repo, "streaming/job.py", "x = 2\n")
    assert decision(bash(commit, repo)) == "deny"

    write_stamp(repo, "fast")
    write_stamp(repo, "check")
    review(repo)
    assert decision(bash(commit, repo)) == "deny"

    write_stamp(repo, "full")
    assert decision(bash(commit, repo)) == "allow"

    add_file(repo, "streaming/job.py", "x = 3\n")
    assert decision(bash(commit, repo)) == "deny"


def test_commit_message_words_are_not_subcommands(repo: Path) -> None:
    write_stamp(repo, "full")

    assert decision(bash('git commit -m "docs: rebase and push rules"', repo)) == "allow"
    assert decision(bash("git log --grep commit", repo)) == "allow"
    (repo / "job.py").write_text("x = 2\n")
    assert decision(bash("git commit-tree HEAD^{tree}", repo)) == "deny"


def test_guard_run_as_a_hook_denies_with_exit_code_2_and_the_reason_on_stderr() -> None:
    event = {"tool_name": "Write", "tool_input": {"file_path": str(REPO / ".check-stamp")}}

    result = hook_process("guard.py", event)

    assert result.returncode == 2
    assert "writes a gate stamp by hand" in result.stderr


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("echo x > .verify-stamp", "writes a gate stamp by hand"),
        ("cp /tmp/g .claude/hooks/guard.py", "shell write to the agent hooks or settings"),
    ],
)
def test_guard_run_as_a_hook_denies_a_bash_write_with_exit_code_2(
    command: str, reason: str
) -> None:
    result = hook_process("guard.py", {"tool_name": "Bash", "tool_input": {"command": command}})

    assert result.returncode == 2
    assert reason in result.stderr


def test_guard_run_as_a_hook_asks_with_json_on_stdout() -> None:
    event = {"tool_name": "Bash", "tool_input": {"command": "make nuke"}}

    result = hook_process("guard.py", event)

    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert decision(result) == "ask"


def test_guard_fails_closed() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOKS / "guard.py")],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )

    assert decision(result) == "crash"
    assert "guard.py failed" in result.stdout


def test_docs_changed_after_a_full_verify_can_be_committed(repo: Path) -> None:
    # The stop gate needs no check for Markdown and docs/; a commit of them needs none either.
    write_stamp(repo, "full")
    (repo / "NOTES.md").write_text("x")
    assert decision(bash("git add -A && git commit -m notes", repo)) == "allow"

    (repo / "job.py").write_text("x = 9\n")
    assert decision(bash("git add -A && git commit -m code", repo)) == "deny"


ODD_DOCS = ["docs/my plan.txt", "docs/план.txt", "my notes.md", "заметки.md"]


@pytest.mark.parametrize("path", ODD_DOCS)
def test_a_doc_with_a_space_or_a_non_ascii_name_can_be_committed_after_a_full_verify(
    repo: Path, path: str
) -> None:
    # B14: git quoted such a path in `status --porcelain` and the quoted name counted as code.
    write_stamp(repo, "full")
    (repo / path).parent.mkdir(exist_ok=True)
    (repo / path).write_text("x")

    assert decision(bash("git add -A && git commit -m notes", repo)) == "allow"


@pytest.mark.parametrize("path", ODD_DOCS)
def test_stop_gate_lets_a_doc_with_an_odd_name_end_the_turn(repo: Path, path: str) -> None:
    (repo / path).parent.mkdir(exist_ok=True)
    (repo / path).write_text("x")

    assert hook("stop_gate.py", {}, repo).stdout == ""


def test_stop_gate_names_code_with_an_odd_name_by_its_real_name(repo: Path) -> None:
    (repo / "моя задача.py").write_text("x = 1\n")

    reason = json.loads(hook("stop_gate.py", {}, repo).stdout)["reason"]

    assert "моя задача.py" in reason


def test_docs_after_a_fast_verify_need_nothing_to_commit(repo: Path) -> None:
    # Markdown alone needs no stamp, so a fast verify neither opens nor closes the commit.
    write_stamp(repo, "fast")
    (repo / "NOTES.md").write_text("x")

    assert decision(bash("git commit -m notes", repo)) == "allow"


def test_commit_chained_after_a_full_verify_is_allowed(repo: Path) -> None:
    (repo / "streaming").mkdir()
    (repo / "streaming" / "job.py").write_text("x = 1\n")
    write_stamp(repo, "check")
    review(repo)
    assert decision(bash("make verify && git add -A && git commit -m x", repo)) == "allow"
    assert decision(bash("make verify-fast && git commit -m x", repo)) == "deny"
    assert decision(bash("make verify; git commit -m x", repo)) == "deny"


def test_a_commit_on_a_clean_tree_needs_nothing(repo: Path) -> None:
    assert decision(bash("git commit -m x", repo)) == "allow"


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


@pytest.mark.parametrize("mode", ["fast", "full"])
def test_stop_gate_lets_markdown_edited_after_a_verify_end_the_turn(repo: Path, mode: str) -> None:
    # B12 (RT-S3, AI-05): code is verified, then only the notes change. The turn must end without
    # another verify, as it does for the commit gate.
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, mode)
    (repo / "NOTES.md").write_text("report\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.txt").write_text("plan\n")

    assert hook("stop_gate.py", {}, repo).stdout == ""


@pytest.mark.parametrize(
    ("edit", "named"),
    [
        (lambda root: (root / "job.py").write_text("x = 3\n"), "job.py"),
        (lambda root: (root / "extra.py").write_text("y = 1\n"), "extra.py"),
        (lambda root: (root / "job.py").unlink(), "job.py"),
    ],
    ids=["code edited", "new code file", "code removed"],
)
def test_stop_gate_blocks_code_changed_after_a_verify(
    repo: Path, edit: Callable[[Path], object], named: str
) -> None:
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "fast")
    (repo / "NOTES.md").write_text("report\n")
    edit(repo)

    result = hook("stop_gate.py", {}, repo)

    assert json.loads(result.stdout)["decision"] == "block"
    assert named in json.loads(result.stdout)["reason"]


MOVED_OUT = pytest.mark.parametrize(
    "target", ["docs/job.txt", "job.md"], ids=["code moved to docs", "code renamed to md"]
)


def move_code_out(repo: Path, target: str, source: str = "job.py") -> None:
    """`source` leaves the code paths with its content: git shows it as a rename."""
    (repo / target).parent.mkdir(exist_ok=True)
    (repo / source).rename(repo / target)


@MOVED_OUT
def test_stop_gate_blocks_code_moved_out_of_the_code_paths_after_a_verify(
    repo: Path, target: str
) -> None:
    # B12 review: git lists a rename by its new name only, a Markdown or docs/ path.
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "fast")
    move_code_out(repo, target)

    result = hook("stop_gate.py", {}, repo)

    assert json.loads(result.stdout)["decision"] == "block"
    assert "job.py" in json.loads(result.stdout)["reason"]


@MOVED_OUT
def test_stop_gate_blocks_a_staged_move_of_code_out_of_the_code_paths(
    repo: Path, target: str
) -> None:
    (repo / target).parent.mkdir(exist_ok=True)
    git(repo, "mv", "job.py", target)

    result = hook("stop_gate.py", {}, repo)

    assert json.loads(result.stdout)["decision"] == "block"
    assert "job.py" in json.loads(result.stdout)["reason"]


@MOVED_OUT
def test_commit_of_a_staged_move_of_code_out_of_the_code_paths_needs_check_and_review(
    repo: Path, target: str
) -> None:
    (repo / target).parent.mkdir(exist_ok=True)
    git(repo, "mv", "job.py", target)
    write_stamp(repo, "full")

    result = bash("git commit -m move", repo)

    assert decision(result) == "deny"
    assert "git commit without make check and a reviewer verdict" in result.stderr


@MOVED_OUT
def test_commit_is_refused_when_code_moved_out_of_the_code_paths_after_the_stamps(
    repo: Path, target: str
) -> None:
    add_file(repo, "streaming/job.py", "x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "streaming")
    add_file(repo, "streaming/job.py", "x = 2\n")
    gate_stamps(repo)
    move_code_out(repo, target, "streaming/job.py")

    result = bash(COMMIT, repo)

    assert decision(result) == "deny"
    assert "a full make verify, make check and a reviewer verdict" in result.stderr


def test_stop_gate_names_only_the_code_changed_after_the_verify(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "fast")
    (repo / "extra.py").write_text("y = 1\n")

    reason = json.loads(hook("stop_gate.py", {}, repo).stdout)["reason"]

    assert "extra.py" in reason and "job.py" not in reason


def test_stop_gate_blocks_a_stamp_of_a_tree_that_is_gone(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    (repo / ".verify-stamp").write_text(f"fast 2026-10-30T10:00:00Z {'0' * 40}\n")

    result = hook("stop_gate.py", {}, repo)

    assert json.loads(result.stdout)["decision"] == "block"


def test_stop_gate_blocks_an_edit_of_a_dbt_docs_block(repo: Path) -> None:
    (repo / "dbt" / "models").mkdir(parents=True)
    (repo / "dbt" / "models" / "docs.md").write_text("{% docs a %}\nA\n{% enddocs %}\n")
    write_stamp(repo, "full")
    (repo / "dbt" / "models" / "docs.md").write_text("{% docs a %}\nB\n{% enddocs %}\n")

    reason = json.loads(hook("stop_gate.py", {}, repo).stdout)["reason"]

    assert "dbt/models/docs.md" in reason


def test_commit_after_full_then_fast_verify_is_allowed(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo)
    write_stamp(repo, "fast")

    assert decision(bash(COMMIT, repo)) == "allow"


def test_session_context_reports_state_goal_and_stamp(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin", monkeypatch, running="", stopped="", rows=""
    )
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


def test_session_context_survives_missing_docs(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin", monkeypatch, running="", stopped="", rows=""
    )
    result = hook("session_context.py", {}, repo)
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    assert "docs/HANDOFF.md is missing" in context


def fake_docker(
    bin_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    running: str,
    stopped: str,
    rows: str,
    stack: str | None = None,
    others: str = "",
) -> None:
    """A `docker` first on PATH: `ps` lists the running containers, `ps -a` with a status filter
    the ids of the stopped ones, with the label filter alone the ids of the stack (`stack`, the
    stopped ones by default) and with no filter the ids of every container (`others`), and
    `inspect` one row per id (name, restart policy, state, exit code). Every call is appended to
    calls.txt next to it."""
    bin_dir.mkdir()
    files = (
        ("ps.txt", running),
        ("ps_all.txt", stopped),
        ("ps_stack.txt", stopped if stack is None else stack),
        ("ps_any.txt", others),
        ("inspect.txt", rows),
    )
    for name, text in files:
        (bin_dir / name).write_text(text)
    script = bin_dir / "docker"
    script.write_text(
        '#!/bin/sh\nd=$(dirname "$0")\necho "$*" >> "$d/calls.txt"\ncase "$1" in\n'
        '  ps) case " $* " in\n'
        '    *" -a "*status=*) cat "$d/ps_all.txt";;\n'
        '    *" -a "*label=*) cat "$d/ps_stack.txt";;\n'
        '    *" -a "*) cat "$d/ps_any.txt";;\n'
        '    *) cat "$d/ps.txt";;\n  esac;;\n'
        '  inspect) cat "$d/inspect.txt";;\n  *) exit 1;;\nesac\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def session_context(repo: Path) -> str:
    result = hook("session_context.py", {"source": "startup"}, repo)
    assert result.returncode == 0
    return str(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])


def test_session_context_names_a_stopped_container_that_should_run(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 27.10 and 30.10: prometheus stayed in Exited (255) after a Docker restart and nobody saw it.
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin",
        monkeypatch,
        running="lakehouse-kafka-1 Up 2 hours (healthy)\n",
        stopped="aaa\nbbb\nccc\nddd\n",
        rows=(
            "/lakehouse-prometheus-1 unless-stopped exited 255\n"
            "/lakehouse-minio-init-1 no exited 0\n"
            "/lakehouse-grafana-1 always exited 137\n"
            "/lakehouse-spark-silver-1 on-failure exited 1\n"
        ),
    )

    context = session_context(repo)

    assert "1 running, 1 healthy" in context and "lakehouse-kafka-1" not in context
    stopped = [line for line in context.splitlines() if "docker start" in line]
    assert len(stopped) == 2
    assert stopped[0].startswith("lakehouse-prometheus-1: exited (255)")
    assert "unless-stopped did not bring it back" in stopped[0]
    assert "docker start lakehouse-prometheus-1 only with the owner's ok" in stopped[0]
    assert stopped[1].startswith("lakehouse-grafana-1: exited (137)") and "always" in stopped[1]
    assert "minio-init" not in context and "spark-silver" not in context


def test_session_context_has_no_stopped_line_when_everything_runs(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin",
        monkeypatch,
        running="lakehouse-kafka-1 Up 2 hours (healthy)\n",
        stopped="",
        rows="",
    )

    context = session_context(repo)

    assert "1 running, 1 healthy" in context and "lakehouse-kafka-1" not in context
    assert "docker start" not in context and "Not running" not in context


@pytest.mark.parametrize("project", [None, "otherstack", ""])
def test_session_context_finds_the_stack_by_its_compose_directory_not_a_project_name(
    repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    project: str | None,
) -> None:
    # B11: the project name may come from .env, which the hook does not read and the hook's own
    # environment does not hold. The working_dir label of the containers does not depend on it.
    if project is None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    else:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", project)
    bin_dir = tmp_path_factory.mktemp("stack") / "bin"
    fake_docker(
        bin_dir,
        monkeypatch,
        running="",
        stopped="aaa\n",
        rows="/renamed-prometheus-1 unless-stopped exited 255\n",
    )

    context = session_context(repo)

    listings = [
        call
        for call in (bin_dir / "calls.txt").read_text().splitlines()
        if call.startswith("ps -a") and "--filter" in call
    ]
    label = f"label=com.docker.compose.project.working_dir={repo}/docker"
    assert len(listings) == 2
    for listing in listings:
        assert listing.split().count(label) == 1
        assert "label=com.docker.compose.project=" not in listing
    assert "docker start renamed-prometheus-1 only with the owner's ok" in context


def test_session_context_says_when_the_stack_directory_matches_no_container(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B11 review: a stack started from another directory, or a path that docker wrote another way,
    # must not read as a stack with nothing stopped.
    fake_docker(
        tmp_path_factory.mktemp("elsewhere") / "bin",
        monkeypatch,
        running="otherstack-kafka-1 Up 2 hours (healthy)\n",
        stopped="",
        rows="",
        stack="",
        others="aaa\nbbb\n",
    )

    context = session_context(repo)

    assert f"no containers of the stack at {repo}/docker" in context
    assert "1 running, 1 healthy" in context and "otherstack-kafka-1" not in context
    assert "docker start" not in context


@pytest.mark.parametrize(
    ("stack", "others"),
    [("aaa\n", "aaa\nbbb\n"), ("", "")],
    ids=["the stack has containers", "docker has no containers at all"],
)
def test_session_context_has_no_missing_stack_line_otherwise(
    repo: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    stack: str,
    others: str,
) -> None:
    fake_docker(
        tmp_path_factory.mktemp("stack") / "bin",
        monkeypatch,
        running="lakehouse-kafka-1 Up 2 hours (healthy)\n",
        stopped="",
        rows="",
        stack=stack,
        others=others,
    )

    assert "no containers of the stack" not in session_context(repo)


def test_session_context_inspects_nothing_when_the_project_has_no_containers(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `docker inspect` with no id is an error, and its output must never be read as a container.
    bin_dir = tmp_path_factory.mktemp("none") / "bin"
    fake_docker(
        bin_dir,
        monkeypatch,
        running="",
        stopped="",
        rows="/lakehouse-ghost-1 always exited 255\n",
    )

    context = session_context(repo)

    calls = (bin_dir / "calls.txt").read_text().splitlines()
    assert not [call for call in calls if call.startswith("inspect")]
    assert "0 running, 0 healthy" in context
    assert "ghost" not in context and "Not running" not in context and "docker start" not in context


def test_session_context_survives_a_docker_that_fails_or_is_missing(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path_factory.mktemp("broken") / "bin"
    fake_docker(broken, monkeypatch, running="", stopped="", rows="")
    (broken / "docker").write_text("#!/bin/sh\nexit 1\n")
    assert "docker start" not in session_context(repo)

    # The listing works and the inspect after it fails.
    half = tmp_path_factory.mktemp("half") / "bin"
    fake_docker(half, monkeypatch, running="", stopped="", rows="")
    (half / "docker").write_text('#!/bin/sh\ncase "$1" in ps) echo aaa;; *) exit 1;; esac\n')
    context = session_context(repo)
    assert "Containers:\n0 running, 0 healthy\naaa" in context and "docker start" not in context

    # Nothing but git on PATH: no docker at all.
    only_git = tmp_path_factory.mktemp("only-git")
    (only_git / "git").symlink_to(shutil.which("git") or "git")
    monkeypatch.setenv("PATH", str(only_git))
    context = session_context(repo)

    assert "Containers:" in context and "docker start" not in context


def test_commit_of_code_lists_every_step_of_the_gate_it_lacks(repo: Path) -> None:
    add_file(repo, "streaming/job.py", "x = 2\n")

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
    add_file(repo, "streaming/job.py", "x = 2\n")
    gate_stamps(repo)
    add_file(repo, "streaming/job.py", "x = 3\n")

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


def test_only_docs_changed_needs_nothing(repo: Path) -> None:
    # The commit of Markdown and docs/ asks for no stamp at all.
    (repo / "NOTES.md").write_text("x")
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.txt").write_text("x")

    assert not list(repo.glob(".*-stamp"))
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
    assert decision(bash("make verify -n && git commit -m x", repo)) == "deny"


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


def test_settings_deny_reading_the_secret_files_but_not_the_example() -> None:
    deny = json.loads((REPO / ".claude" / "settings.json").read_text())["permissions"]["deny"]

    assert {"Read(./.env)", "Read(**/*.pem)", "Read(**/*.key)"} <= set(deny)
    assert {"Edit(.env)", "Edit(**/*.pem)", "Edit(**/*.key)"} <= set(deny)
    # A rule such as Read(./.env*) would also close .env.example, which holds no secret.
    assert [rule for rule in deny if rule.startswith("Read(") and ".env" in rule] == [
        "Read(./.env)"
    ]


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
        "claude-md-management@claude-plugins-official",
    ):
        assert settings["enabledPlugins"][plugin] is False
    assert (HOOKS / "review_stamp.py").exists()


def test_settings_give_the_guard_a_timeout_and_a_second_layer() -> None:
    settings = json.loads((REPO / ".claude" / "settings.json").read_text())
    guards = [
        h
        for group in settings["hooks"]["PreToolUse"]
        for h in group["hooks"]
        if "guard.py" in h["command"]
    ]
    assert guards
    for handler in guards:
        assert handler["timeout"] == 30
        assert handler["onFailure"] == "block"

    deny = settings["permissions"]["deny"]
    ask = settings["permissions"]["ask"]
    assert set(deny) == {
        "Edit(/.claude/hooks/**)",
        "Edit(/.claude/settings.json)",
        "Edit(/.claude/settings.local.json)",
        "Edit(/.verify-stamp)",
        "Edit(/.check-stamp)",
        "Edit(/.review-stamp)",
        "Edit(.env)",
        "Edit(**/*.pem)",
        "Edit(**/*.key)",
        "Read(./.env)",
        "Read(**/*.pem)",
        "Read(**/*.key)",
    }
    assert set(ask) == {
        "Edit(/AGENTS.md)",
        "Edit(/CLAUDE.md)",
        "Edit(/docs/agent-rules.md)",
        "Edit(/docs/planning/13-harness.md)",
        "Edit(/scripts/agent_state.py)",
        "Edit(/.claude/agents/**)",
        "Edit(/.claude/skills/**)",
        "Bash(git push *)",
        "Bash(git rebase *)",
        "Bash(git reset --hard*)",
        "Bash(make silver*)",
        "Bash(make nuke*)",
        "Bash(make bootstrap*)",
        # The targets that spend the replay budget; `make replay-status` only reads.
        "Bash(make replay-burst*)",
        "Bash(make replay-start*)",
        "Bash(make replay-live*)",
        "Bash(make replay-reset*)",
        "Bash(make replay-load*)",
        "Bash(make chaos-*)",
        "Bash(make iceberg-demo*)",
        "Bash(make cdc-snapshot*)",
        "Bash(make migrate*)",
        "Bash(make watermark-*)",
        "Bash(make start*)",
        "Bash(make up*)",
        "Bash(make down*)",
        # The project runs compose with options before the subcommand.
        "Bash(docker compose down*)",
        "Bash(docker compose * down*)",
        "Bash(gh pr create*)",
        "Bash(gh workflow run*)",
        "Bash(docker push*)",
    }
    assert len(ask) == len(set(ask)) and len(deny) == len(set(deny))
    # The guard sees every tool that runs a command or writes a file.
    assert [
        g["matcher"]
        for g in settings["hooks"]["PreToolUse"]
        if any("guard.py" in h["command"] for h in g["hooks"])
    ] == ["Bash|Write|Edit|NotebookEdit"]
    # "/x" is anchored at the directory the session started in, the repository root for project
    # settings; "./x" is relative to the current directory.
    new_rules = [r for r in deny + ask if r not in {"Read(./.env)"}]
    assert not [r for r in new_rules if r.partition("(")[2].startswith("./")]


def test_a_failure_in_one_text_of_the_command_does_not_lower_a_deny_in_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def check_bash(text: str) -> None:
        if text == "echo ab":
            raise RuntimeError("a regex gave up")
        raise GUARD.VerdictError("deny", "the raw text is denied")

    monkeypatch.setattr(GUARD, "check_bash", check_bash)

    with pytest.raises(GUARD.VerdictError) as raised:
        GUARD.check({"tool_name": "Bash", "tool_input": {"command": "echo a\\\nb"}})

    assert raised.value.kind == "deny"


def test_a_failure_in_every_text_of_the_command_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    def check_bash(text: str) -> None:
        raise RuntimeError("a regex gave up")

    monkeypatch.setattr(GUARD, "check_bash", check_bash)

    with pytest.raises(GUARD.VerdictError) as raised:
        GUARD.check({"tool_name": "Bash", "tool_input": {"command": "echo a\\\nb"}})

    assert raised.value.kind == "ask"


def add_file(root: Path, rel: str, text: str = "y = 1\n") -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)


def test_markdown_only_commit_needs_no_stamp(repo: Path) -> None:
    add_file(repo, "NOTES.md", "x")
    add_file(repo, "docs/plan.txt", "x")

    assert decision(bash(COMMIT, repo)) == "allow"


def test_ci_and_tests_commit_needs_check_and_review_only(repo: Path) -> None:
    add_file(repo, "tests/test_job.py", "def test_x() -> None: ...\n")
    add_file(repo, ".github/ci.yml", "x: 1\n")

    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without make check and a reviewer verdict on" in result.stderr
    assert "make verify" not in result.stderr

    write_stamp(repo, "check")
    review(repo)
    assert decision(bash(COMMIT, repo)) == "allow"


def test_stack_code_commit_needs_a_verify(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")

    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "a make verify-fast or make verify, make check and a reviewer verdict" in result.stderr

    write_stamp(repo, "check")
    review(repo)
    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without a make verify-fast or make verify on" in result.stderr

    write_stamp(repo, "fast")
    assert decision(bash(COMMIT, repo)) == "allow"


def test_streaming_commit_needs_a_full_verify(repo: Path) -> None:
    add_file(repo, "streaming/job.py")
    write_stamp(repo, "check")
    review(repo)
    assert decision(bash("make verify && git add -A && git commit -m x", repo)) == "allow"

    write_stamp(repo, "fast")
    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without a full make verify on" in result.stderr

    write_stamp(repo, "full")
    assert decision(bash(COMMIT, repo)) == "allow"


def test_a_tests_edit_after_a_verify_keeps_it_covering(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo)
    add_file(repo, "tests/test_job.py", "def test_x() -> None: ...\n")

    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without make check and a reviewer verdict on" in result.stderr
    assert "make verify" not in result.stderr

    write_stamp(repo, "check")
    review(repo)
    verify = read_stamp(repo, "verify")
    assert verify is not None and not verify.fresh
    assert decision(bash(COMMIT, repo)) == "allow"


@pytest.fixture
def quiet_docker(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin", monkeypatch, running="", stopped="", rows=""
    )


def start_session(root: Path, session_id: str, source: str = "startup") -> None:
    result = hook("session_context.py", {"source": source, "session_id": session_id}, root)
    assert result.returncode == 0


def blocked(result: subprocess.CompletedProcess[str]) -> str:
    """The reason of a block, an empty string when the turn may end."""
    return str(json.loads(result.stdout)["reason"]) if result.stdout.strip() else ""


def test_stop_gate_ignores_code_outside_the_stack(repo: Path) -> None:
    add_file(repo, "tests/test_job.py", "def test_x() -> None: ...\n")
    add_file(repo, ".github/ci.yml", "x: 1\n")
    add_file(repo, ".claude/hooks/new.py")
    add_file(repo, ".sqlfluff", "[sqlfluff]\n")

    assert hook("stop_gate.py", {}, repo).stdout == ""

    (repo / "job.py").write_text("x = 2\n")
    reason = blocked(hook("stop_gate.py", {}, repo))
    assert "job.py" in reason and "tests/test_job.py" not in reason


def test_stop_gate_ignores_code_changed_before_the_session(repo: Path, quiet_docker: None) -> None:
    (repo / "job.py").write_text("x = 2\n")
    start_session(repo, "s-before")

    assert hook("stop_gate.py", {"session_id": "s-before"}, repo).stdout == ""
    assert "job.py" in blocked(hook("stop_gate.py", {"session_id": "other"}, repo))


def test_stop_gate_blocks_code_changed_in_the_session(repo: Path, quiet_docker: None) -> None:
    (repo / "job.py").write_text("x = 2\n")
    start_session(repo, "s-in")
    add_file(repo, "extra.py")
    add_file(repo, "tests/test_job.py", "def test_x() -> None: ...\n")

    reason = blocked(hook("stop_gate.py", {"session_id": "s-in"}, repo))
    assert "extra.py" in reason and "job.py" not in reason and "tests/" not in reason

    write_stamp(repo, "fast")
    assert hook("stop_gate.py", {"session_id": "s-in"}, repo).stdout == ""


def test_a_resumed_session_keeps_its_base(repo: Path, quiet_docker: None) -> None:
    start_session(repo, "s-resume")
    base = (repo / ".git" / "claude-base-s-resume").read_text()
    (repo / "job.py").write_text("x = 2\n")

    for source in ("resume", "compact", "clear"):
        start_session(repo, "s-resume", source)

    assert (repo / ".git" / "claude-base-s-resume").read_text() == base
    assert "job.py" in blocked(hook("stop_gate.py", {"session_id": "s-resume"}, repo))


def test_stop_gate_without_a_base_behaves_as_before(repo: Path) -> None:
    (repo / "job.py").write_text("x = 2\n")

    assert "job.py" in blocked(hook("stop_gate.py", {}, repo))
    assert "job.py" in blocked(hook("stop_gate.py", {"session_id": "never-started"}, repo))


def test_stop_gate_with_a_base_tree_that_is_gone_behaves_as_without_a_base(
    repo: Path, quiet_docker: None
) -> None:
    start_session(repo, "s-gone")
    (repo / ".git" / "claude-base-s-gone").write_text(f"{'0' * 40}\n")
    (repo / "job.py").write_text("x = 2\n")

    assert "job.py" in blocked(hook("stop_gate.py", {"session_id": "s-gone"}, repo))


@pytest.mark.parametrize("session_id", ["../outside", "a/b", "", "x" * 129])
def test_a_session_id_with_a_slash_writes_no_base(
    repo: Path, quiet_docker: None, session_id: str
) -> None:
    before = sorted(p.name for p in repo.parent.iterdir())
    git_dir_before = sorted(p.name for p in (repo / ".git").iterdir())
    (repo / "job.py").write_text("x = 2\n")

    start_session(repo, session_id)

    assert sorted(p.name for p in repo.parent.iterdir()) == before
    assert sorted(p.name for p in (repo / ".git").iterdir()) == git_dir_before
    assert "job.py" in blocked(hook("stop_gate.py", {"session_id": session_id}, repo))


def test_session_context_survives_an_empty_or_odd_input(repo: Path, quiet_docker: None) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    for stdin in ("", "not json", "[]", '{"session_id": 5}'):
        result = subprocess.run(
            [sys.executable, str(HOOKS / "session_context.py")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0
        assert "Session start facts" in result.stdout


def test_session_context_lists_only_unhealthy_containers(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin",
        monkeypatch,
        running=(
            "lakehouse-kafka-1 Up 2 hours (healthy)\n"
            "lakehouse-trino-1 Up 3 minutes (unhealthy)\n"
            "lakehouse-airflow-1 Up 5 seconds (health: starting)\n"
            "lakehouse-grafana-1 Up 2 hours\n"
        ),
        stopped="",
        rows="",
    )

    context = session_context(repo)

    assert "4 running, 1 healthy" in context
    assert "lakehouse-trino-1 Up 3 minutes (unhealthy)" in context
    assert "lakehouse-airflow-1 Up 5 seconds (health: starting)" in context
    assert "lakehouse-kafka-1" not in context and "lakehouse-grafana-1" not in context


def test_session_context_shows_the_three_stamps_and_short_commits(
    repo: Path, quiet_docker: None
) -> None:
    git(repo, "commit", "-q", "--allow-empty", "-m", "s" * 100)
    git(repo, "commit", "-q", "--allow-empty", "-m", "short")
    write_stamp(repo, "check")

    context = session_context(repo)

    assert "Verify stamp: none" in context and "Review stamp: none" in context
    assert "Check stamp: check at " in context
    commits = context.split("Last commits:\n")[1].split("\n\n")[0].splitlines()
    assert "s" * 100 not in context
    assert len(commits[1].split(" ", 1)[1]) == 72 and commits[1].endswith("..")
    assert commits[0].endswith(" short")
    assert all(line == line.rstrip() for line in context.splitlines())


def test_session_context_shows_a_restarting_and_a_paused_container(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_docker(
        tmp_path_factory.mktemp("bin") / "bin",
        monkeypatch,
        running=(
            "lakehouse-kafka-1 Up 2 hours (healthy)\n"
            "lakehouse-trino-1 Restarting (1) 5 seconds ago\n"
            "lakehouse-airflow-1 Up 3 minutes (Paused)\n"
        ),
        stopped="",
        rows="",
    )

    context = session_context(repo)

    assert "2 running, 1 healthy" in context
    assert "lakehouse-trino-1 Restarting (1) 5 seconds ago" in context
    assert "lakehouse-airflow-1 Up 3 minutes (Paused)" in context
    assert "lakehouse-kafka-1" not in context


@pytest.mark.parametrize(
    "command",
    [
        "git apply /tmp/p.patch && git add -A && git commit -m x",
        "git stash pop && git add -A && git commit -m x",
        "git cherry-pick -n abc && git commit -m x",
        "echo 'x = 9' > streaming/job.py && git add -A && git commit -m x",
        "git rm -q --cached job.py && git commit -m x",
        "make verify && echo x > a.py && git add -A && git commit -m x",
    ],
)
def test_a_commit_after_a_command_that_changes_the_tree_is_refused(
    repo: Path, command: str
) -> None:
    # The gate reads the tree before the command runs, so a write in the same text is not seen.
    result = bash(command, repo)

    assert decision(result) == "deny"
    assert "run it first, then commit" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git add -A && git commit -m x",
        "git status && git commit -m x",
        "cd . && git add -A && git commit -m x",
        "make verify && git add -A && git commit -m x",
        "make check && git commit -m x",
    ],
)
def test_a_commit_after_only_a_read_an_add_a_cd_or_a_verify_is_decided_by_the_stamps(
    repo: Path, command: str
) -> None:
    assert decision(bash(command, repo)) == "allow"


def test_a_fast_verify_before_the_commit_stands_for_a_verify_only_below_the_full_level(
    repo: Path,
) -> None:
    (repo / "job.py").write_text("x = 2\n")
    write_stamp(repo, "check")
    review(repo)
    assert decision(bash("make verify-fast && git commit -m x", repo)) == "allow"
    assert decision(bash("make verify -n && git commit -m x", repo)) == "deny"

    add_file(repo, "streaming/job.py")
    write_stamp(repo, "check")
    review(repo)
    assert decision(bash("make verify-fast && git commit -m x", repo)) == "deny"
    assert decision(bash("make verify && git commit -m x", repo)) == "allow"


def test_markdown_under_the_agent_directory_needs_check_and_review(repo: Path) -> None:
    add_file(repo, ".claude/agents/r.md", "x\n")

    result = bash(COMMIT, repo)
    assert decision(result) == "deny"
    assert "git commit without make check and a reviewer verdict on" in result.stderr
    assert "make verify" not in result.stderr
    assert hook("stop_gate.py", {}, repo).stdout == ""

    write_stamp(repo, "check")
    review(repo)
    assert decision(bash(COMMIT, repo)) == "allow"


def test_stop_gate_does_not_blame_code_that_came_in_a_commit_after_the_base(
    repo: Path, quiet_docker: None
) -> None:
    start_session(repo, "s-pull")
    add_file(repo, "other.py")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "owner or pull")

    assert hook("stop_gate.py", {"session_id": "s-pull"}, repo).stdout == ""


def test_stop_gate_does_not_blame_the_discard_of_an_edit_made_before_the_session(
    repo: Path, quiet_docker: None
) -> None:
    (repo / "job.py").write_text("x = 2\n")
    start_session(repo, "s-discard")
    git(repo, "checkout", "--", "job.py")

    assert hook("stop_gate.py", {"session_id": "s-discard"}, repo).stdout == ""
