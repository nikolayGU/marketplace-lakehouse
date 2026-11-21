import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def _dockerfiles() -> set[str]:
    return {
        str(p.relative_to(REPO))
        for p in REPO.rglob("Dockerfile")
        if ".venv" not in p.parts and "node_modules" not in p.parts
    }


def test_every_dockerfile_is_in_the_hadolint_matrix() -> None:
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    matrix = set(ci["jobs"]["hadolint"]["strategy"]["matrix"]["dockerfile"])

    assert matrix == _dockerfiles()


def test_third_party_actions_are_pinned_to_a_commit() -> None:
    # A tag moves, a commit does not. Every action counts, the old check saw only
    # docker/ and hadolint/. The version comment is checked in test_pinning.py.
    seen = 0
    for workflow in WORKFLOWS.glob("*.yml"):
        for line in workflow.read_text().splitlines():
            match = re.search(r"uses:\s*(?!\./)(\S+)@(\S+)", line)
            if match:
                seen += 1
                assert re.fullmatch(r"[0-9a-f]{40}", match.group(2)), line

    assert seen


def test_workflows_use_no_secret_but_the_github_token() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        for name in re.findall(r"secrets\.(\w+)", workflow.read_text()):
            assert name == "GITHUB_TOKEN", f"{workflow.name}: secrets.{name}"


def test_smoke_runs_on_demand_and_weekly_and_checks_verify_ok() -> None:
    # The schedule came back after the first green run (ADR-026).
    text = (WORKFLOWS / "smoke.yml").read_text()
    smoke = yaml.safe_load(text)
    triggers = smoke[True]  # PyYAML reads the key `on` as True

    assert set(triggers) == {"workflow_dispatch", "schedule"}
    assert triggers["schedule"] == [{"cron": "0 3 * * 1"}]
    assert "REPLAY_DATA=sample" in text
    assert "make verify" in text
    assert "grep -qx 'verify ok'" in text
    assert smoke["permissions"] == {"contents": "read"}


def test_ci_runs_the_checks_it_claims() -> None:
    # Dropping a step must turn a test red, not leave CI green with less checked.
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    runs = {
        job: " ".join(step.get("run", "") for step in spec["steps"])
        for job, spec in ci["jobs"].items()
    }

    assert "make test-spark" in runs["spark-tests"]
    assert "make dags-check AIRFLOW_IMAGE=lakehouse/airflow:ci" in runs["airflow-image"]
    assert "scripts/check-minio-images.sh" in runs["minio-images"]
    # promtool is in no other gate; a broken alert rule would reach main unnoticed.
    assert "make alerts-test" in runs["alerts-test"]


def test_the_minio_images_are_built_through_the_layer_cache_in_ci() -> None:
    # Without the cache every push compiles MinIO and mc from scratch.
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    builds = [
        step["with"]
        for step in ci["jobs"]["minio-images"]["steps"]
        if str(step.get("uses", "")).startswith("docker/build-push-action@")
    ]

    assert [(b["target"], b["tags"]) for b in builds] == [
        ("minio", "lakehouse/minio:ci"),
        ("mc", "lakehouse/mc:ci"),
    ]
    assert all(b["context"] == "docker/minio" and b["load"] for b in builds)
    assert all("type=gha" in b["cache-from"] and "type=gha" in b["cache-to"] for b in builds)
    # One scope for both targets would let the second build overwrite the cache of the first.
    assert len({b["cache-to"] for b in builds}) == len(builds)
    for b in builds:
        assert b["cache-from"].split("scope=")[1] == b["cache-to"].split("scope=")[1]


def test_ci_reads_the_repo_and_nothing_more() -> None:
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())

    assert ci["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_ci_pins_java_17_before_the_first_pytest_step() -> None:
    # ubuntu-latest moved to a newer default JDK (ubuntu-26.04) on which Spark 3.5.9 fails with
    # "getSubject is not supported"; the Spark image runs OpenJDK 17.
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    steps = ci["jobs"]["lint-and-test"]["steps"]
    java = [
        i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-java@")
    ]
    pytest = [i for i, s in enumerate(steps) if "pytest" in s.get("run", "")]

    assert len(java) == 1
    assert steps[java[0]]["with"] == {"java-version": "17", "distribution": "temurin"}
    assert pytest and java[0] < pytest[0]


def _workflow_jobs() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path.name, name, spec)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, spec in yaml.safe_load(path.read_text())["jobs"].items()
    ]


def _steps_using(prefix: str) -> list[dict[str, Any]]:
    return [
        step
        for _, _, spec in _workflow_jobs()
        for step in spec["steps"]
        if str(step.get("uses", "")).startswith(prefix)
    ]


def test_every_job_runs_on_the_pinned_runner_image() -> None:
    # ubuntu-latest moves to a new image with a new default JDK and tool set without a commit.
    jobs = _workflow_jobs()

    assert jobs
    for workflow, name, spec in jobs:
        assert spec["runs-on"] == "ubuntu-24.04", f"{workflow}: {name}"


def test_setup_uv_installs_the_pinned_uv() -> None:
    # Without a version setup-uv takes the latest uv; this is the one that writes uv.lock.
    steps = _steps_using("astral-sh/setup-uv@")

    assert len(steps) == 2
    for step in steps:
        assert step.get("with", {}).get("version") == "0.12.17", step["uses"]


def test_checkout_leaves_no_git_credentials_behind() -> None:
    steps = _steps_using("actions/checkout@")

    assert len(steps) >= 7
    for step in steps:
        assert step.get("with", {}).get("persist-credentials") is False


def test_no_job_widens_the_read_only_permissions() -> None:
    # The workflow level grants read only; a job key could raise it for one job unnoticed.
    for workflow, name, spec in _workflow_jobs():
        assert "permissions" not in spec, f"{workflow}: {name}"


def test_lint_and_test_runs_every_check_it_claims() -> None:
    # Dropping a step must turn a test red, not leave CI green with less checked.
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    steps = ci["jobs"]["lint-and-test"]["steps"]
    runs = [str(step["run"]).strip() for step in steps if "run" in step]

    # A step switched off or allowed to fail still passes the command checks below, so none may
    # carry these keys.
    for step in steps:
        for key in ("if", "continue-on-error"):
            assert key not in step, f"{key} on a lint-and-test step: {step}"

    for command in (
        "uv sync --locked --group dev",
        "uv run ruff check . && uv run ruff format --check .",
        "uv run mypy",
        "uv run sqlfluff lint oltp/migrations",
        "uv run sqlfluff lint models macros tests",
        "make dbt-parse",
        "uv run pytest tests/unit -q",
    ):
        assert command in runs, command
    for command in (
        "for script in $(git ls-files '*.sh'); do bash -n \"$script\" || exit 1; done",
        "uv run shellcheck -x -S warning $(git ls-files '*.sh')",
        "uv run yamllint -c .yamllint docker observability airflow .github",
    ):
        assert command in runs, command
    compose = [step for step in steps if step.get("name") == "compose config"]
    assert len(compose) == 1
    assert str(compose[0].get("run", "")).strip() == (
        "cp .env.example .env && docker compose --env-file .env -f docker/compose.yaml"
        " --profile '*' config -q"
    )
    assert any(str(step.get("uses", "")).startswith("gitleaks/gitleaks-action@") for step in steps)

    # A test file that needs the throwaway Postgres runs in a step that fails on a skip.
    dsn = "RECONCILE_TEST" + "_DSN"
    needing = [
        path.name
        for path in sorted((REPO / "tests" / "unit").glob("test_*.py"))
        if path != Path(__file__).resolve() and dsn in path.read_text()
    ]
    assert needing
    for name in needing:
        covering = [s for s in steps if name in s.get("run", "")]
        assert covering, f"{name} is not run by lint-and-test"
        for step in covering:
            assert step.get("env", {}).get("FAIL_ON_SKIP") == "1", name
