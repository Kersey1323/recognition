#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-recognition-service:v1}"
CONTAINER_NAME="${CONTAINER_NAME:-recognition-service}"
ENV_FILE="${ENV_FILE:-.env.deployment}"

HOST_LOG_DIR="${HOST_LOG_DIR:-/data/recognition/logs}"
HOST_TEMP_DIR="${HOST_TEMP_DIR:-/data/recognition/temp}"
HOST_STATE_DIR="${HOST_STATE_DIR:-/data/recognition/state}"

mkdir -p \
  "${HOST_LOG_DIR}" \
  "${HOST_TEMP_DIR}" \
  "${HOST_STATE_DIR}/vector_db" \
  "${HOST_STATE_DIR}/reconstruction"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network host \
  --ipc host \
  --env-file "${ENV_FILE}" \
  -v "${HOST_LOG_DIR}:/app/logs" \
  -v "${HOST_TEMP_DIR}:/app/temp" \
  -v "${HOST_STATE_DIR}:/app/state" \
  "${IMAGE_NAME}"
