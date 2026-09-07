#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  printf '环境变量文件不存在: %s\n' "${ENV_FILE}" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo '缺少 curl，无法请求 SGO 登录接口' >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo '缺少 jq，无法构造请求和解析 Token' >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required_vars=(
  SGO_API_URL
  SGO_TENANT_ID
  SGO_USERNAME
  SGO_PASSWORD
  SGO_ENCRYPTION
)

for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    printf '缺少环境变量: %s\n' "${name}" >&2
    exit 1
  fi
done

# 避免配置末尾斜杠后再拼接路径，导致 SGO 返回 301。
api_url="${SGO_API_URL%/}"
auth_url="${api_url}/uc/sfsso/authByAccount?tenantId=${SGO_TENANT_ID}"
payload=$(jq -nc \
  --arg username "${SGO_USERNAME}" \
  --arg password "${SGO_PASSWORD}" \
  --arg encryption "${SGO_ENCRYPTION}" \
  '{username: $username, password: $password, encryption: $encryption}')

response=$(curl -sS \
  --connect-timeout 5 \
  --max-time 15 \
  -w $'\n%{http_code}' \
  -X POST \
  "${auth_url}" \
  -H 'Content-Type: application/json' \
  --data "${payload}")
http_status="${response##*$'\n'}"
response_body="${response%$'\n'*}"

if [[ ! "${http_status}" =~ ^2[0-9][0-9]$ ]]; then
  printf 'SGO Token 获取失败: HTTP %s\n' "${http_status}" >&2
  exit 1
fi

token=$(printf '%s' "${response_body}" | jq -r '.token // empty')
if [[ -z "${token}" ]]; then
  message=$(
    printf '%s' "${response_body}" \
      | jq -r '.message // .loginMessage // .msg // "响应中没有 Token"'
  )
  printf 'SGO Token 获取失败: %s\n' "${message}" >&2
  exit 1
fi

expiration=$(printf '%s' "${response_body}" | jq -r '.expiration // empty')
if [[ -n "${expiration}" ]]; then
  printf 'SGO Token 获取成功，有效期字段: %s 秒\n' "${expiration}" >&2
else
  echo 'SGO Token 获取成功' >&2
fi

printf '%s\n' "${token}"
