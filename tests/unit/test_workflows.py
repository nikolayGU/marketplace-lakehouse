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
    text = (WORKFLOWS / "smoke.yml").read_text()
    smoke = yaml.safe_load(text)
    triggers = smoke[True]  # PyYAML reads the key `on` as True

    assert set(triggers) == {"workflow_dispatch", "schedule"}
    assert "REPLAY_DATA=sample" in text
    assert "make verify" in text
    assert "grep -qx 'verify ok'" in text
    assert smoke["permissions"] == {"contents": "read"}
