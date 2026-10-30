"""SEC-09: an image or an action is named by its content, not by a tag its publisher can move."""

import re
import shlex
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "docker" / "compose.yaml"
MAKEFILE = REPO / "Makefile"
WORKFLOWS = REPO / ".github" / "workflows"

DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"[0-9a-f]{40}")
EXACT_VERSION = re.compile(r"v\d+\.\d+\.\d+\b")

# image reference -> why it may stay without a digest. Empty on purpose: an entry needs a reason
# a reviewer can disagree with, and one that no file uses any more fails the test below.
UNPINNED: dict[str, str] = {}

# Compose images that `docker compose build` makes from a Dockerfile of this repo: they carry no
# digest, but must never be pulled (see test_every_lakehouse_image_is_never_pulled).
LOCAL_NAMESPACE = "lakehouse/"


def _services() -> dict[str, Any]:
    compose: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    services: dict[str, Any] = compose["services"]
    return services


def _dockerfiles() -> list[Path]:
    return sorted(
        p
        for p in REPO.rglob("Dockerfile*")
        if ".venv" not in p.parts and "node_modules" not in p.parts
    )


def _instructions(path: Path) -> list[str]:
    # Continuation lines joined, comments dropped: a hadolint reason may name an image too.
    lines = path.read_text().replace("\\\n", " ").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _external_bases(path: Path) -> list[str]:
    """The images a Dockerfile starts a stage from, minus the stages it built itself."""
    froms = re.findall(
        r"^FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?$",
        "\n".join(_instructions(path)),
        re.M | re.I,
    )
    stages = {alias.lower() for _, alias in froms if alias}
    return [image for image, _ in froms if image.lower() not in stages]


def _images_taken_from(path: Path) -> list[str]:
    """Images a Dockerfile copies files from, or mounts, other than its own stages."""
    sources: list[str] = []
    for line in _instructions(path):
        copy = re.match(r"COPY\s+(?:--\S+\s+)*?--from=(\S+)", line, re.I)
        if copy:
            sources.append(copy.group(1))
        if re.match(r"RUN\s", line, re.I):
            for mount in re.findall(r"--mount=(\S+)", line):
                sources += [o.removeprefix("from=") for o in mount.split(",") if o[:5] == "from="]
    # A bare name is a stage or a named build context; only `registry/name:tag` pulls an image.
    return [source for source in sources if "/" in source or ":" in source]


def _unpinned(references: list[str]) -> list[str]:
    return [r for r in references if not DIGEST.search(r) and r not in UNPINNED]


def test_every_compose_image_is_pinned_by_digest() -> None:
    images = {
        name: spec["image"]
        for name, spec in _services().items()
        if "image" in spec and not spec["image"].startswith(LOCAL_NAMESPACE)
    }

    assert images
    bad = {name: image for name, image in images.items() if _unpinned([image])}
    assert not bad, bad


def test_compose_builds_every_image_it_does_not_pin() -> None:
    # The exemption above is only sound while a `lakehouse/` image comes from a build here.
    services = _services()
    built = {spec["image"] for spec in services.values() if "build" in spec and "image" in spec}
    used = {
        spec["image"]
        for spec in services.values()
        if spec.get("image", "").startswith(LOCAL_NAMESPACE)
    }

    assert used
    assert used <= built, used - built


def test_every_lakehouse_image_is_never_pulled() -> None:
    # ADR-026: `lakehouse` on Docker Hub is somebody else's namespace, and compose asks the
    # registry for an image that is missing locally when the command has no --build (a plain
    # `compose up`, `make lakekeeper-bootstrap`). The build is the only way to get one.
    local = {
        name: spec.get("pull_policy")
        for name, spec in _services().items()
        if spec.get("image", "").startswith(LOCAL_NAMESPACE)
    }

    assert local
    assert {n: p for n, p in local.items() if p != "never"} == {}


def test_compose_build_contexts_are_not_images_by_tag() -> None:
    contexts = [
        value
        for spec in _services().values()
        for value in (spec.get("build", {}).get("additional_contexts") or {}).values()
        if str(value).startswith("docker-image://")
    ]

    assert not _unpinned(contexts)


def test_every_dockerfile_base_is_pinned_by_digest() -> None:
    found = {path: _external_bases(path) for path in _dockerfiles()}

    assert found
    assert all(found.values()), [str(p.relative_to(REPO)) for p, b in found.items() if not b]
    bad = {str(p.relative_to(REPO)): _unpinned(b) for p, b in found.items() if _unpinned(b)}
    assert not bad, bad


def test_no_dockerfile_takes_files_from_an_image_by_tag() -> None:
    bad = {str(p.relative_to(REPO)): _images_taken_from(p) for p in _dockerfiles()}

    assert not {p: images for p, images in bad.items() if _unpinned(images)}


def test_every_exception_is_used_and_has_a_reason() -> None:
    referenced = {
        reference
        for path in _dockerfiles()
        for reference in (*_external_bases(path), *_images_taken_from(path))
    } | {spec.get("image") for spec in _services().values()}

    for reference, reason in UNPINNED.items():
        assert reason.strip(), reference
        assert reference in referenced, f"{reference} is exempt but no file uses it"


def _pip_arguments(path: Path) -> list[list[str]]:
    # Every `pip install ...` up to the next shell operator, split like the shell would.
    text = "\n".join(_instructions(path))
    return [shlex.split(m) for m in re.findall(r"\bpip3?\s+install\s+([^&;|\n]+)", text)]


def test_every_pip_package_in_a_dockerfile_is_pinned_by_version() -> None:
    # A bare name takes whatever the index (or the constraints file of the base image) offers
    # on the day of the build.
    installs = [(p, args) for p in _dockerfiles() for args in _pip_arguments(p)]
    options_with_value = {"--constraint", "-c", "--requirement", "-r", "--index-url", "-i"}
    unpinned: list[str] = []
    for path, args in installs:
        skip = False
        for token in args:
            if skip:
                skip = False
            elif token in options_with_value:
                skip = True
            elif not token.startswith("-") and not re.fullmatch(
                r"[A-Za-z0-9_.-]+(\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.!+-]+", token
            ):
                unpinned.append(f"{path.relative_to(REPO)}: {token}")

    assert installs
    assert not unpinned, unpinned


def _actions() -> list[tuple[str, str, str | None]]:
    """(workflow file, `uses:` value, version comment) of every step that uses an action."""
    found: list[tuple[str, str, str | None]] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for line in workflow.read_text().splitlines():
            match = re.match(r"^\s*(?:-\s+)?uses:\s*(\S+)(?:\s+#\s*(.*\S))?\s*$", line)
            if match and not match.group(1).startswith("./"):
                found.append((workflow.name, match.group(1), match.group(2)))
    return found


def test_every_action_is_pinned_to_a_commit_with_its_version_in_a_comment() -> None:
    actions = _actions()

    assert len(actions) >= 10
    for workflow, uses, comment in actions:
        name, _, ref = uses.partition("@")
        assert re.fullmatch(r"[\w.-]+/[\w.-]+(/[\w./-]+)?", name), f"{workflow}: {uses}"
        assert COMMIT.fullmatch(ref), f"{workflow}: {uses} is not a commit SHA"
        assert comment and EXACT_VERSION.match(comment), f"{workflow}: {uses} has no version"


def test_one_action_has_one_commit_in_every_workflow() -> None:
    # Two SHAs for one action would mean one workflow was left behind on an upgrade.
    pins: dict[str, set[tuple[str, str | None]]] = {}
    for _, uses, comment in _actions():
        name, _, ref = uses.partition("@")
        pins.setdefault(name, set()).add((ref, comment))

    assert pins
    assert {name: p for name, p in pins.items() if len(p) > 1} == {}


def test_promtool_runs_from_the_prometheus_image_compose_runs() -> None:
    # make alerts-test must try the rules with the binary that will load them, by the same digest.
    pinned = _services()["prometheus"]["image"]
    text = MAKEFILE.read_text()

    variable = re.search(r"^PROMETHEUS_IMAGE\s*[:?]?=\s*(\S+)\s*$", text, re.M)
    assert variable, "Makefile does not set PROMETHEUS_IMAGE"
    assert variable.group(1) == pinned
    promtool = re.findall(r"^\t.*\bpromtool\b.*$", text, re.M)
    assert len(promtool) == 2
    assert all("$(PROMETHEUS_IMAGE)" in line for line in promtool)
    # No second copy of the name, tag or digest elsewhere in the Makefile.
    assert "prom/prometheus" not in text.replace(pinned, "")
