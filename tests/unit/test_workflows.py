import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]

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


def test_third_party_actions_have_a_version_tag() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        for line in workflow.read_text().splitlines():
            match = re.search(r"uses:\s*((?:docker|hadolint)/[\w.-]+)@(\S+)", line)
            if match:
                assert re.fullmatch(r"v\d+(\.\d+)*", match.group(2)), line


def test_workflows_use_no_secret_but_the_github_token() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        for name in re.findall(r"secrets\.(\w+)", workflow.read_text()):
            assert name == "GITHUB_TOKEN", f"{workflow.name}: secrets.{name}"


def test_smoke_runs_on_demand_and_weekly_and_checks_verify_ok() -> None:
    # W6-D2: the schedule came back after the first green run (2026-10-29, ADR-026).
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
