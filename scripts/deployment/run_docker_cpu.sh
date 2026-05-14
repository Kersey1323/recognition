#!/usr/bin/env bash

set -euo pipefail
IMAGE_NAME="${IMAGE_NAME:-recognition:cpu}"
CONTAINER_NAME="${CONTAINER_NAME:-recognition-service-cpu}"
ENV_FILE="${ENV_FILE:-.env.cpu}"

HOST_DIR="${HOST_DIR:-/data/recognition}"

mkdir -p "${HOST_DIR}"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true


docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network host \
  --ipc host \
  --env-file "${ENV_FILE}" \
  -v "${HOST_DIR}":/app
  "${IMAGE_NAME}"
