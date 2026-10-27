"""ADR-026: MinIO and mc are built from the pinned source, no registry serves them any more."""

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "docker" / "minio" / "Dockerfile"
CHECK_SCRIPT = REPO / "scripts" / "check-minio-images.sh"

MINIO_TAG = "RELEASE.2025-09-07T16-13-09Z"
MC_TAG = "RELEASE.2025-08-13T08-35-41Z"


def _services() -> dict[str, Any]:
    compose: dict[str, Any] = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text())
    services: dict[str, Any] = compose["services"]
    return services


def _dockerfile() -> str:
    # Instructions only: the comments name the same flags and must not count as a build.
    lines = DOCKERFILE.read_text().replace("\\\n", " ").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def _arg(name: str) -> str:
    match = re.search(rf"^ARG {name}=(\S+)$", _dockerfile(), re.M)
    assert match, f"ARG {name} is not set in {DOCKERFILE.name}"
    return match.group(1)


def test_minio_and_mc_are_built_from_the_dockerfile_not_pulled() -> None:
    # Putting a registry image back would bring the red smoke of 2026-10-26 back.
    services = _services()

    for name, target, image in (
        ("minio", "minio", f"lakehouse/minio:{MINIO_TAG}"),
        ("minio-init", "mc", f"lakehouse/mc:{MC_TAG}"),
    ):
        assert services[name]["build"] == {"context": "./minio", "target": target}
        assert services[name]["image"] == image


def test_the_images_are_never_pulled() -> None:
    # `lakehouse/minio` is not ours on Docker Hub: a tag published there would be pulled with
    # the S3 root keys in its environment on a host that has no image yet.
    services = _services()

    assert services["minio"]["pull_policy"] == "never"
    assert services["minio-init"]["pull_policy"] == "never"


def test_no_service_pulls_a_minio_image() -> None:
    images = [spec["image"] for spec in _services().values() if "image" in spec]

    assert not [i for i in images if i.startswith(("quay.io/minio/", "minio/"))]


def test_every_base_image_is_pinned_by_digest() -> None:
    # A stage built FROM an earlier stage is not a base image.
    froms = re.findall(r"^FROM (\S+)(?: AS (\S+))?$", _dockerfile(), re.M)
    stages = {alias for _, alias in froms if alias}

    bases = [image for image, _ in froms if image not in stages]

    assert bases
    for image in bases:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), image


def test_the_targets_compose_asks_for_exist() -> None:
    stages = set(re.findall(r"^FROM \S+ AS (\S+)$", _dockerfile(), re.M))

    assert {"minio", "mc"} <= stages


def test_the_source_is_a_commit_and_the_clone_is_checked_against_it() -> None:
    text = _dockerfile()

    for name in ("MINIO_COMMIT", "MC_COMMIT"):
        assert re.fullmatch(r"[0-9a-f]{40}", _arg(name)), name
    # A tag can be moved; the commit cannot.
    assert text.count("git clone") == 2
    for name in ("MINIO_COMMIT", "MC_COMMIT"):
        assert f'[ "$head" != "${name}" ]' in text, name
    assert text.count('head="$(git rev-parse HEAD)"') == 2
    # The comparison must stop the build, not only print.
    assert text.count("exit 1; fi") == 2


def test_the_tags_of_the_dockerfile_and_of_compose_agree() -> None:
    services = _services()

    assert _arg("MINIO_TAG") == services["minio"]["image"].split(":")[1]
    assert _arg("MC_TAG") == services["minio-init"]["image"].split(":")[1]


def test_the_release_is_set_by_explicit_ldflags() -> None:
    # `make build` upstream prints DEVELOPMENT.<date> and takes the date from git history.
    text = _dockerfile()

    for module in ("minio/minio", "minio/mc"):
        for symbol in ("Version", "ReleaseTag", "CommitID", "ShortCommitID", "CopyrightYear"):
            assert f"-X github.com/{module}/cmd.{symbol}=" in text, f"{module} {symbol}"
    # One build per tool, each with the flags of its Makefile.
    for flag in ("CGO_ENABLED=0", "-tags kqueue", "-trimpath", "cmd.Version=${version}"):
        assert text.count(flag) == 2, flag


def test_the_minio_healthcheck_uses_what_the_runtime_has() -> None:
    # The runtime is alpine without curl: a curl healthcheck would keep minio "starting" forever.
    test = _services()["minio"]["healthcheck"]["test"]

    assert "curl" not in " ".join(test)
    assert "wget -q --spider http://localhost:9000/minio/health/live" in " ".join(test)


def test_the_image_check_runs_the_compose_healthcheck_command() -> None:
    command = _services()["minio"]["healthcheck"]["test"][1]

    assert command in CHECK_SCRIPT.read_text()


def test_the_image_check_reads_what_the_flags_cannot_fake() -> None:
    # --version prints the release tag from a flag; the Go build info and the server report do not.
    text = CHECK_SCRIPT.read_text()

    assert "vcs.revision=" in text
    assert "vcs.modified=false" in text
    assert text.count('built_from "$') == 2
    assert "mc admin info" in text


def test_the_image_check_refuses_without_both_images() -> None:
    result = subprocess.run(
        ["bash", str(CHECK_SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
