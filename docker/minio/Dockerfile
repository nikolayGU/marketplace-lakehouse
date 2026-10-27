# ADR-026: MinIO and mc built from the source of the last community release tags, because no
# registry serves the images any more. Flags are those of each tag's Makefile (CGO_ENABLED=0,
# -tags kqueue, -trimpath). The release is set by explicit -ldflags: upstream gen-ldflags.go reads
# it from git history and calls it DEVELOPMENT.<date> unless MINIO_RELEASE is set.
#
# A host short of memory: --build-arg GOFLAGS=-p=2 limits the parallel compiles of MinIO.

FROM golang:1.24.6-bookworm@sha256:ab1d1823abb55a9504d2e3e003b75b36dbeb1cbcc4c92593d85a84ee46becc6c AS go
WORKDIR /src

FROM go AS minio-build
ARG GOFLAGS
ARG MINIO_TAG=RELEASE.2025-09-07T16-13-09Z
ARG MINIO_COMMIT=07c3a429bfed433e49018cb0f78a52145d4bedeb
# A tag can be moved, a commit cannot: the build stops if the tag is no longer this commit.
RUN git clone --quiet --depth 1 --branch "$MINIO_TAG" https://github.com/minio/minio.git . \
 && head="$(git rev-parse HEAD)" \
 && if [ "$head" != "$MINIO_COMMIT" ]; then echo "tag $MINIO_TAG is $head, not $MINIO_COMMIT" >&2; exit 1; fi
# Version is RFC3339 (cmd/update.go parses it); the tag spells the time with hyphens:
# 2025-09-07T16-13-09Z becomes 2025-09-07T16:13:09Z.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    stamp="${MINIO_TAG#RELEASE.}" \
 && time="${stamp#*T}" \
 && minutes="${time#*-}" \
 && version="${stamp%%T*}T${time%%-*}:${minutes%%-*}:${minutes#*-}" \
 && CGO_ENABLED=0 go build -tags kqueue -trimpath -o /out/minio \
      -ldflags "-s -w \
        -X github.com/minio/minio/cmd.Version=${version} \
        -X github.com/minio/minio/cmd.CopyrightYear=${stamp%%-*} \
        -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_TAG} \
        -X github.com/minio/minio/cmd.CommitID=${MINIO_COMMIT} \
        -X github.com/minio/minio/cmd.ShortCommitID=$(printf %.12s "$MINIO_COMMIT")" \
      .

FROM go AS mc-build
ARG GOFLAGS
ARG MC_TAG=RELEASE.2025-08-13T08-35-41Z
ARG MC_COMMIT=7394ce0dd2a80935aded936b09fa12cbb3cb8096
RUN git clone --quiet --depth 1 --branch "$MC_TAG" https://github.com/minio/mc.git . \
 && head="$(git rev-parse HEAD)" \
 && if [ "$head" != "$MC_COMMIT" ]; then echo "tag $MC_TAG is $head, not $MC_COMMIT" >&2; exit 1; fi
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    stamp="${MC_TAG#RELEASE.}" \
 && time="${stamp#*T}" \
 && minutes="${time#*-}" \
 && version="${stamp%%T*}T${time%%-*}:${minutes%%-*}:${minutes#*-}" \
 && CGO_ENABLED=0 go build -tags kqueue -trimpath -o /out/mc \
      -ldflags "-s -w \
        -X github.com/minio/mc/cmd.Version=${version} \
        -X github.com/minio/mc/cmd.CopyrightYear=${stamp%%-*} \
        -X github.com/minio/mc/cmd.ReleaseTag=${MC_TAG} \
        -X github.com/minio/mc/cmd.CommitID=${MC_COMMIT} \
        -X github.com/minio/mc/cmd.ShortCommitID=$(printf %.12s "$MC_COMMIT")" \
      .

FROM alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f AS runtime

FROM runtime AS minio
COPY --from=minio-build /out/minio /usr/bin/minio
COPY --from=minio-build /src/LICENSE /src/CREDITS /licenses/
ENV MINIO_CONFIG_ENV_FILE=config.env
EXPOSE 9000
VOLUME ["/data"]
ENTRYPOINT ["minio"]
CMD ["server", "/data"]

FROM runtime AS mc
COPY --from=mc-build /out/mc /usr/bin/mc
COPY --from=mc-build /src/LICENSE /src/CREDITS /licenses/
ENTRYPOINT ["mc"]
