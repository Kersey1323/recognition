#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CONTAINER_NAME="recognition-assets-proxy-debug"
IMAGE_NAME="nginx:1.27-alpine"
HOST_PORT="${HOST_PORT:-8080}"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name recognition-assets-proxy-debug \
  --add-host host.docker.internal:host-gateway \
  -p 8080:8080 \
  -v "${PROJECT_ROOT}/docs/deployment/nginx-assets-proxy-example.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "${PROJECT_ROOT}/tools/assets_download_debug.html:/usr/share/nginx/html/assets_download_debug.html:ro" \
  "${IMAGE_NAME}"

echo "assets proxy debug page: http://127.0.0.1:${HOST_PORT}/assets_download_debug.html"
