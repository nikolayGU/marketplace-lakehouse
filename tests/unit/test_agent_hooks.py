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
        # The `;` inside the quotes of the code does not split the command.
        "python3 -c \"import os; print(open('.env').read())\"",
        "python3 -c 'import os; print(open(\".env\").read())' && echo done",
        "echo start; python3 -c \"import os; print(open('.env').read())\"; echo done",
        "python3 -c 'print(1)'; python3 -c \"import os; print(open('.env').read())\"",
        "python3 -c 'print(1)'\npython3 -c \"import os; print(open('.env').read())\"",
        "python3 -c 'print(1)' | python3 -c \"import os; print(open('.env').read())\"",
        "python3 -c 'a=1' && node -e \"require('fs').readFileSync('.env')\" || true",
        "perl -e 'open(F, \".env\"); print <F>' && echo done",
        "env X=1 python3 -c \"import os; print(open('.env').read())\"",
        # A `$(...)`, a backtick pair or `&&` inside the code, or the code inside a substitution.
        "python3 -c \"x = '$(date)'; print(open('.env').read())\"",
        "python3 -c \"print(1 and 2 or 3 | 4); print(open('.env').read())\"",
        "echo $(python3 -c \"print(open('.env').read())\")",
        "echo `python3 -c \"print(open('.env').read())\"`",
        "x=$(python3 -c \"import os; print(open('.env').read())\"); echo done",
        # A here-document or a here-string: the code is not among the words of the interpreter.
        "python3 - <<'EOF'\nimport os; print(open('.env').read())\nEOF",
        "python3 <<EOF\nprint(open('.env').read())\nEOF\necho done",
        "git status; python3 - <<'EOF'\nprint(open('.env').read())\nEOF",
        "python3 - <<-EOF\n\tprint(open('.env').read())\n\tEOF",
        "python3 - <<< \"print(open('.env').read())\"",
        # Code piped to the interpreter, or a file name handed to it by xargs, comes from an
        # earlier command of the line.
        "echo \"print(open('.env').read())\" | python3 -",
        "printf 'print(open(\".env\").read())' | python3 - && echo done",
        "echo .env | xargs python3 -c 'import sys; print(open(sys.argv[1]).read())'",
        # Quotes that do not balance: the segments are unknown, the whole line counts.
        "echo done; python3 -c \"print(open('.env').read())",
        # The name is in a variable, an `export` or a `for`, or the code runs in another shell.
        "f=.env; python3 -c \"print(open('$f').read())\"",
        "F=.env && python3 -c \"print(open('$F').read())\"",
        "export F=.env; python3 -c \"import os; print(open(os.environ['F']).read())\"",
        "export F=.env\npython3 -c \"import os; print(open(os.environ['F']).read())\"",
        "for f in .env; do python3 -c \"print(open('$f').read())\"; done",
        'bash -c "python3 -c \\"print(open(\'.env\').read())\\""',
        'sh -c \'f=.env; python3 -c "print(open(\\"$f\\").read())"\'',
        "eval 'f=.env'; python3 -c \"print(open('$f').read())\"",
        'eval "python3 -c \\"print(open(\'.env\').read())\\""',
        "env F=.env python3 -c \"import os; print(open(os.environ['F']).read())\"",
        "F=.env python3 -c \"import os; print(open(os.environ['F']).read())\"",
        "f=.env; python3 <<< \"print(open('$f').read())\"",
        ("cd /work/lakehouse; F=.env; uv run python -c \"import os; print(open('$F').read())\""),
        "ENV_FILE=$(pwd)/.env && python3 -c \"print(open('$ENV_FILE').read())\"",
        "python3 -c \"print(open('$HOME/marketplace-lakehouse/'+'.env').read())\"",
        # A `$(...)` or a backtick pair before the path, a process substitution.
        'python3 -c "import sys; print(open(sys.argv[1]).read())" $(pwd)/.env',
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' `pwd`/.env",
        (
            "python3 -c 'import sys; print(open(sys.argv[1]).read())' "
            "$(git rev-parse --show-toplevel)/.env"
        ),
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' \"$(pwd)/.env\"",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' $(echo .env)",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' `echo .env`",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' <(cat .env)",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' <(< .env)",
        "python3 -c 'import sys; print(sys.stdin.read())' < <(tr a a < .env)",
        (
            'uv run python -c "import sys; '
            'print(open(sys.argv[1]).read())" \\\n    $(git rev-parse '
            "--show-toplevel)/.env"
        ),
        # The name is on the stdin of the code, from an earlier command of the pipeline.
        ('echo .env | python3 -c "import sys; print(open(sys.stdin.read().strip()).read())"'),
        "printf .env | python3 -c 'import sys; print(open(input()).read())'",
        "dd if=.env 2>/dev/null | python3 -c 'import sys; print(sys.stdin.read())'",
        "base64 .env | python3 -c 'import sys; print(sys.stdin.read())'",
        (
            'git check-ignore .env | python3 -c "import sys; '
            'print(open(sys.stdin.read().strip()).read())"'
        ),
        (
            'ls -a | grep -x .env | python3 -c "import sys; '
            'print(open(sys.stdin.read().strip()).read())"'
        ),
        # A backslash and a newline inside the command, or the flag glued to the code.
        "echo hi\\\n; python3 -c \"print(open('.env').read())\"",
        "python3 -c \\\n\"print(open('.env').read())\"",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' \\\n  .env",
        "python3 -c \\\n  'import sys; print(open(sys.argv[1]).read())' .env",
        "python3 -c\"print(open('.env').read())\"",
        "python3 -c'print(open(\".env\").read())'",
        "node -e\"console.log(require('fs').readFileSync('.env','utf8'))\"",
        "python3 -c \"import os\nprint(open('.env').read())\"",
        # Another command before, after or around the code, a here-document, quoting forms.
        "python3 -c \"print(open('.env').read())\" &",
        "sleep 1 & python3 -c \"print(open('.env').read())\"",
        "cat <<'A'\nhello\nA\npython3 - <<'B'\nprint(open('.env').read())\nB",
        "python3 - <<'A'\nprint(1)\nA\ncat <<'B'\n.env\nB",
        "python3 /dev/stdin <<'EOF'\nprint(open('.env').read())\nEOF",
        "python3 -c \"$(cat <<'EOF'\nprint(open('.env').read())\nEOF\n)\"",
        "python3 -c 'print(open(\".env\").read())'",
        "python3 -c $'print(open(\".env\").read())'",
        "uv run python - <<'EOF'\nprint(open('.env').read())\nEOF",
        "ruby -e 'puts File.read(\".env\")'",
        # The name as an argument of the code, in a group, a condition, `time`, `find`, `xargs`.
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' .env",
        "python3 -c 'import sys; print(open(sys.argv[1]).read())' ./.env",
        "{ python3 -c 'import sys; print(open(sys.argv[1]).read())' .env; }",
        ("if true; then python3 -c 'import sys; print(open(sys.argv[1]).read())' .env; fi"),
        "time python3 -c 'import sys; print(open(sys.argv[1]).read())' .env",
        "xargs -a <(echo .env) python3 -c 'import sys; print(open(sys.argv[1]).read())'",
        ("find . -name .env -exec python3 -c 'import sys; print(open(sys.argv[1]).read())' {} \\;"),
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
        # Code on the stdin of an interpreter that is the end of a pipe, here-document or not.
        f"cat <<'EOF' | python3\n{READS_ENV}\nEOF",
        f"cat <<'EOF' | uv run python\n{READS_ENV}\nEOF",
        f"cat <<EOF | python3.12 -u\n{READS_ENV}\nEOF",
        f"cat <<'EOF' | env PYTHONUNBUFFERED=1 python3\n{READS_ENV}\nEOF",
        f'echo "{READS_ENV}" | python3',
        f"printf '{READS_ENV}' | python3 -u",
        f'cat script.txt && echo "{READS_ENV}" | python3 && echo done',
        "cat <<'EOF' | node\nrequire('fs').readFileSync('.env')\nEOF",
        "cat <<'EOF' | perl\nopen(F, '.env'); print <F>\nEOF",
        "cat <<'EOF' | ruby\nputs File.read('.env')\nEOF",
        f"x=$(cat <<'EOF' | python3\n{READS_ENV}\nEOF\n)",
        # The same with a shell, which can hold the name in a variable.
        "cat <<'EOF' | bash\nf=.env\ncat \"$f\"\nEOF",
        "echo 'f=.env; cat $f' | sh",
        "cat <<'EOF' | bash -s\nf=.env\ncat \"$f\"\nEOF",
        "bash <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        'sh <<EOF\nf=.env\ncat "$f"\nEOF',
        "bash <<< 'f=.env; cat $f'",
        "/bin/bash <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        f'python3 < <(echo "{READS_ENV}")',
        f'echo "{READS_ENV}" | python3 /dev/stdin',
        f'echo "{READS_ENV}" | python3 -X dev',
        f'echo "{READS_ENV}" | python3 | tee out.txt',
        # A redirect right after the interpreter does not give it a script file.
        f"cat <<'EOF' | python3 2>&1 | tail -3\n{READS_ENV}\nEOF",
        f"cat <<'EOF' | python3 2>/dev/null\n{READS_ENV}\nEOF",
        f"cat <<'EOF' | python3 &>/dev/null\n{READS_ENV}\nEOF",
        f"cat <<'EOF' | python3 >out.txt\n{READS_ENV}\nEOF",
        "echo 'cat .env' | bash 2>&1",
        "echo 'cat .env' | bash 2>&1 | head",
        # A wrapper with an option and its value, a group around the interpreter.
        f'echo "{READS_ENV}" | nice -n 5 python3',
        f'echo "{READS_ENV}" | timeout 60 python3',
        f'echo "{READS_ENV}" | stdbuf -oL python3',
        f'echo "{READS_ENV}" | env -i python3',
        f'echo "{READS_ENV}" | sudo -u nobody python3',
        "echo 'f=.env; cat $f' | sudo -u nobody bash",
        f'echo "{READS_ENV}" | (python3)',
        f'echo "{READS_ENV}" | ( python3 )',
        f'echo "{READS_ENV}" | {{ python3; }}',
        f'echo "{READS_ENV}" | timeout --signal=KILL 60 python3',
        # An escaped separator in the value of an option, or a command line handed over by xargs.
        f'python3 -X a\\;b -c "{READS_ENV}"',
        f'python3 -Xa\\|b -c "{READS_ENV}"',
        "echo 'cat .env' | xargs -I{} bash -c {}",
        # A shell with options only reads its here-document as code.
        "bash -x <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        # The line is cut by a backslash right after the interpreter or after the command name.
        f'python3 \\\n-c "{READS_ENV}"',
        f'python3 \\\n  -c "{READS_ENV}"',
        f'uv run python \\\n-c "{READS_ENV}"',
        f'python3 -u \\\n  -c "{READS_ENV}"',
        f'python3\\\n -c "{READS_ENV}"',
        "cat \\\n.env",
        "git status; cat \\\n  .env",
        "grep PASSWORD \\\n  .env",
        # Two backslashes are a literal one: the newline after them ends the command.
        "echo a\\\\\ncat .env",
        "echo a\\\\\\\n; cat .env",
        # An option with a value in quotes that hold a separator comes before `-c`.
        f"python3 -X 'a;b' -c \"{READS_ENV}\"",
        f'python3 -X "a;b" -c "{READS_ENV}"',
        f"python3 -W 'a|b' -c \"{READS_ENV}\"",
        f"python3 -X 'a&b' -c \"{READS_ENV}\"",
        f"python3 -X 'a;b' -X 'c;d' -c \"{READS_ENV}\"",
        f"node --require 'a;b' -e \"{READS_ENV}\"",
        "python3 -X 'a;b' - <<'EOF'\nprint(open('.env').read())\nEOF",
        "python3 -X 'a;b' <<'EOF'\nprint(open('.env').read())\nEOF",
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
        "git status; cat \\\n  README.md",
        "python3 -X 'a;b' -c 'print(1)'",
        "python3 -X 'a;b' -c 'print(open(\".env.example\").read())'",
        "cat Makefile | python3 -m json.tool",
        "ls scripts | grep sh",
        "git log --oneline | head -3",
        "echo 'a|b' | tr a b",
        "bash scripts/hello.sh <<'EOF'\nyes\nEOF",
        "./scripts/run.sh <<'EOF'\nyes\nEOF",
        # A shell that runs a script file reads the here-document as data, not as code.
        "bash scripts/hello.sh <<'EOF'\nmentions .env\nEOF",
        "sh -x scripts/hello.sh .env <<EOF\nyes\nEOF",
        # A module or a script file after the options is what runs; the pipe is its data.
        "git ls-files | grep .env | python3 -u scripts/x.py",
        "git ls-files | grep .env | uv run python -u scripts/x.py",
        "git ls-files | grep .env | python3 -m json.tool",
        "git ls-files | grep .env | python3 -X dev scripts/x.py",
        "git ls-files | grep .env | python3 -W error -m json.tool",
        "git ls-files | grep .env | python3 -mjson.tool",
        "git ls-files | grep .env | timeout 60 python3 scripts/x.py",
        "git ls-files | grep .env | nice -n 5 python3 scripts/x.py",
        # A script file is run: the piped text is its data, and `||` is no pipe.
        "git check-ignore .env | python3 parse.py",
        "git check-ignore .env | bash scripts/hello.sh",
        "git check-ignore .env || python3 -u build.py",
        "git check-ignore .env || bash",
    ],
)
def test_guard_lets_the_unusual_forms_without_env_pass(command: str) -> None:
    assert decision(bash(command)) == "allow"


# The same forms hide the module of the stamp code from the guard.
@pytest.mark.parametrize(
    "command",
    [
        "echo \"from scripts import agent_state as s; s.write_stamp(None, 'full')\" | python3",
        "printf 'import scripts.agent_state' | python3 -u",
        "cat scripts/agent_state.py | uv run python",
        "python3 -X 'a;b' -c \"from scripts.agent_state import write_stamp\"",
        "python3 -W 'a|b' -c \"import scripts.agent_state\"",
        'python3 \\\n-c "from scripts.agent_state import write_stamp"',
        'python3 \\\n  -c "from scripts.agent_state import write_stamp"',
        'uv run python \\\n-c "import scripts.agent_state"',
        "python3 -X 'a;b' -c \"open('.review-stamp', 'w').write('x')\"",
        # A redirect after the interpreter, a process substitution, a wrapper with options.
        "echo 'from scripts.agent_state import write_stamp' | python3 2>&1",
        "echo 'from scripts.agent_state import write_stamp' | python3 2>/dev/null",
        "echo 'from scripts.agent_state import write_stamp' | python3 &>/dev/null",
        "cat <<'EOF' | python3 2>&1 | tail -3\nfrom scripts.agent_state import write_stamp\nEOF",
        "python3 < <(echo 'import scripts.agent_state')",
        'python3 -X a\\;b -c "import scripts.agent_state"',
        "echo 'import scripts.agent_state as s' | nice -n 5 python3",
        "echo 'import scripts.agent_state as s' | timeout 60 python3",
        "echo 'import scripts.agent_state as s' | stdbuf -oL python3",
        "echo 'import scripts.agent_state as s' | (python3)",
        "echo 'import scripts.agent_state as s' | { python3; }",
    ],
)
def test_guard_denies_a_gate_stamp_written_through_an_unusual_interpreter_call(
    command: str,
) -> None:
    result = bash(command)

    assert decision(result) == "deny"
    assert "writes a gate stamp by hand" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "echo 'print(1)' | python3 -u",
        "python3 -X 'a;b' -c 'print(1)'",
        "python3 \\\n-c 'print(1)'",
        "python3 -X 'a;b' scripts/agent_state.py tree .",
        "cat scripts/agent_state.py | head -5",
        "uv run pytest tests/unit/test_agent_state.py -q 2>&1 | python3 summarize.py",
        "git diff scripts/agent_state.py | python3 render.py",
        "cat scripts/agent_state.py | python3 -m ast",
        "git log -p -- scripts/agent_state.py | python3 -m pydoc",
        "cat scripts/agent_state.py | python3 -u scripts/render.py",
        "cat scripts/agent_state.py | python3 -W error -m ast",
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


def move_code_out(repo: Path, target: str) -> None:
    """`job.py` leaves the code paths with its content: git shows it as a rename."""
    (repo / target).parent.mkdir(exist_ok=True)
    (repo / "job.py").rename(repo / target)


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
    (repo / "job.py").write_text("x = 2\n")
    gate_stamps(repo)
    move_code_out(repo, target)

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

    assert "lakehouse-kafka-1 Up 2 hours (healthy)" in context
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

    assert "lakehouse-kafka-1 Up 2 hours (healthy)" in context
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
    assert "otherstack-kafka-1 Up 2 hours (healthy)" in context
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
    assert "Containers:\naaa" in context and "docker start" not in context

    # Nothing but git on PATH: no docker at all.
    only_git = tmp_path_factory.mktemp("only-git")
    (only_git / "git").symlink_to(shutil.which("git") or "git")
    monkeypatch.setenv("PATH", str(only_git))
    context = session_context(repo)

    assert "Containers:" in context and "docker start" not in context


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
    ):
        assert settings["enabledPlugins"][plugin] is False
    assert (HOOKS / "review_stamp.py").exists()


# B18: the stdin-as-code forms the first round of the pipe and heredoc checks left open. A shell
# option that takes a value is not a script file, `-s` reads the script from stdin whatever follows,
# a group on the receiving end of a pipe, a process substitution and the interpreters beyond python
# are inline code too. Each command hides `.env` in quotes, so only the inline code can read it.
PIPED_TEXT = "echo 'cat .env' | "
PYTHON_TEXT = "echo \"print(open('.env').read())\" | "
STAMP_TEXT = "echo 'import scripts.agent_state as s' | "


@pytest.mark.parametrize(
    "command",
    [
        PIPED_TEXT + "bash -euo pipefail",
        PIPED_TEXT + "bash -o pipefail",
        PIPED_TEXT + "bash -eo pipefail",
        PIPED_TEXT + "bash +o history",
        PIPED_TEXT + "bash -O extglob",
        PIPED_TEXT + "bash --rcfile /dev/null",
        PIPED_TEXT + "bash -s -- arg",
        PIPED_TEXT + "bash -s arg",
        PIPED_TEXT + "bash -es -- a b",
        PIPED_TEXT + "bash -e -",
        PIPED_TEXT + "bash -o pipefail -",
        PIPED_TEXT + "bash -euo pipefail -s",
        PIPED_TEXT + "sudo -E bash -s -- arg",
        PIPED_TEXT + "nice -n 5 bash -o pipefail",
        PIPED_TEXT + "zsh -o errexit",
        PIPED_TEXT + "env -i bash -o pipefail",
        PIPED_TEXT + "timeout 60 sh -o pipefail",
        PIPED_TEXT + "bash -o pipefail 2>&1",
        "bash -o pipefail <<< 'cat .env'",
        "bash -o pipefail <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        "bash -euo pipefail <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        "bash -s -- arg <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        'bash -s -- a <<< "f=.env; cat \\$f"',
        "bash -e - <<< 'cat .env'",
        "bash - <<< 'cat .env'",
        "bash -o pipefail < <(echo 'cat .env')",
        "bash <(echo 'cat .env')",
        "bash -o pipefail <(echo 'cat .env')",
        "bash -e <(echo 'cat .env')",
    ],
)
def test_a_shell_option_with_a_value_does_not_make_the_piped_text_a_script_file(
    command: str,
) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        PYTHON_TEXT + "python3 --check-hash-based-pycs never",
        PYTHON_TEXT + "python3 -X dev --check-hash-based-pycs always -u",
        PYTHON_TEXT + "( cd /x && python3 )",
        PYTHON_TEXT + "{ cd /x; python3; }",
        PYTHON_TEXT + "( cd /x; nice -n 5 python3 -u )",
        PYTHON_TEXT + "tee >(python3)",
        PYTHON_TEXT + "tee /dev/null >(python3 -u)",
        "python3 <(echo \"print(open('.env').read())\")",
        "python3 -u <(echo \"print(open('.env').read())\")",
        "python3 -B -X dev <(echo \"print(open('.env').read())\")",
        "python3 -- <(echo \"print(open('.env').read())\")",
        PYTHON_TEXT + "pypy3",
        PYTHON_TEXT + "pypy3 -u",
        "pypy3 -c \"print(open('.env').read())\"",
        "pypy3 - <<'EOF'\nprint(open('.env').read())\nEOF",
        "pypy3 <<< \"print(open('.env').read())\"",
        "node -p \"require('fs').readFileSync('.env','utf8')\"",
        "node --print \"require('fs').readFileSync('.env','utf8')\"",
        "node --eval \"console.log(require('fs').readFileSync('.env','utf8'))\"",
        "node -r dotenv/config -p \"require('fs').readFileSync('.env','utf8')\"",
        "perl -E 'say for do { local @ARGV = (\".env\"); <> }'",
        "perl -nE 'say' .env",
        "perl -Mstrict -E 'say for do { local @ARGV = (\".env\"); <> }'",
    ],
)
def test_the_inline_code_of_the_other_forms_that_reads_env_asks(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        STAMP_TEXT + "pypy3",
        STAMP_TEXT + "( cd /x && python3 )",
        STAMP_TEXT + "{ cd /x; python3; }",
        STAMP_TEXT + "tee >(python3)",
        STAMP_TEXT + "python3 --check-hash-based-pycs never",
        STAMP_TEXT + "nice -n 5 pypy3 -u",
        "python3 <(echo 'import scripts.agent_state')",
        "python3 -u <(echo 'import scripts.agent_state')",
        "python3 --check-hash-based-pycs never <(echo 'import scripts.agent_state')",
        "python3 -X dev --check-hash-based-pycs never <(echo 'import scripts.agent_state')",
        "pypy3 -c 'import scripts.agent_state'",
        "pypy3 -c 'import scripts.agent_state' x",
    ],
)
def test_the_other_forms_of_inline_python_that_name_the_stamp_code_are_denied(
    command: str,
) -> None:
    assert decision(bash(command)) == "deny"


# The forms the first draft of this patch let through while HEAD asked or denied, and the
# neighbours of the new forms. HEAD asks for all but `| bash --`, `bash - <<'EOF'`, which it let
# pass (a gap this patch closes), so those two ask here too.
@pytest.mark.parametrize(
    "command",
    [
        PIPED_TEXT + "bash -",
        PIPED_TEXT + "bash --",
        PIPED_TEXT + "bash -es",
        PIPED_TEXT + "bash -e",
        PIPED_TEXT + "bash",
        PIPED_TEXT + "bash -c 'ls'",
        "bash -- <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        "bash - <<'EOF'\nf=.env\ncat \"$f\"\nEOF",
        "python3 -- < <(echo \"print(open('.env').read())\")",
        PYTHON_TEXT + "python3 -u -",
        PYTHON_TEXT + "python3 -X dev",
    ],
)
def test_the_forms_that_asked_before_still_ask(command: str) -> None:
    assert decision(bash(command)) == "ask"


def test_a_stamp_written_through_python_u_and_a_process_substitution_is_still_denied() -> None:
    command = "python3 -u - < <(echo 'import scripts.agent_state as s')"

    assert decision(bash(command)) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        PIPED_TEXT + "bash script.sh",
        PIPED_TEXT + "bash -o pipefail script.sh",
        PIPED_TEXT + "bash -euo pipefail ./run.sh arg -s",
        PIPED_TEXT + "bash -- script.sh",
        PIPED_TEXT + "bash +o history script.sh",
        PYTHON_TEXT + "python3 script.py",
        PYTHON_TEXT + "python3 -u script.py -x",
        PYTHON_TEXT + "python3 -m json.tool",
        PYTHON_TEXT + "python3 --check-hash-based-pycs never script.py",
        PYTHON_TEXT + "( cd /x && python3 script.py )",
        PYTHON_TEXT + "tee >(cat) > /dev/null",
        PYTHON_TEXT + "node scripts/x.js -p",
        PYTHON_TEXT + "node scripts/x.js --print",
        PYTHON_TEXT + "node -r dotenv/config scripts/x.js -p 3000",
        PYTHON_TEXT + "perl script.pl -E",
        PYTHON_TEXT + "pypy3 script.py",
        "grep -rn .env docs | node scripts/x.js -p",
        "python3 script.py <(echo .env)",
        "git log --oneline | python3 -m json.tool",
    ],
)
def test_a_script_file_or_a_module_keeps_the_piped_text_as_data(command: str) -> None:
    assert decision(bash(command)) == "allow"


def load_guard(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The guard's names without running its stdin check, to call `check` with a stub inside."""
    source = (HOOKS / "guard.py").read_text()
    head = source.split("\ntry:\n    check(json.load(sys.stdin))")[0]
    names: dict[str, Any] = {"__name__": "guard_under_test", "__file__": str(HOOKS / "guard.py")}
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(REPO))
    monkeypatch.syspath_prepend(str(REPO))
    exec(compile(head, "guard.py", "exec"), names)
    return names


def test_a_failure_in_one_text_of_the_command_does_not_lower_a_deny_in_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = load_guard(monkeypatch)

    def check_bash(text: str) -> None:
        if text == "echo ab":
            raise RuntimeError("a regex gave up")
        raise guard["VerdictError"]("deny", "the raw text is denied")

    guard["check_bash"] = check_bash

    with pytest.raises(guard["VerdictError"]) as raised:
        guard["check"]({"tool_name": "Bash", "tool_input": {"command": "echo a\\\nb"}})

    assert raised.value.kind == "deny"


def test_a_failure_in_every_text_of_the_command_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = load_guard(monkeypatch)

    def check_bash(text: str) -> None:
        raise RuntimeError("a regex gave up")

    guard["check_bash"] = check_bash

    with pytest.raises(guard["VerdictError"]) as raised:
        guard["check"]({"tool_name": "Bash", "tool_input": {"command": "echo a\\\nb"}})

    assert raised.value.kind == "ask"


# The wrapper options once backtracked without bound: `nice` and 22 pairs of `-a 5` before a
# command that does not match took seconds. The decision is checked as well as the time, so that
# a guard that gives up early cannot pass.
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (PIPED_TEXT + "nice" + " -a 5" * 40 + " bash script.sh", "allow"),
        (PIPED_TEXT + "nice" + " -a 5" * 40 + " ls", "allow"),
        (PIPED_TEXT + "nice" + " -a 5" * 40 + " bash -o pipefail", "ask"),
        (PIPED_TEXT + "nice" + " -a 5" * 40 + " bash", "ask"),
        (STAMP_TEXT + "nice" + " -a 5" * 40 + " python3", "deny"),
        (STAMP_TEXT + "timeout" + " -k 5" * 40 + " 9 python3 script.py", "allow"),
        (STAMP_TEXT + "env" + " -a 5" * 40 + " nice" + " -a 5" * 40 + " ls", "allow"),
        (PIPED_TEXT + "nice" + " -a env" * 40 + " ls", "allow"),
        (PIPED_TEXT + "nice" + " -a nice" * 40 + " ls", "allow"),
        (PIPED_TEXT + "nice" + " -a A=1 nice" * 40 + " ls", "allow"),
        (STAMP_TEXT + "nice" + " -a env" * 40 + " python3", "deny"),
        (STAMP_TEXT + "nice" + " -a A=1 nice" * 40 + " python3", "deny"),
    ],
)
def test_forty_wrapper_options_are_decided_in_under_a_second(command: str, expected: str) -> None:
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO)}
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(HOOKS / "guard.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the guard did not decide in 10 s")
    elapsed = time.monotonic() - started

    assert decision(result) == expected
    assert elapsed < 1


# A word that starts with `#` ends the command at the next line break or separator, as in bash. It
# is no script file of the interpreter before it, so the piped text stays its code. A `#` inside
# a word or inside quotes is no comment.
@pytest.mark.parametrize(
    "command",
    [
        PYTHON_TEXT + "python3 -u # x",
        PYTHON_TEXT + "python3 # x",
        PIPED_TEXT + "bash # x",
        PIPED_TEXT + "bash -e # x",
        PYTHON_TEXT + "python3 #x; ls",
        PYTHON_TEXT + "python3 # x | cat",
        PYTHON_TEXT + "python3 # it's a comment",
        PYTHON_TEXT + "nice -n 5 python3 # x",
        PYTHON_TEXT + "python3 # x\nls",
    ],
)
def test_a_comment_after_the_interpreter_does_not_make_the_piped_text_data(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        STAMP_TEXT + "python3 # x",
        STAMP_TEXT + "python3 -u # x",
        STAMP_TEXT + "pypy3 # x",
    ],
)
def test_a_comment_after_the_interpreter_does_not_hide_the_stamp_code_in_the_pipe(
    command: str,
) -> None:
    assert decision(bash(command)) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        PYTHON_TEXT + "python3 a#b",
        PYTHON_TEXT + "python3 '#'",
        PYTHON_TEXT + 'python3 "#x"',
        PIPED_TEXT + "bash '# x'",
        "python3 script.py # x",
        PYTHON_TEXT + "python3 script.py #x; ls",
    ],
)
def test_a_hash_inside_a_word_or_quotes_is_not_a_comment(command: str) -> None:
    assert decision(bash(command)) == "allow"


# A comment runs to the line break, not to the next `;`, `&` or `|` (`bash -c 'true # a; echo x'`
# prints nothing). A quote in what follows the `;` is part of the comment: it must not unbalance
# the quotes of the next line, where the real command is.
@pytest.mark.parametrize(
    "command",
    [
        "true # a; it's\necho 'cat .env' | bash -o pipefail # '",
        "true # a & it's\necho 'cat .env' | bash -o pipefail # '",
        "true # a | it's\necho 'cat .env' | bash -o pipefail # '",
        "true # a; it's\n" + PIPED_TEXT + "bash -o pipefail",
        "true # a; it's\n" + PYTHON_TEXT + "python3 -X dev --check-hash-based-pycs never # '",
        PIPED_TEXT + "bash -o pipefail # it's",
        PIPED_TEXT + "bash -o pipefail # a; it's\nls",
    ],
)
def test_a_quote_after_a_separator_inside_a_comment_does_not_hide_the_next_line(
    command: str,
) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


def test_a_stamp_written_after_a_comment_with_a_separator_and_a_quote_is_denied() -> None:
    command = "true # a; it's\n" + STAMP_TEXT + "python3 --check-hash-based-pycs never # '"

    assert decision(bash(command)) == "deny"


# What a comment hides is decided by the quotes: a `#` inside quotes is text (the value of `-o`
# is a word, so the shell still reads its script from the pipe), and a `#` right after a bracket
# starts a comment, whose quote must not unbalance the rest.
@pytest.mark.parametrize(
    "command",
    [
        PIPED_TEXT + "bash -o 'a #b'",
        PIPED_TEXT + 'bash -o "a #b"',
        PIPED_TEXT + "bash -o 'a #b' # c",
        PYTHON_TEXT + "( #x\npython3)",
        PIPED_TEXT + "(#)\nbash -o pipefail )",
        PIPED_TEXT + "tee >(#)\nbash -o pipefail )",
        PYTHON_TEXT + "(#)\npython3 -X dev )",
        PYTHON_TEXT + "(#it's\npython3)",
        PYTHON_TEXT + "( python3 -u\n#it's\n)",
        PIPED_TEXT + "(#it's\nbash -o pipefail)",
        PIPED_TEXT + "$(#it's\nbash -o pipefail)",
    ],
)
def test_the_quotes_decide_which_hash_starts_a_comment(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "python3 'a #b'",
        PYTHON_TEXT + "python3 'a #b'",
        PIPED_TEXT + 'bash "x #y"',
        PIPED_TEXT + "bash 'a #b'",
        PIPED_TEXT + "bash 'it #s' x",
    ],
)
def test_a_script_file_with_a_hash_in_quotes_is_still_a_script_file(command: str) -> None:
    assert decision(bash(command)) == "allow"


# The stdin of a wrapped interpreter is its code whatever the options of the wrapper look like: a
# value with a point (`0.5`), a suffix (`1.5s`, `5x`), an assignment (`-u A=1`) or a wrapper name
# that is no value. The decimal forms and the assignment were once read as the end of the options,
# and the quotes around `$(...)` hide the text from the token scan, so only the patterns decide.
SUBSTITUTED_STAMP = 'echo "$(' + STAMP_TEXT
SUBSTITUTED_SECRET = 'echo "$(' + PIPED_TEXT


@pytest.mark.parametrize(
    "command",
    [
        SUBSTITUTED_STAMP + 'timeout -k 0.5 9 python3)"',
        SUBSTITUTED_STAMP + 'timeout --kill-after 1.5 9 python3)"',
        SUBSTITUTED_STAMP + 'timeout -k 0.5 9 python3 -u)"',
        SUBSTITUTED_STAMP + 'timeout -k 0.5s 9 python3)"',
        SUBSTITUTED_STAMP + 'nice -n 5x python3)"',
        SUBSTITUTED_STAMP + 'stdbuf -o 0x python3 -u)"',
        SUBSTITUTED_STAMP + 'nice -a A=1 5 python3)"',
        SUBSTITUTED_STAMP + 'sudo -u A=1 -E python3)"',
        SUBSTITUTED_STAMP + 'env -u A=1 -i python3)"',
        SUBSTITUTED_STAMP + 'nice -a env -n 5 python3)"',
        SUBSTITUTED_STAMP + 'sudo -u nice -E python3)"',
        SUBSTITUTED_STAMP + 'stdbuf -oL python3)"',
        SUBSTITUTED_STAMP + 'sudo -E uv run 5 -E 0.5 9 python3)"',
        'x="$(' + STAMP_TEXT + 'nice -n 5x python3)"',
        'sh -c "' + STAMP_TEXT + 'stdbuf -o 0x python3 -u"',
    ],
)
def test_wrapper_options_with_a_decimal_a_suffix_or_an_assignment_still_feed_the_interpreter(
    command: str,
) -> None:
    assert decision(bash(command)) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        SUBSTITUTED_SECRET + 'sudo -E uv run 5 -E 0.5 9 bash)"',
        SUBSTITUTED_SECRET + 'timeout -k 0.5 9 bash)"',
        SUBSTITUTED_SECRET + '(timeout -k 0.5 9 bash))"',
        SUBSTITUTED_SECRET + 'nice -a A=1 5 bash)"',
        SUBSTITUTED_SECRET + 'nice -n 5x bash)"',
        SUBSTITUTED_SECRET + 'sudo -u A=1 -E bash)"',
        "echo \"$( (echo 'cat .env') | timeout -k 0.5 9 bash)\"",
        'echo "$(' + PYTHON_TEXT + '(timeout -k 0.5 9 python3))"',
        PIPED_TEXT + "sudo -E uv run 5 -E 0.5 9 bash",
    ],
)
def test_wrapper_options_with_a_decimal_or_an_assignment_still_feed_the_shell(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


# A wrapper name after an option is the next wrapper, not the value of the option.
@pytest.mark.parametrize(
    "command",
    [
        PIPED_TEXT + "env -i uv run python3 -X dev --check-hash-based-pycs never",
        PIPED_TEXT + "sudo -E uv run bash -o pipefail",
        PIPED_TEXT + "sudo -E uv run python3 --check-hash-based-pycs never",
        PIPED_TEXT + "sudo -E env bash -o pipefail",
        PIPED_TEXT + "sudo -E nice -n 5 bash -o pipefail",
        PIPED_TEXT + "sudo -E poetry run bash -o pipefail",
        PIPED_TEXT + "env -i timeout 9 bash -o pipefail",
    ],
)
def test_a_wrapper_after_an_option_is_not_the_value_of_that_option(command: str) -> None:
    result = bash(command)

    assert decision(result) == "ask"
    assert "secret" in result.stdout


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (SUBSTITUTED_STAMP + "nice" + " -a A=1 5" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a 5x" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a 0.5" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a 1.5s" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a A=1" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a A=1 nice" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a 5 A=1" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a A=1 5" * 40 + ' ls)"', "allow"),
        (SUBSTITUTED_STAMP + "nice" + " -a A=1 5" * 40 + 'x)"', "allow"),
        (SUBSTITUTED_STAMP + "nice" + " 5 -a" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a uv run" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -a -b 5" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_STAMP + "nice" + " -k 0.5" * 40 + ' python3)"', "deny"),
        (SUBSTITUTED_SECRET + "nice" + " -a A=1 5" * 40 + ' bash)"', "ask"),
        (SUBSTITUTED_SECRET + "nice" + " -a 5x" * 40 + ' bash -o pipefail)"', "ask"),
        (PIPED_TEXT + "nice" + " -a A=1 5" * 40 + " bash -o pipefail", "ask"),
        (PIPED_TEXT + "nice" + " -a 0.5" * 40 + " ls", "allow"),
    ],
)
def test_forty_odd_wrapper_options_are_decided_in_under_a_second(
    command: str, expected: str
) -> None:
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO)}
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(HOOKS / "guard.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the guard did not decide in 10 s")
    elapsed = time.monotonic() - started

    assert decision(result) == expected
    assert elapsed < 1
