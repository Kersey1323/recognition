#!/usr/bin/env bash
set -euo pipefail

IMAGE_REF="${1:?image reference is required}"
REPO_URL="${GITOPS_REPO_URL:-}"
BRANCH="${GITOPS_BRANCH:-${CI_DEFAULT_BRANCH:-master}}"
CLONE_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${CLONE_DIR}"
}
trap cleanup EXIT

if [[ -z "${REPO_URL}" ]]; then
  echo "GITOPS_REPO_URL is required. This project now uses a dedicated GitOps repository." >&2
  exit 1
fi

while IFS='=' read -r key value; do
  export "${key}=${value}"
done < <(bash "$(dirname "$0")/extract_runtime_metadata.sh")

APP_NAME="${APP_NAME:-${GITOPS_APP_NAME:-${CI_PROJECT_NAME:-recognition}}}"
TARGET_FILE="${GITOPS_TARGET_FILE:-apps/${APP_NAME}/app.yaml}"

build_auth_repo_url() {
  python3 - "$1" "$2" "$3" <<'PY'
from urllib.parse import quote, urlsplit, urlunsplit
import sys

repo_url, username, password = sys.argv[1:4]
parts = urlsplit(repo_url)
if not parts.scheme or not parts.netloc:
    print(repo_url)
    raise SystemExit

netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parts.hostname or ''}"
if parts.port:
    netloc = f"{netloc}:{parts.port}"
print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
}

if [[ -n "${GITOPS_PUSH_USERNAME:-}" && -n "${GITOPS_PUSH_PASSWORD:-}" ]]; then
  AUTH_REPO_URL="$(build_auth_repo_url "$REPO_URL" "$GITOPS_PUSH_USERNAME" "$GITOPS_PUSH_PASSWORD")"
else
  echo "Set GITOPS_PUSH_USERNAME and GITOPS_PUSH_PASSWORD in GitLab CI/CD variables." >&2
  exit 1
fi

git clone "$AUTH_REPO_URL" "${CLONE_DIR}/repo"
git -C "${CLONE_DIR}/repo" checkout -B "$BRANCH" "origin/$BRANCH"

if [[ ! -f "${CLONE_DIR}/repo/${TARGET_FILE}" ]]; then
  echo "Target app descriptor not found: ${TARGET_FILE}" >&2
  exit 1
fi

python3 "$(dirname "$0")/update_gitops_app_yaml.py" \
  "$IMAGE_REF" \
  "${CLONE_DIR}/repo/${TARGET_FILE}"

if git -C "${CLONE_DIR}/repo" diff --quiet -- "${TARGET_FILE}"; then
  echo "App descriptor already references ${IMAGE_REF}"
  exit 0
fi

git -C "${CLONE_DIR}/repo" config user.name "${GITOPS_COMMIT_NAME:-gitlab-ci}"
git -C "${CLONE_DIR}/repo" config user.email "${GITOPS_COMMIT_EMAIL:-gitlab-ci@local.lab}"
git -C "${CLONE_DIR}/repo" add "${TARGET_FILE}"
git -C "${CLONE_DIR}/repo" commit -m "ci: update ${APP_NAME} descriptor to ${CI_COMMIT_SHORT_SHA} [skip ci]"
git -C "${CLONE_DIR}/repo" push "$AUTH_REPO_URL" "HEAD:${BRANCH}"
