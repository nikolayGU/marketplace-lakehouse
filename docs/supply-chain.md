# Supply chain

How the images, actions and the MinIO build are pinned and how to change them.

## Pinned images and actions

Every image compose takes from a registry and every `FROM` is `name:tag@sha256:<digest>` (the
index of the multi-arch image); every third-party action is `owner/repo@<commit sha> # vX.Y.Z`.
The tag is for the reader, the digest and the SHA are what runs. `make alerts-test` runs promtool
from the same Prometheus digest as compose (`PROMETHEUS_IMAGE` in the Makefile).
`tests/unit/test_pinning.py` fails on:
- a tag alone in compose, in a `FROM`, in a `COPY --from` or in a `RUN --mount ...,from=`;
- a `lakehouse/*` image no service builds, or one without `pull_policy: never`;
- a `pip install` in a Dockerfile of a bare package name or of a `==` with a wildcard;
- an action without a SHA or without its version in the comment;
- a promtool image in the Makefile that is not the one compose runs.

How it is kept:
- Changing a version: edit the tag and the digest together. Digest of an image already pulled:
  `docker image inspect --format '{{json .RepoDigests}}' <image>:<tag>`; otherwise the `Digest:`
  at the top of `docker buildx imagetools inspect <image>:<tag>`. A registry may serve another
  digest under the same tag today (`postgres:17` does), so the pinned one is the one that ran.
  For an action: `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (and `git/tags/<sha>` when the
  tag is annotated) gives the commit; the comment names the exact tag that points at it. Nothing
  moves a digest or a SHA by itself (no Dependabot, no Renovate): updates are by hand.
- `airflow/Dockerfile` also names `pydantic-settings`, `trino` and `psycopg`: the versions the
  constraints file of the base image carries. Another base image means other numbers there; pip
  stops the build if they disagree.
- `lakehouse/*` images carry no digest: compose builds them (`--build`), and `pull_policy: never`
  keeps compose from asking a registry for one that is missing, because `lakehouse` on Docker Hub
  is not ours (ADR-026). The `FROM` of each of them carries a digest, so a rebuild keeps its base.

## Not covered

- the jars of `streaming/Dockerfile` are checked against a `.sha1` from the same origin;
- there is no CVE scanning of the images;
- pip installs have no `--require-hashes`, and the transitive dependencies of the dbt venv float;
- `rev:` in `.pre-commit-config.yaml` is a tag;
- the DockerOperator of `silver_upsert` pulls `lakehouse/spark:dev` from a registry when the image
  is missing locally (`pull_policy` is compose's, not the operator's).

## MinIO and mc images

`docker/minio/Dockerfile` builds both from the source of the tags of ADR-004
(`RELEASE.2025-09-07T16-13-09Z`, `RELEASE.2025-08-13T08-35-41Z`): `git clone` of the tag, a check
that `HEAD` is the commit written in the `ARG`, `CGO_ENABLED=0`, explicit `-ldflags`, Go
`1.24.6-bookworm` and `alpine:3.22` pinned by digest. `docker compose` builds them (`minio` target
`minio`, `minio-init` target `mc`) as `lakehouse/minio:<tag>` and `lakehouse/mc:<tag>`.
- Check built images: `bash scripts/check-minio-images.sh lakehouse/minio:<tag> lakehouse/mc:<tag>`
  (a throwaway container, no port, the live stack is not touched).
- Changing a tag: the `ARG` pair (tag and commit, `git ls-remote <repo> 'refs/tags/<tag>^{}'`), the
  `image:` line in compose and the two constants in `tests/unit/test_minio_image.py`.
- A host short of memory: `--build-arg GOFLAGS=-p=2` (`docker compose build --build-arg
  GOFLAGS=-p=2 minio minio-init`).
- The healthcheck is `wget -q --spider` because the runtime has no `curl`; `pull_policy: never`
  keeps compose from trying Docker Hub, where `lakehouse` is somebody else's namespace.
- A compose command that creates containers (`make start`, `make up`, `compose up`) reads the
  compose file of the working tree: from the moment it names `lakehouse/minio:<tag>` it builds
  `minio` and `minio-init` (`make start` has `--build` and `minio` is a dependency of
  `spark-bronze`) and recreates them when the image id differs from the running container's. The
  data volume does not change. On a live stack that is a separate step with its own "ok".

Rollback and the cost of a cold build: [ADR-026](../DECISIONS.md#adr-026-minio-and-mc-built-from-the-pinned-source).
