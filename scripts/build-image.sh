#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/build-image.sh [image-ref]

Build the runtime image for local developer use.

Environment variables:
  DOCKERFILE   Dockerfile path to use (default: Dockerfile)
  TARGET       Docker build target (default: runtime)
  PLATFORM     Optional single platform, for example linux/arm64
  LOAD_IMAGE   Set to 0 to skip --load (default: 1)
  CONTEXT      Build context (default: .)
EOF
}

if [[ "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

image_ref="${1:-${IMAGE_REF:-janky-thermostat:dev}}"
dockerfile="${DOCKERFILE:-Dockerfile}"
target="${TARGET:-runtime}"
platform="${PLATFORM:-}"
load_image="${LOAD_IMAGE:-1}"
context="${CONTEXT:-.}"

if docker buildx version >/dev/null 2>&1; then
    docker_build_cmd=(docker buildx build)
elif command -v docker-buildx >/dev/null 2>&1; then
    docker_build_cmd=(docker-buildx build)
else
    docker_build_cmd=()
fi

if [[ -n "${platform}" && "${platform}" == *,* && "${load_image}" != "0" ]]; then
    echo "PLATFORM must be a single value when LOAD_IMAGE is enabled" >&2
    exit 1
fi

if [[ ${#docker_build_cmd[@]} -gt 0 ]]; then
    cmd=(
        "${docker_build_cmd[@]}"
        --file "${dockerfile}"
        --target "${target}"
        --tag "${image_ref}"
    )

    if [[ -n "${platform}" ]]; then
        cmd+=(--platform "${platform}")
    fi

    if [[ "${load_image}" != "0" ]]; then
        cmd+=(--load)
    fi
else
    if [[ "${load_image}" == "0" ]]; then
        echo "LOAD_IMAGE=0 requires docker buildx" >&2
        exit 1
    fi

    cmd=(
        docker build
        --file "${dockerfile}"
        --target "${target}"
        --tag "${image_ref}"
    )

    if [[ -n "${platform}" ]]; then
        cmd+=(--platform "${platform}")
    fi
fi

cmd+=("${context}")

echo "Building ${image_ref}"
"${cmd[@]}"
