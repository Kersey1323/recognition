# MinIO 和图片数据报告

## 问题概述

接口中涉及大量图片操作，需要确认 MinIO 存储和图片数据的可用性。

---

## MinIO 服务器状态

### 配置的 MinIO 地址
- **Endpoint**: 192.168.100.126:9000
- **Access Key**: root
- **Secret Key**: Y2iaciej@Bfr
- **状态**: ❌ 无法连接（Connection refused）

### 其他服务器检查
- **192.168.100.8**: ❌ 没有 MinIO 容器
- **192.168.100.2**: ❌ 没有 MinIO 容器

### 结论
⚠️ **MinIO 服务当前不可用**，需要：
1. 检查 192.168.100.126 服务器上的 MinIO 服务状态
2. 或者找到正确的 MinIO 服务器地址

---

## 数据库中的图片数据

### ✅ 有图片数据！

#### 1. sgo_item_image_info 表
- **记录数**: 14,398 条
- **图片来源**: SGO 系统（BASEINFO）
- **路径格式**: `bfr-ai-files/{文件ID}.jpg`

**示例数据**：
```
配件ID: 1557988408477880320
  图片1: bfr-ai-files/1725402784070635520.jpg
  图片2: bfr-ai-files/1725402791335170048.jpg
  图片3: bfr-ai-files/1725402796729044992.jpg
  图片4: bfr-ai-files/1725402809005772800.jpg
  图片5: bfr-ai-files/1725402840131702784.jpg
  来源: BASEINFO
```

#### 2. item_image 表
- **记录数**: 7 条
- **状态**: 表结构可能不完整（缺少 image_url 字段）

#### 3. 其他图片相关表
- **indexed_item_image_info**: 0 条记录（索引图片信息）
- **segmented_image_info**: 0 条记录（分割图片信息）

---

## 图片URL格式分析

### 当前格式
```
bfr-ai-files/1725402784070635520.jpg
```

### 完整URL应该是
```
http://{minio_host}:{minio_port}/bfr-ai-files/1725402784070635520.jpg
```

或者使用 MinIO 客户端访问：
```python
from minio import Minio
client = Minio(endpoint, access_key, secret_key)
url = client.presigned_get_object("bfr-ai-files", "1725402784070635520.jpg")
```

---

## 影响的接口

### 无法正常工作的接口（需要 MinIO）

1. **POST /railway/parts/create_item_image** - 上传配件图片
2. **POST /railway/parts/item_image_indexed** - 建立图片索引
3. **POST /railway/parts/image_search** - 图片相似度搜索
4. **POST /railway/parts/auto_segment** - 自动分割（需要读取图片）
5. **POST /railway/parts/reconstruct_3d** - 3D重建（需要多张图片）
6. **POST /images/ocr/front** - OCR识别（需要读取图片）
7. **POST /segment/simple** - 图像分割（需要读取图片）

### 可能可以工作的接口（使用数据库中的图片路径）

1. **POST /sgo/sgo/parts/images** - 获取SGO系统图片列表（返回路径）
2. **GET /railway/parts/segmented_images/{item_id}** - 获取分割记录（如果有）

---

## 解决方案

### 方案1：修复 MinIO 服务（推荐）

1. **检查 192.168.100.126 服务器**
```bash
ssh root@192.168.100.126
docker ps | grep minio
docker logs {minio_container_id}
```

2. **如果 MinIO 容器存在但未启动**
```bash
docker start {minio_container_id}
```

3. **如果 MinIO 容器不存在，启动新容器**
```bash
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -e "MINIO_ROOT_USER=root" \
  -e "MINIO_ROOT_PASSWORD=Y2iaciej@Bfr" \
  -v /data/minio:/data \
  minio/minio server /data --console-address ":9001"
```

### 方案2：查找其他 MinIO 实例

检查其他可能的服务器：
```bash
# 检查常见端口
for host in 192.168.100.{1..20}; do
  echo "Testing $host..."
  curl -s --connect-timeout 1 http://$host:9000 && echo "$host:9000 响应"
done
```

### 方案3：使用现有图片数据（临时方案）

如果 MinIO 暂时不可用，可以：
1. 使用数据库中已有的 14,398 条图片记录进行测试
2. 修改代码，使图片路径可以从其他来源读取
3. 暂时跳过需要上传新图片的接口

---

## 测试建议

### 1. 测试可用的接口（不需要 MinIO）

```bash
# 列出配件
curl -X POST "http://localhost:65432/railway/parts/list_items" \
  -H "Content-Type: application/json" \
  -d '{"page":1,"pageSize":5,"query":""}'

# 获取配件详情
curl -X POST "http://localhost:65432/railway/parts/get_item_details" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"1557988408477880320"}'

# 获取SGO图片列表
curl -X POST "http://localhost:65432/sgo/sgo/parts/images" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"1557988408477880320"}'

# 数据统计
curl -X POST "http://localhost:65432/railway/parts/data/statistics" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 2. 测试需要 MinIO 的接口（修复后）

```bash
# 图片搜索（需要 MinIO 可访问图片）
curl -X POST "http://localhost:65432/railway/parts/image_search" \
  -H "Content-Type: application/json" \
  -d '{"images_url":["http://minio-host:9000/bfr-ai-files/1725402784070635520.jpg"],"radius":0.8,"texts":[]}'
```

---

## 数据统计

| 项目 | 数量 |
|-----|------|
| 配件总数 | 78,740 |
| 图片记录数 | 14,398 |
| 有图片的配件 | 未统计 |
| 平均每个配件的图片数 | 未统计 |
| MinIO Bucket | bfr-ai-files |

---

## 下一步行动

### 优先级1：修复 MinIO 连接
- [ ] 检查 192.168.100.126 服务器
- [ ] 确认 MinIO 服务状态
- [ ] 测试 MinIO 连接
- [ ] 验证图片可访问性

### 优先级2：更新配置
- [ ] 如果 MinIO 在其他地址，更新 `csrcqsf/settings.py`
- [ ] 重启应用

### 优先级3：测试接口
- [ ] 测试不需要 MinIO 的接口
- [ ] MinIO 修复后测试图片相关接口
- [ ] 更新 API 文档中的图片URL示例

---

## 联系信息

如需协助，请提供：
1. 192.168.100.126 服务器的访问权限
2. MinIO 的实际部署位置
3. 图片存储的备用方案（如果有）
