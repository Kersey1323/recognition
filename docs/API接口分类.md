# 铁路配件识别系统 - API 接口分类

## 📋 接口总览

**服务地址**: `http://localhost:65432`  
**接口总数**: 33个  
**分类方式**: 业务接口 vs 算法接口

---

## 🏢 业务接口 (20个)

业务接口主要处理数据的增删改查、系统集成、数据同步等业务逻辑。

### 1. 配件基础管理 (10个)

#### 1.1 配件 CRUD
- `POST /railway/parts/item` - 创建配件
- `POST /railway/parts/item_delete` - 删除配件
- `POST /railway/parts/item_put` - 修改配件信息
- `POST /railway/parts/item/size_put` - 修改3D模型尺寸描述
- `POST /railway/parts/list_items` - 列出配件列表（分页）
- `POST /railway/parts/get_item_details` - 获取配件详情

#### 1.2 配件图片管理
- `POST /railway/parts/create_item_image` - 为配件上传图片
- `POST /railway/parts/delete_item_image_index` - 删除图片索引
- `GET /railway/parts/segmented_images/{item_id}` - 获取分割记录

#### 1.3 数据统计
- `POST /railway/parts/data/statistics` - 索引统计

---

### 2. 配件特征管理 (3个)

- `POST /railway/parts/list_item_features` - 列出配件文字特征
- `POST /railway/parts/update_item_features` - 修改文字特征
- `POST /railway/parts/delete_item_features` - 删除文字特征

---

### 3. 检索历史管理 (2个)

- `POST /railway/parts/search/history/v2` - 检索历史列表
- `POST /railway/parts/search/history/delete/v2` - 删除检索历史

---

### 4. SGO 系统集成 (4个)

外部系统数据同步接口

- `POST /sgo/sgo/parts/sync` - 同步配件基本信息
- `POST /sgo/sgo/parts/images/sync` - 同步配件照片
- `POST /sgo/sgo/parts/images` - 获取SGO系统图片
- `POST /sgo/sgo/inquery/list` - 获取询码记录列表

---

### 5. 文档管理 (4个)

配件手册文档解析与管理

- `POST /railway/docs/file` - 上传并解析配件手册
- `POST /railway/docs/files` - 列出文件列表
- `POST /railway/docs/file/tables` - 列出文件的表格数据
- `POST /railway/docs/file/export` - 导出Excel文件

---

### 6. 3D 重建任务管理 (2个)

- `GET /railway/parts/reconstruct_3d/progress/{task_id}` - 查询3D重建进度
- `GET /railway/parts/reconstruct_3d/tasks` - 列出3D重建任务

---

## 🤖 算法接口 (13个)

算法接口主要处理AI模型相关的功能，包括图像识别、特征提取、3D重建等。

### 1. 图像分割 (2个)

**技术**: SAM (Segment Anything Model)

- `POST /segment/simple` - 简单的图像物体提取
- `POST /railway/parts/auto_segment` - 自动分割并建立索引

**说明**: 
- `auto_segment` 是完整的自动化流程：SAM分割 + DINOv2特征提取 + Milvus索引
- `simple` 仅返回分割mask，用于快速测试

---

### 2. 特征提取与索引 (3个)

**技术**: DINOv2-Large (1024维特征向量)

- `POST /railway/parts/item_image_indexed` - 建立图片索引
- `POST /railway/parts/index_rebuild` - 重建所有索引

**向量数据库**: Milvus

**说明**:
- 支持原图或裁剪后的图片
- 自动提取DINOv2特征并存入Milvus
- 支持文字特征标注

---

### 3. 智能检索 (3个)

**技术**: 向量相似度搜索 (Milvus) + 文本匹配

- `POST /railway/parts/image_search` - 图片相似度搜索
- `POST /railway/parts/search/v2` - 综合检索V2（图片+文字）

**算法流程**:
1. 图片 → DINOv2特征提取 → 1024维向量
2. Milvus向量检索（余弦相似度）
3. 文字特征过滤
4. 返回相似配件列表

**参数说明**:
- `radius`: 相似度阈值 (-1到1)，建议0.7-0.9
- `texts`: 文字特征列表，用于二次过滤

---

### 4. OCR 文字识别 (1个)

**技术**: OCR引擎

- `POST /images/ocr/front` - OCR文字识别

**应用场景**: 提取铭牌、标签上的文字信息

---

### 5. 3D 重建 (1个)

**技术栈**: COLMAP + 3D Gaussian Splatting + SuGaR

- `POST /railway/parts/reconstruct_3d` - 3D重建（多角度照片→OBJ）

**算法流程**:
1. COLMAP: 相机位姿估计 (SfM)
2. 3D Gaussian Splatting: 场景重建
3. SuGaR: Mesh提取 (生成OBJ文件)

**要求**:
- 至少10张多角度照片
- 建议50-100张以获得更好效果
- 异步任务，需轮询进度

---

## 📊 接口分类对比

| 分类 | 数量 | 主要功能 | 技术特点 |
|------|------|----------|----------|
| 业务接口 | 20个 | 数据管理、系统集成 | CRUD、数据同步、文档解析 |
| 算法接口 | 13个 | AI识别、特征提取 | SAM、DINOv2、Milvus、3DGS |

---

## 🔄 典型业务流程

### 流程1: 配件录入与智能检索

```
业务接口                          算法接口
    ↓                                ↓
1. 创建配件 (POST /item)
2. 上传图片 (POST /create_item_image)
                                3. 自动分割 (POST /auto_segment)
                                   ├─ SAM分割
                                   ├─ DINOv2特征提取
                                   └─ Milvus索引
4. 查看分割结果 (GET /segmented_images)
                                5. 图片检索 (POST /image_search)
                                   └─ 向量相似度搜索
6. 查看检索历史 (POST /search/history/v2)
```

---

### 流程2: 3D数字孪生

```
业务接口                          算法接口
    ↓                                ↓
1. 创建配件 (POST /item)
2. 上传多角度照片 (POST /create_item_image)
                                3. 提交3D重建 (POST /reconstruct_3d)
                                   ├─ COLMAP (SfM)
                                   ├─ 3DGS (重建)
                                   └─ SuGaR (Mesh)
4. 查询进度 (GET /reconstruct_3d/progress)
5. 查看任务列表 (GET /reconstruct_3d/tasks)
6. 更新OBJ URL (POST /item_put)
```

---

### 流程3: 外部系统集成

```
业务接口                          算法接口
    ↓                                ↓
1. 同步配件信息 (POST /sgo/parts/sync)
2. 同步配件照片 (POST /sgo/parts/images/sync)
                                3. 批量自动分割 (POST /auto_segment)
                                4. 重建索引 (POST /index_rebuild)
5. 查看询码记录 (POST /sgo/inquery/list)
                                6. 综合检索 (POST /search/v2)
```

---

## 🎯 接口选择指南

### 何时使用业务接口？

- ✅ 配件信息的增删改查
- ✅ 图片上传和管理
- ✅ 查看统计数据
- ✅ 与SGO系统集成
- ✅ 文档解析和导出
- ✅ 查看任务进度和历史

### 何时使用算法接口？

- ✅ 需要自动分割图片
- ✅ 需要提取图片特征
- ✅ 需要相似度检索
- ✅ 需要OCR识别
- ✅ 需要3D重建
- ✅ 需要重建向量索引

---

## 🔧 核心技术栈

### 业务层
- **FastAPI**: Web框架
- **PostgreSQL**: 关系数据库
- **MinIO**: 对象存储
- **SQLAlchemy**: ORM

### 算法层
- **SAM**: 图像分割 (Meta AI)
- **DINOv2**: 特征提取 (Meta AI, 1024维)
- **Milvus**: 向量数据库
- **COLMAP**: 相机位姿估计
- **3D Gaussian Splatting**: 3D重建
- **SuGaR**: Mesh提取
- **OCR**: 文字识别

---

## 📝 接口调用建议

### 业务接口
- 响应快速（通常<100ms）
- 可以频繁调用
- 支持批量操作
- 事务性保证

### 算法接口
- 响应较慢（秒级到分钟级）
- 建议异步调用
- 资源消耗大
- 需要GPU加速

---

## 🚀 快速测试

### 测试业务接口
```bash
# 配件列表
curl -X POST "http://localhost:65432/railway/parts/list_items" \
  -H "Content-Type: application/json" \
  -d '{"page":1,"pageSize":10,"query":"司机室"}'

# 数据统计
curl -X POST "http://localhost:65432/railway/parts/data/statistics" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 测试算法接口
```bash
# 图片分割
curl -X POST "http://localhost:65432/segment/simple" \
  -H "Content-Type: application/json" \
  -d '{"file_url":"https://example.com/test.jpg"}'

# 图片检索
curl -X POST "http://localhost:65432/railway/parts/image_search" \
  -H "Content-Type: application/json" \
  -d '{"images_url":["https://example.com/test.jpg"],"radius":0.8,"texts":[]}'
```

---

**详细接口文档**: `docs/API.md`  
**Swagger UI**: `http://localhost:65432/docs`
