# 铁路配件识别系统 - API 接口文档与测试指南

## 项目概述
这是一个基于 FastAPI 的铁路配件智能识别系统，集成了图像分割、特征提取、3D重建等AI能力。共有 30+ 个接口，分为 4 个主要模块。

**服务地址**: `http://localhost:65432`

---

## 🗂️ 接口分类

### 1️⃣ Railway Parts 模块 (配件管理) - 24个接口

#### 1.1 配件基础 CRUD

**1. POST `/railway/parts/item` - 创建配件**

请求体：
```json
{
  "item_name": "测试螺栓",
  "item_code": "TEST-BOLT-001",
  "obj_url": null,
  "height": 10.5,
  "length": 20.0,
  "width": 5.0,
  "parent_item_id": null
}
```

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/item" \
  -H "Content-Type: application/json" \
  -d '{"item_name":"测试螺栓","item_code":"TEST-BOLT-001","obj_url":null,"height":10.5,"length":20,"width":5,"parent_item_id":null}'
```

---

**2. POST `/railway/parts/item_delete` - 删除配件**

请求体：
```json
{
  "item_id_list": ["1482740094400990802", "1555467253485408256"]
}
```

⚠️ 注意：请使用测试创建的配件ID，不要删除生产数据

---

**3. POST `/railway/parts/item_put` - 修改配件信息**

请求体：
```json
{
  "id": "1482740094400990802",
  "item_name": "司机室控制主机(更新)",
  "item_code": "40001178346",
  "parent_item_id": null,
  "obj_url": null,
  "height": 105.0,
  "length": 205.0,
  "width": 155.0
}
```

---

**4. POST `/railway/parts/item/size_put` - 修改3D模型尺寸描述**

请求体：
```json
{
  "item_id": "1482740094400990802",
  "item_size_desc": "长205mm×宽155mm×高105mm"
}
```

---

**5. POST `/railway/parts/list_items` - 列出配件列表（分页）**

请求体：
```json
{
  "page": 1,
  "pageSize": 20,
  "query": "司机室",
  "parent_item_id": null,
  "only_has_index": 0,
  "has_inquery_code": 0,
  "has_images": 0
}
```

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/list_items" \
  -H "Content-Type: application/json" \
  -d '{"page":1,"pageSize":10,"query":"司机室"}'
```

---

**6. POST `/railway/parts/get_item_details` - 获取配件详情**

请求体：
```json
{
  "item_id": "1482740094400990802"
}
```

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/get_item_details" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"1482740094400990802"}'
```

---

#### 1.2 配件图片管理

**7. POST `/railway/parts/create_item_image` - 为配件上传图片**

请求体：
```json
{
  "item_id": "1482740094400990802",
  "images_url": [
    "https://example.com/images/part1.jpg",
    "https://example.com/images/part2.jpg"
  ]
}
```

⚠️ 注意：图片URL需要是可访问的公网地址或MinIO地址

---

**8. POST `/railway/parts/item_image_indexed` - 建立图片索引**

说明：可以是原图或裁剪后的图片，使用 DINOv2 提取特征

请求体：
```json
{
  "item_id": "1482740094400990802",
  "images": [
    {
      "image_id": "0",
      "image_url": "https://example.com/cropped/part1.jpg"
    }
  ],
  "features": ["控制主机", "司机室"]
}
```

---

**9. POST `/railway/parts/delete_item_image_index` - 删除图片索引**

请求体：
```json
{
  "item_id": "1482740094400990802",
  "image_file_url": [
    "https://example.com/images/part1.jpg"
  ]
}
```

---

**10. GET `/railway/parts/segmented_images/{item_id}` - 获取分割记录**

测试方法：
```bash
curl "http://localhost:65432/railway/parts/segmented_images/1482740094400990802"
```

---

#### 1.3 配件特征管理

**11. POST `/railway/parts/list_item_features` - 列出配件文字特征**

请求体：
```json
{
  "item_id": "1482740094400990802"
}
```

---

**12. POST `/railway/parts/update_item_features` - 修改文字特征**

请求体：
```json
{
  "item_id": "1482740094400990802",
  "old_feature": "控制主机",
  "new_feature": "司机室控制主机"
}
```

---

**13. POST `/railway/parts/delete_item_features` - 删除文字特征**

请求体：
```json
{
  "item_id": "1482740094400990802",
  "features": ["控制主机", "司机室"]
}
```

---

#### 1.4 智能检索

**14. POST `/railway/parts/image_search` - 图片相似度搜索**

说明：上传图片，返回相似配件

请求体：
```json
{
  "images_url": [
    "https://example.com/query/unknown_part.jpg"
  ],
  "radius": 0.8,
  "texts": []
}
```

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/image_search" \
  -H "Content-Type: application/json" \
  -d '{"images_url":["https://example.com/test.jpg"],"radius":0.8,"texts":[]}'
```

---

**15. POST `/railway/parts/search/v2` - 综合检索V2（图片+文字）**

说明：支持图片和文字特征混合检索

请求体：
```json
{
  "images": ["https://example.com/part.jpg"],
  "features": ["控制主机", "司机室"],
  "lower_rate": 0.8,
  "sgo_inquery_id": null,
  "parent_item_id": "0"
}
```

---

**16. POST `/railway/parts/search/history/v2` - 检索历史列表**

请求体：
```json
{
  "page": 1,
  "pageSize": 20
}
```

---

**17. POST `/railway/parts/search/history/delete/v2` - 删除检索历史**

请求体：
```json
{
  "history_id_list": ["1", "2"]
}
```

---

#### 1.5 自动化处理

**18. POST `/railway/parts/auto_segment` - 自动分割并建立索引 (SAM + DINOv2)**

说明：自动处理配件的 BASEINFO 图片，使用 SAM 分割 + DINOv2 特征提取

请求体：
```json
{
  "item_id": "1482740094400990802",
  "rebuild": false
}
```

测试流程：
1. 先上传配件图片
2. 调用此接口自动分割
3. 查看分割结果

```bash
curl -X POST "http://localhost:65432/railway/parts/auto_segment" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"1482740094400990802","rebuild":false}'
```

---

**19. POST `/railway/parts/index_rebuild` - 重建所有索引**

说明：重建 Milvus 向量索引

请求体：无

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/index_rebuild"
```

---

#### 1.6 3D 重建

**20. POST `/railway/parts/reconstruct_3d` - 3D重建（多角度照片→OBJ）**

说明：使用 COLMAP + 3D Gaussian Splatting + SuGaR 生成 OBJ 模型

请求体：
```json
{
  "item_id": "1482740094400990802",
  "image_urls": [
    "https://example.com/360/angle_001.jpg",
    "https://example.com/360/angle_002.jpg",
    "https://example.com/360/angle_003.jpg"
  ]
}
```

⚠️ 至少需要 10 张多角度照片，建议 50-100 张

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/reconstruct_3d" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"1482740094400990802","image_urls":["url1","url2","url3"]}' 
```

---

**21. GET `/railway/parts/reconstruct_3d/progress/{task_id}` - 查询3D重建进度**

测试方法：
```bash
curl "http://localhost:65432/railway/parts/reconstruct_3d/progress/task_123456"
```

---

**22. GET `/railway/parts/reconstruct_3d/tasks` - 列出3D重建任务**

参数：`item_id`（可选）

测试方法：
```bash
curl "http://localhost:65432/railway/parts/reconstruct_3d/tasks?item_id=1482740094400990802"
```

---

#### 1.7 数据统计

**23. POST `/railway/parts/data/statistics` - 索引统计**

说明：返回配件总数、索引数、识别率等统计信息

请求体：`{}`

测试方法：
```bash
curl -X POST "http://localhost:65432/railway/parts/data/statistics" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

### 2️⃣ SGO 模块 (外部系统集成) - 4个接口

**24. POST `/sgo/sgo/parts/sync` - 同步配件基本信息**

说明：从 SGO 系统同步配件数据

请求体：`{}`

---

**25. POST `/sgo/sgo/parts/images/sync` - 同步配件照片**

请求体：
```json
{
  "items_id_list": ["1482740094400990802", "1555467253485408256"]
}
```

---

**26. POST `/sgo/sgo/parts/images` - 获取SGO系统图片**

请求体：
```json
{
  "item_id": "1482740094400990802"
}
```

---

**27. POST `/sgo/sgo/inquery/list` - 获取询码记录列表**

请求体：
```json
{
  "page": 1,
  "pageSize": 20,
  "has_indexed": 1,
  "current_status": "FINISH"
}
```

参数说明：
- `has_indexed`: 0=不限, 1=已索引, 2=未索引
- `current_status`: FINISH/CREATE/CONFIRMAUDIT/BACKAUDIT/REGING

---

### 3️⃣ Image 模块 (图像处理) - 1个接口

**28. POST `/images/ocr/front` - OCR文字识别**

说明：提取图片中的文字内容

请求体：
```json
{
  "file_url": "https://example.com/images/nameplate.jpg"
}
```

测试方法：
```bash
curl -X POST "http://localhost:65432/images/ocr/front" \
  -H "Content-Type: application/json" \
  -d '{"file_url":"https://example.com/test.jpg"}'
```

---

### 4️⃣ Docs 模块 (文档解析) - 4个接口

**29. POST `/railway/docs/file` - 上传并解析配件手册**

说明：解析 PDF 文档中的表格数据

请求体：
```json
{
  "file_name": "配件手册V1.0.pdf",
  "file_url": "https://example.com/docs/manual.pdf"
}
```

---

**30. POST `/railway/docs/files` - 列出文件列表**

请求体：
```json
{
  "page": 1,
  "pageSize": 20,
  "query": "手册"
}
```

---

**31. POST `/railway/docs/file/tables` - 列出文件的表格数据**

请求体：
```json
{
  "file_id": "1",
  "page": 1,
  "pageSize": 20,
  "query": ""
}
```

---

**32. POST `/railway/docs/file/export` - 导出Excel文件**

请求体：
```json
{
  "file_id": "1",
  "user_id": "123"
}
```

---

### 5️⃣ DeepSeek 模块 (图像分割) - 1个接口

**33. POST `/segment/simple` - 简单的图像物体提取**

说明：使用 SAM 模型提取物体 mask

请求体：
```json
{
  "file_url": "https://example.com/images/part.jpg"
}
```

响应：
```json
{
  "mask": "base64编码的mask图片"
}
```

---

## 🧪 完整测试流程

### 场景1：配件录入与检索

```bash
# 1. 创建配件
curl -X POST "http://localhost:65432/railway/parts/item" \
  -H "Content-Type: application/json" \
  -d '{"item_name":"测试螺栓","item_code":"TEST-BOLT-001","obj_url":null,"height":10,"length":20,"width":5,"parent_item_id":null}'

# 2. 获取配件列表（找到刚创建的配件ID）
curl -X POST "http://localhost:65432/railway/parts/list_items" \
  -H "Content-Type: application/json" \
  -d '{"page":1,"pageSize":10,"query":"测试螺栓"}'

# 3. 上传配件图片（使用返回的item_id）
curl -X POST "http://localhost:65432/railway/parts/create_item_image" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"YOUR_ITEM_ID","images_url":["https://example.com/bolt1.jpg"]}'

# 4. 自动分割并建立索引
curl -X POST "http://localhost:65432/railway/parts/auto_segment" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"YOUR_ITEM_ID","rebuild":false}'

# 5. 查看分割结果
curl "http://localhost:65432/railway/parts/segmented_images/YOUR_ITEM_ID"

# 6. 图片检索
curl -X POST "http://localhost:65432/railway/parts/image_search" \
  -H "Content-Type: application/json" \
  -d '{"images_url":["https://example.com/unknown.jpg"],"radius":0.8,"texts":[]}'
```

---

### 场景2：3D重建

```bash
# 1. 提交3D重建任务
curl -X POST "http://localhost:65432/railway/parts/reconstruct_3d" \
  -H "Content-Type: application/json" \
  -d '{"item_id":"1482740094400990802","image_urls":["url1","url2","url3"]}' 

# 2. 查询进度（使用返回的task_id）
curl "http://localhost:65432/railway/parts/reconstruct_3d/progress/TASK_ID"

# 3. 列出所有任务
curl "http://localhost:65432/railway/parts/reconstruct_3d/tasks"
```

---

### 场景3：文档解析

```bash
# 1. 上传文档
curl -X POST "http://localhost:65432/railway/docs/file" \
  -H "Content-Type: application/json" \
  -d '{"file_name":"手册.pdf","file_url":"https://example.com/manual.pdf"}'

# 2. 查看表格
curl -X POST "http://localhost:65432/railway/docs/file/tables" \
  -H "Content-Type: application/json" \
  -d '{"file_id":"1","page":1,"pageSize":10,"query":""}'

# 3. 导出Excel
curl -X POST "http://localhost:65432/railway/docs/file/export" \
  -H "Content-Type: application/json" \
  -d '{"file_id":"1","user_id":"123"}'
```

---

## 🔧 使用 Swagger UI 测试

访问 `http://localhost:65432/docs` 可以看到自动生成的交互式 API 文档，支持：
- 查看所有接口
- 在线测试
- 查看请求/响应模型

---

## 📊 核心技术栈

- **FastAPI**: Web 框架
- **Milvus**: 向量数据库（图片特征检索）
- **SAM (Segment Anything)**: 图像分割
- **DINOv2**: 高精度特征提取（1024维）
- **COLMAP**: 相机位姿估计
- **3D Gaussian Splatting**: 3D重建
- **SuGaR**: Mesh 提取
- **PostgreSQL**: 关系数据库
- **MinIO**: 对象存储

---

## ⚠️ 注意事项

1. **图片URL**: 
   - MinIO 服务地址：192.168.100.126:9000（当前状态：需要确认）
   - 数据库中有 14,398 条图片记录
   - 图片路径格式：`bfr-ai-files/{文件ID}.jpg`
   - 完整URL格式：`http://192.168.100.126:9000/bfr-ai-files/{文件ID}.jpg`
   - 示例图片：`bfr-ai-files/1725402784070635520.jpg`

2. **3D重建**: 至少需要 10 张多角度照片，建议 50-100 张

3. **特征模式**: 默认使用 DINOv2-Large (高精度)，可选 ResNet34 (标准)

4. **相似度阈值**: `radius` 参数范围 -1 到 1，越大越严格，建议 0.7-0.9

5. **异步任务**: 3D重建是后台任务，需要轮询进度接口

6. **配件ID**: 使用真实的配件ID进行测试，示例中的ID来自实际数据库

7. **分页参数**: 使用 `pageSize` 而不是 `per_page`

---

## 📝 数据库信息

**当前数据库统计**:
- 配件总数: 78,740 条
- 数据库地址: 192.168.100.8:5432
- 数据库名: zcsf

**示例配件数据**:
- ID: `1482740094400990802`, 名称: 司机室控制主机, 编码: 40001178346
- ID: `1555467253485408256`, 名称: 半单管卡DN25, 编码: 10010840010
- ID: `1557988408477880320`, 名称: 门锁组成左, 编码: 19010022376
- ID: `1557988713898708992`, 名称: 二等车三人座椅, 编码: 29148120028
- ID: `1557989033974435840`, 名称: 左支座, 编码: 29358110029

---

这份文档已经涵盖了所有 33 个接口的详细说明和测试方法，使用真实的数据库ID和有效的测试数据。
