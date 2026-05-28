#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-recognition-reconstruction-server:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-recognition-reconstruction-server}"
ENV_FILE="${ENV_FILE:-docker/reconstruction-server/.env.example}"
HOST_LOG_DIR="${HOST_LOG_DIR:-/data/reconstruction-server/logs}"
HOST_OUTPUT_DIR="${HOST_OUTPUT_DIR:-/data/reconstruction-server/output}"
HOST_DATA_DIR="${HOST_DATA_DIR:-/data/reconstruction-server/data}"

mkdir -p "${HOST_LOG_DIR}" "${HOST_OUTPUT_DIR}" "${HOST_DATA_DIR}"
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network host \
  --ipc host \
  --env-file "${ENV_FILE}" \
  -v "${HOST_LOG_DIR}:/app/csrcqsf/biz/railwayparts/reconstruction_server/logs" \
  -v "${HOST_OUTPUT_DIR}:/app/csrcqsf/biz/railwayparts/reconstruction_server/output" \
  -v "${HOST_DATA_DIR}:/app/csrcqsf/biz/railwayparts/reconstruction_server/data" \
  "${IMAGE_NAME}"
