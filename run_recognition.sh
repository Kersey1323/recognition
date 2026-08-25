#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="${IMAGE_NAME:-recognition-service:v1.7}"
CONTAINER_NAME="${CONTAINER_NAME:-recognition-service}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.deployment}"
IMAGE_TAR_PATH="${1:-}"

usage() {
  cat <<'EOF'
Usage:
  ./run_recognition.sh <path-to-image-tar>

Optional environment variables:
  IMAGE_NAME        Docker image tag to run, default: recognition-service:v1.7
  CONTAINER_NAME    Container name, default: recognition-service
  ENV_FILE          Env file path, default: ./.env.deployment
  HOST_SOURCE_DIR   Host csrcqsf directory, default: /data/recognition-service/csrcqsf
  HOST_LOG_DIR      Host log directory, default: /data/recognition/logs
  HOST_TEMP_DIR     Host temp directory, default: /data/recognition/temp
  HOST_STATE_DIR    Host state directory, default: /data/recognition/state

The HOST_* values can also be configured in .env.deployment.
EOF
}

read_env_value() {
  local key="$1"
  awk -v key="${key}" '
    index($0, key "=") == 1 {
      sub(/^[^=]*=/, "")
      sub(/\r$/, "")
      print
      exit
    }
  ' "${ENV_FILE}"
}

if [[ -z "${IMAGE_TAR_PATH}" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${IMAGE_TAR_PATH}" ]]; then
  echo "Image tar not found: ${IMAGE_TAR_PATH}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Env file not found: ${ENV_FILE}" >&2
  exit 1
fi

HOST_SOURCE_DIR="${HOST_SOURCE_DIR:-$(read_env_value HOST_SOURCE_DIR)}"
HOST_LOG_DIR="${HOST_LOG_DIR:-$(read_env_value HOST_LOG_DIR)}"
HOST_TEMP_DIR="${HOST_TEMP_DIR:-$(read_env_value HOST_TEMP_DIR)}"
HOST_STATE_DIR="${HOST_STATE_DIR:-$(read_env_value HOST_STATE_DIR)}"

HOST_SOURCE_DIR="${HOST_SOURCE_DIR:-/data/recognition-service/csrcqsf}"
HOST_LOG_DIR="${HOST_LOG_DIR:-/data/recognition/logs}"
HOST_TEMP_DIR="${HOST_TEMP_DIR:-/data/recognition/temp}"
HOST_STATE_DIR="${HOST_STATE_DIR:-/data/recognition/state}"

if [[ ! -f "${HOST_SOURCE_DIR}/__init__.py" ]] || [[ ! -f "${HOST_SOURCE_DIR}/__main__.py" ]]; then
  echo "Recognition source directory is incomplete: ${HOST_SOURCE_DIR}" >&2
  echo "Expected files: __init__.py and __main__.py" >&2
  exit 1
fi

echo "[1/4] Loading image from: ${IMAGE_TAR_PATH}"
docker load -i "${IMAGE_TAR_PATH}"

if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "Docker image not found after loading: ${IMAGE_NAME}" >&2
  exit 1
fi

echo "[2/4] Preparing host directories"
mkdir -p \
  "${HOST_LOG_DIR}" \
  "${HOST_TEMP_DIR}" \
  "${HOST_STATE_DIR}/vector_db" \
  "${HOST_STATE_DIR}/reconstruction"

echo "[3/4] Replacing container: ${CONTAINER_NAME}"
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

echo "[4/4] Starting container from image: ${IMAGE_NAME}"
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

echo "Container started. Verify with:"
echo "  curl -fsS http://127.0.0.1:65432/health"
echo "  tail -n 1 ${HOST_LOG_DIR}/source_mount.log"
