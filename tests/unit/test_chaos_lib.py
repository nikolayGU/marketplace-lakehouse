"""Shell helpers of scripts/chaos/lib.sh, run in bash with stubs on PATH."""

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def run_lib(
    tmp_path: Path, body: str, stubs: dict[str, str] | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "scripts" / "chaos" / "lib.sh", root / "scripts" / "chaos" / "lib.sh")
    (root / ".env").write_text("OLTP_USER=user\nOLTP_DB=db\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in (stubs or {}).items():
        path = bin_dir / name
        path.write_text(f"#!/usr/bin/env bash\n{text}\n")
        path.chmod(0o755)
    script = f'. "{root}/scripts/chaos/lib.sh"\n{body}\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", **env},
    )


def test_run_dag_reports_unknown_state_when_the_cli_fails(tmp_path: Path) -> None:
    body = """airflow_cli() { [ "$1 $2" = "dags trigger" ]; }
run_dag d r"""
    result = run_lib(tmp_path, body, RUN_DAG_WAIT="0")
    assert result.returncode == 1
    assert "d run r still unknown after 0 s" in result.stderr


def test_container_of_prints_the_id_of_the_service(tmp_path: Path) -> None:
    stubs = {"docker": 'echo "args: $*" >&2; echo abc123'}
    result = run_lib(tmp_path, "container_of spark-bronze", stubs)
    assert result.returncode == 0
    assert result.stdout == "abc123\n"
    # Created containers of every profile; a stopped one is not listed.
    assert "--profile * ps -q spark-bronze" in result.stderr


def test_container_of_fails_naming_the_service_on_empty_answer(tmp_path: Path) -> None:
    result = run_lib(tmp_path, "container_of kafka-connect", {"docker": "exit 0"})
    assert result.returncode == 1
    assert "no running container for service kafka-connect" in result.stderr
    assert result.stdout == ""


def test_container_of_fails_naming_the_service_when_docker_fails(tmp_path: Path) -> None:
    result = run_lib(tmp_path, "container_of kafka-connect", {"docker": "exit 1"})
    assert result.returncode == 1
    assert "kafka-connect" in result.stderr


def test_fail_prints_one_line_and_exits_1(tmp_path: Path) -> None:
    result = run_lib(tmp_path, 'fail "it broke" badly; echo unreachable')
    assert result.returncode == 1
    assert result.stderr == "FAIL: it broke badly\n"
    assert result.stdout == ""


def test_airflow_api_get_sends_the_token_to_the_path(tmp_path: Path) -> None:
    curl = r"""
for a in "$@"; do echo "arg: $a" >> "$CURL_LOG"; done
case "$*" in
  */auth/token*) echo '{"access_token": "tok123"}' ;;
  *) echo '{"ok": true}' ;;
esac"""
    log = tmp_path / "curl.log"
    result = run_lib(
        tmp_path,
        "airflow_api_get dags/x/dagRuns",
        {"curl": curl},
        CURL_LOG=str(log),
        BIND_IP="10.0.0.1",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == '{"ok": true}'
    args = log.read_text().splitlines()
    assert "arg: Authorization: Bearer tok123" in args
    assert "arg: http://10.0.0.1:8090/api/v2/dags/x/dagRuns" in args


def test_airflow_api_get_fails_when_there_is_no_token(tmp_path: Path) -> None:
    # Called in a condition, as callers do: errexit is off there, so only the function's own
    # return keeps the request from going out with an empty token.
    curl = r"""
case "$*" in
  */auth/token*) exit 22 ;;
  *) echo "request: $*" >> "$CURL_LOG" ;;
esac"""
    log = tmp_path / "curl.log"
    body = 'if airflow_api_get dags; then echo passed; else echo "failed $?"; fi'
    result = run_lib(tmp_path, body, {"curl": curl}, CURL_LOG=str(log))
    assert result.stdout == "failed 1\n"
    assert not log.exists()


def test_task_log_keeps_the_json_accept_header(tmp_path: Path) -> None:
    curl = r"""
echo "$*" >> "$CURL_LOG"
case "$*" in
  */auth/token*) echo '{"access_token": "t"}' ;;
  *) echo '{"content": [{"event": "line one"}]}' ;;
esac"""
    log = tmp_path / "curl.log"
    result = run_lib(tmp_path, "task_log d r t", {"curl": curl}, CURL_LOG=str(log))
    assert result.returncode == 0
    assert result.stdout == "line one\n"
    assert "Accept: application/json" in log.read_text()


def test_no_script_copies_the_offsets_sql_or_names_a_container() -> None:
    lib = REPO / "scripts" / "chaos" / "lib.sh"
    files = [
        p
        for d in ("scripts", "connect")
        for p in (REPO / d).rglob("*")
        if p.is_file() and p.suffix in {".sh", ".py", ".sql"} and p != lib
    ]
    copies = [str(p) for p in files if "count(distinct kafka_offset)" in p.read_text()]
    assert copies == []
    literal = re.compile(r"lakehouse-[a-z-]+-1")
    named = [
        f"{p}:{n}"
        for p in files
        if p.suffix == ".sh"
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if literal.search(line) and not line.lstrip().startswith("#")
    ]
    assert named == []
