#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-recognition:cpu}"
CONTAINER_NAME="${CONTAINER_NAME:-recognition-service-cpu}"
ENV_FILE="${ENV_FILE:-.env.cpu}"

HOST_MODEL_DIR="${HOST_MODEL_DIR:-/data/recognition/models}"
HOST_LOG_DIR="${HOST_LOG_DIR:-/data/recognition/logs}"
HOST_TEMP_DIR="${HOST_TEMP_DIR:-/data/recognition/temp}"
HOST_STATE_DIR="${HOST_STATE_DIR:-/data/recognition/state}"

mkdir -p "${HOST_MODEL_DIR}" "${HOST_LOG_DIR}" "${HOST_TEMP_DIR}" "${HOST_STATE_DIR}/vector_db" "${HOST_STATE_DIR}/reconstruction"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true


docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network host \
  --ipc host \
  --env-file "${ENV_FILE}" \
  -v "${HOST_MODEL_DIR}:/models" \
  -v "${HOST_LOG_DIR}:/app/logs" \
  -v "${HOST_TEMP_DIR}:/app/temp" \
  -v "${HOST_STATE_DIR}:/app/state" \
  "${IMAGE_NAME}"
