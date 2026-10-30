"""REL-01, REL-02: `make report` shows a long-lived container that is down.

`restart: unless-stopped` does not bring back a container that `docker kill` or `docker stop`
marked as stopped by hand, and nothing else raises it. The script runs here against a fake
`docker` that prints what `docker ps` and `docker inspect` would.
"""

import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "report.sh"
SECTION = "== stopped containers"

FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE_DOCKER_DIR/calls.log"
[ -f "$FAKE_DOCKER_DIR/inspect.txt" ] || exit 1
case "$1" in
  ps)
    case "$*" in
      *--filter*) cat "$FAKE_DOCKER_DIR/ids.txt" ;;
      *) echo "lakehouse-trino-1 Up 3 hours (healthy)" ;;
    esac ;;
  inspect) cat "$FAKE_DOCKER_DIR/inspect.txt" ;;
  *) exit 1 ;;
esac
"""

FAKE_MAKE = "#!/bin/sh\nexit 1\n"


def _run_report(
    tmp_path: Path,
    inspect_lines: list[str] | None,
    *,
    ids: list[str] | None = None,
    project: str | None = None,
) -> tuple[str, list[str]]:
    """Return the report and the docker calls; inspect_lines None means docker fails.

    ids are the container ids `docker ps` finds (five by default); project is the shell's
    COMPOSE_PROJECT_NAME, unset when None.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"docker": FAKE_DOCKER, "make": FAKE_MAKE}.items():
        tool = bin_dir / name
        tool.write_text(body)
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    if inspect_lines is not None:
        (tmp_path / "inspect.txt").write_text("".join(f"{line}\n" for line in inspect_lines))
    found = ids if ids is not None else ["id1", "id2", "id3", "id4", "id5"]
    (tmp_path / "ids.txt").write_text("".join(f"{one}\n" for one in found))
    # The developer's shell must not decide which project the report looks at.
    env = {
        **{k: v for k, v in os.environ.items() if k != "COMPOSE_PROJECT_NAME"},
        **({"COMPOSE_PROJECT_NAME": project} if project is not None else {}),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_DIR": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    calls_log = tmp_path / "calls.log"
    calls = calls_log.read_text().splitlines() if calls_log.exists() else []
    return result.stdout, calls


def _section(report: str, header: str) -> str:
    lines = report.splitlines()
    start = lines.index(header) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("== ")), len(lines))
    return "\n".join(lines[start:end])


def test_a_stopped_unless_stopped_container_is_listed_and_a_one_shot_job_is_not(
    tmp_path: Path,
) -> None:
    report, _ = _run_report(
        tmp_path,
        [
            "/lakehouse-trino-1 unless-stopped running 0",
            "/lakehouse-prometheus-1 unless-stopped exited 255",
            "/lakehouse-minio-init-1 no exited 0",
            "/lakehouse-spark-silver-1 no exited 137",
            "/lakehouse-legacy-1 always exited 1",
        ],
    )

    section = _section(report, SECTION)

    assert "project: lakehouse" in section
    assert "lakehouse-prometheus-1 exited" in section
    assert "255" in section
    assert "lakehouse-legacy-1 exited" in section
    assert "lakehouse-trino-1" not in section
    assert "lakehouse-minio-init-1" not in section
    assert "lakehouse-spark-silver-1" not in section
    assert "docker start <name>" in section
    assert "owner" in section


def test_nothing_is_listed_when_every_restartable_container_runs(tmp_path: Path) -> None:
    report, _ = _run_report(
        tmp_path,
        ["/lakehouse-trino-1 unless-stopped running 0", "/lakehouse-minio-init-1 no exited 0"],
    )

    section = _section(report, SECTION)

    assert "all restartable containers run" in section
    assert "docker start" not in section


def test_no_containers_of_the_project_is_not_reported_as_all_running(tmp_path: Path) -> None:
    # An empty list (the stack is down, or the project is another one) must not read as healthy.
    report, _ = _run_report(tmp_path, [], ids=[])

    section = _section(report, SECTION)

    assert "no containers of project lakehouse" in section
    assert "all restartable containers run" not in section


def test_the_project_comes_from_compose_project_name(tmp_path: Path) -> None:
    report, calls = _run_report(
        tmp_path,
        ["/lakehouse-fresh-prometheus-1 unless-stopped exited 255"],
        project="lakehouse-fresh",
    )

    section = _section(report, SECTION)

    assert "project: lakehouse-fresh" in section
    assert "lakehouse-fresh-prometheus-1 exited" in section
    [listing] = [call for call in calls if call.startswith("ps") and "--filter" in call]
    assert "label=com.docker.compose.project=lakehouse-fresh" in listing.split()


def test_a_docker_that_fails_reads_unavailable_and_the_report_goes_on(tmp_path: Path) -> None:
    report, _ = _run_report(tmp_path, None)

    assert _section(report, SECTION).strip() == "docker unavailable"
    assert "== replay" in report


def test_the_section_only_reads_and_prints_no_environment(tmp_path: Path) -> None:
    _, calls = _run_report(tmp_path, ["/lakehouse-prometheus-1 unless-stopped exited 255"])

    assert {call.split()[0] for call in calls} <= {"ps", "inspect"}
    inspect = [call for call in calls if call.startswith("inspect")]
    assert inspect
    assert all(".Config" not in call and "Env" not in call for call in inspect)
