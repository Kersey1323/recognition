# 向量检索测试

主服务不再加载 SigLIP、DINOv2 或分割模型。图片和文本特征统一通过
`MODEL_SERVICE_URL` 调用独立模型服务，主服务仅负责 Milvus 检索、结果聚合和
patch token 持久化。

## 环境准备

- 主服务环境变量已配置 `MODEL_SERVICE_URL`。
- 模型服务 `/health` 返回正常，并提供 SigLIP、DINOv2 和索引提取能力。
- Milvus、MinIO 和主数据库连接正常。
- 查询图片使用本地可读路径。

## 统一检索脚本

文本检索：

```bash
python tests/vector_db/test_milvus_manager.py \
  --mode text \
  --query "特殊螺栓"
```

混合图像检索：

```bash
python tests/vector_db/test_milvus_manager.py \
  --mode image \
  --query /path/to/query_image.jpg \
  --image-mode hybrid
```

仅使用 SigLIP：

```bash
python tests/vector_db/test_milvus_manager.py \
  --mode image \
  --query /path/to/query_image.jpg \
  --image-mode siglip
```

仅使用 DINOv2：

```bash
python tests/vector_db/test_milvus_manager.py \
  --mode image \
  --query /path/to/query_image.jpg \
  --image-mode dinov2
```

## 检索模式

| 模式 | 用途 |
| --- | --- |
| `siglip` | 快速语义检索 |
| `dinov2` | 强调视觉细节和 patch token 精排 |
| `hybrid` | 融合语义与局部视觉特征，作为默认模式 |

## 说明

- 主服务环境不需要 Torch、Transformers、CUDA 或模型权重。
- 索引构建使用正式接口 `/railway/parts/v2/index/rebuild`，不再使用本地模型脚本。
- Collection 初始化优先使用正式接口；`scripts/vector_db/init_collections.py` 仅保留为运维工具。
