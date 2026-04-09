# Swagger 接口分类说明

## 📋 分类结构

访问 `http://localhost:65432/docs` 可以看到按照以下分类组织的接口：

### 业务接口 (20个)

#### 1. 业务-配件管理 (6个)
- POST `/railway/parts/item` - 创建配件实体
- POST `/railway/parts/item_delete` - 删除配件实体
- POST `/railway/parts/item_put` - 修改配件实体描述
- POST `/railway/parts/item/size_put` - 修改配件3D模型的尺寸描述
- POST `/railway/parts/list_items` - 列出配件列表
- POST `/railway/parts/get_item_details` - 获取配件的详细信息

#### 2. 业务-图片管理 (3个)
- POST `/railway/parts/create_item_image` - 为配件上传图片
- POST `/railway/parts/delete_item_image_index` - 删除配件图片索引
- GET `/railway/parts/segmented_images/{item_id}` - 获取配件的分割记录

#### 3. 业务-特征管理 (3个)
- POST `/railway/parts/list_item_features` - 列出当前配件的features
- POST `/railway/parts/update_item_features` - 修改配件文字特征
- POST `/railway/parts/delete_item_features` - 删除配件文字特征

#### 4. 业务-检索历史 (2个)
- POST `/railway/parts/search/history/v2` - 检索历史列表
- POST `/railway/parts/search/history/delete/v2` - 删除检索历史

#### 5. 业务-SGO集成 (4个)
- POST `/sgo/sgo/parts/sync` - 同步一次所有的配件基本信息
- POST `/sgo/sgo/parts/images/sync` - 同步选中的配件的照片
- POST `/sgo/sgo/parts/images` - 根据配件id获取sgo系统里的图片
- POST `/sgo/sgo/inquery/list` - 获取询码记录列表

#### 6. 业务-文档管理 (4个)
- POST `/railway/docs/file` - 上传并解析配件手册
- POST `/railway/docs/files` - 列出文件列表
- POST `/railway/docs/file/tables` - 列出文件的表格数据
- POST `/railway/docs/file/export` - 导出excel文件

#### 7. 业务-任务管理 (2个)
- GET `/railway/parts/reconstruct_3d/progress/{task_id}` - 查询3D重建进度
- GET `/railway/parts/reconstruct_3d/tasks` - 列出3D重建任务

#### 8. 业务-数据统计 (1个)
- POST `/railway/parts/data/statistics` - 索引统计

---

### 算法接口 (13个)

#### 1. 算法-图像分割 (2个)
**技术**: SAM (Segment Anything Model)

- POST `/segment/simple` - 简单的图像物体提取 (SAM)
- POST `/railway/parts/auto_segment` - 自动分割并建立索引 (SAM + DINOv2)

#### 2. 算法-特征索引 (2个)
**技术**: DINOv2-Large (1024维特征向量)

- POST `/railway/parts/item_image_indexed` - 为配件建立索引
- POST `/railway/parts/index_rebuild` - 重建所有配件的图片索引

#### 3. 算法-智能检索 (2个)
**技术**: Milvus向量检索

- POST `/railway/parts/image_search` - 根据图片查询配件
- POST `/railway/parts/search/v2` - 检索V2版本（图片+文字）

#### 4. 算法-OCR识别 (1个)
**技术**: OCR引擎

- POST `/images/ocr/front` - 获取ocr内容

#### 5. 算法-3D重建 (1个)
**技术**: COLMAP + 3D Gaussian Splatting + SuGaR

- POST `/railway/parts/reconstruct_3d` - 3D重建 (多角度照片→OBJ)

---

## 🎯 分类优势

### 1. 清晰的功能分组
- 业务接口和算法接口一目了然
- 每个分类下的接口数量适中，便于查找

### 2. 便于前端开发
- 前端可以按照分类组织API调用
- 业务逻辑和算法调用分离

### 3. 便于文档阅读
- Swagger UI 自动按 tags 分组
- 减少滚动查找的时间

### 4. 便于维护
- 新增接口时明确应该归属哪个分类
- 接口职责更加清晰

---

## 📝 命名规范

### 业务接口标签格式
```
业务-{功能模块}
```

示例：
- `业务-配件管理`
- `业务-图片管理`
- `业务-SGO集成`

### 算法接口标签格式
```
算法-{算法类型}
```

示例：
- `算法-图像分割`
- `算法-特征索引`
- `算法-智能检索`

---

## 🔧 技术实现

### 修改的文件
1. `csrcqsf/services/parts.py` - 配件相关接口
2. `csrcqsf/services/sgo.py` - SGO集成接口
3. `csrcqsf/services/doc_parse.py` - 文档管理接口
4. `csrcqsf/services/images.py` - 图像处理接口
5. `csrcqsf/app.py` - 主应用和segment接口

### 修改方式
在每个路由装饰器中修改 `tags` 参数：

```python
# 修改前
@parts_router.post('/item', tags=["railway"], summary='创建配件实体')

# 修改后
@parts_router.post('/item', tags=["业务-配件管理"], summary='创建配件实体')
```

---

## 📊 接口统计

| 分类 | 子分类 | 接口数 |
|------|--------|--------|
| 业务接口 | 配件管理 | 6 |
| 业务接口 | 图片管理 | 3 |
| 业务接口 | 特征管理 | 3 |
| 业务接口 | 检索历史 | 2 |
| 业务接口 | SGO集成 | 4 |
| 业务接口 | 文档管理 | 4 |
| 业务接口 | 任务管理 | 2 |
| 业务接口 | 数据统计 | 1 |
| **业务接口小计** | | **20** |
| 算法接口 | 图像分割 | 2 |
| 算法接口 | 特征索引 | 2 |
| 算法接口 | 智能检索 | 2 |
| 算法接口 | OCR识别 | 1 |
| 算法接口 | 3D重建 | 1 |
| **算法接口小计** | | **13** |
| **总计** | | **33** |

---

## 🚀 使用建议

### 前端开发
1. 业务接口通常响应快速，可以频繁调用
2. 算法接口响应较慢，建议异步调用并显示加载状态
3. 3D重建等长时间任务需要轮询进度接口

### 测试
1. 先测试业务接口，确保数据正确
2. 再测试算法接口，验证AI功能
3. 使用Swagger UI的"Try it out"功能快速测试

### 文档查阅
1. 在Swagger UI中点击分类名称可以展开/折叠
2. 使用浏览器搜索功能（Ctrl+F）快速定位接口
3. 参考 `docs/API接口分类.md` 了解详细说明

---

**访问地址**: http://localhost:65432/docs
