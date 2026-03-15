#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/publish-image.sh <image-repo> [tag]

Build and push a multi-arch runtime image.

Environment variables:
  DOCKERFILE       Dockerfile path to use (default: Dockerfile)
  TARGET           Docker build target (default: runtime)
  PLATFORMS        Target platforms (default: linux/amd64,linux/arm64)
  CONTEXT          Build context (default: .)
  PUBLISH_LATEST   Set to 1 to also push the latest tag
EOF
}

if [[ "${1:-}" == "--help" || $# -lt 1 ]]; then
    usage >&2
    exit $([[ "${1:-}" == "--help" ]] && echo 0 || echo 1)
fi

image_repo="$1"
tag="${2:-${TAG:-}}"
dockerfile="${DOCKERFILE:-Dockerfile}"
target="${TARGET:-runtime}"
platforms="${PLATFORMS:-linux/amd64,linux/arm64}"
context="${CONTEXT:-.}"

if docker buildx version >/dev/null 2>&1; then
    docker_build_cmd=(docker buildx build)
elif command -v docker-buildx >/dev/null 2>&1; then
    docker_build_cmd=(docker-buildx build)
else
    echo "docker buildx or docker-buildx is required for publishing multi-arch images" >&2
    exit 1
fi

if [[ -z "${tag}" ]]; then
    if git describe --tags --exact-match >/dev/null 2>&1; then
        tag="$(git describe --tags --exact-match)"
    else
        tag="$(git rev-parse --short HEAD)"
    fi
fi

cmd=(
    "${docker_build_cmd[@]}"
    --file "${dockerfile}"
    --target "${target}"
    --platform "${platforms}"
    --tag "${image_repo}:${tag}"
    --push
)

if [[ "${PUBLISH_LATEST:-0}" == "1" ]]; then
    cmd+=(--tag "${image_repo}:latest")
fi

cmd+=("${context}")

echo "Publishing ${image_repo}:${tag}"
"${cmd[@]}"
