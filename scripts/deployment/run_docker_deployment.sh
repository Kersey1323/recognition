#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-recognition:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-recognition-service}"
ENV_FILE="${ENV_FILE:-.env.deployment}"

HOST_LOG_DIR="${HOST_LOG_DIR:-/data/recognition/logs}"
HOST_TEMP_DIR="${HOST_TEMP_DIR:-/data/recognition/temp}"
HOST_STATE_DIR="${HOST_STATE_DIR:-/data/recognition/state}"
HOST_SOURCE_DIR="${HOST_SOURCE_DIR:-/data/recognition-service/csrcqsf}"

if ! [[ -f "${HOST_SOURCE_DIR}/__init__.py" ]]; then
  printf '业务源码目录无效，缺少 %s\n' "${HOST_SOURCE_DIR}/__init__.py" >&2
  exit 1
fi

mkdir -p "${HOST_LOG_DIR}" "${HOST_TEMP_DIR}" "${HOST_STATE_DIR}/vector_db" "${HOST_STATE_DIR}/reconstruction"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network host \
  --ipc host \
  --env-file "${ENV_FILE}" \
  -e "RECOGNITION_MAIN_SOURCE_HOST_PATH=${HOST_SOURCE_DIR}" \
  -v "${HOST_SOURCE_DIR}:/app/csrcqsf:ro" \
  -v "${HOST_LOG_DIR}:/app/logs" \
  -v "${HOST_TEMP_DIR}:/app/temp" \
  -v "${HOST_STATE_DIR}:/app/state" \
  "${IMAGE_NAME}"
