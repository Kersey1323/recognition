CONTAINER_NAME=recognition-service

docker exec -u 0 "${CONTAINER_NAME}" sh -ec '
echo "[1/3] 当前证书颁发者"
curl -vkI https://sgo.csrcqsf.com 2>&1 \
  | grep -E "subject:|issuer:" || true

echo "[2/3] 更新容器 CA 证书库"
apt-get update
apt-get install --reinstall -y --no-install-recommends ca-certificates
update-ca-certificates

echo "[3/3] 验证 HTTPS"
curl -I --max-time 15 https://sgo.csrcqsf.com
'

docker restart "${CONTAINER_NAME}"

echo "Recognition 容器已重启，CA 修复完成"
