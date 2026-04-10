# 向量检索测试

测试 SigLIP 的图搜图和文搜图功能，DINOv2 的两阶段检索功能，以及 SigLIP + DINOv2 的混合检索功能。

## 快速开始：使用 MilvusManager 统一接口

推荐使用 `MilvusManager` 统一管理器进行检索测试，它集成了所有检索功能。

### 1. 文本检索（仅 SigLIP）

```bash
python vector_db/tests/test_milvus_manager.py \
    --mode text \
    --query "特殊螺栓"
```

### 2. 图像检索

**混合检索（默认，推荐）：**
```bash
python vector_db/tests/test_milvus_manager.py \
    --mode image \
    --query /path/to/query_image.jpg \
    --image-mode hybrid
```

**SigLIP 单模型检索：**
```bash
python vector_db/tests/test_milvus_manager.py \
    --mode image \
    --query /path/to/query_image.jpg \
    --image-mode siglip
```

**DINOv2 两阶段检索：**
```bash
python vector_db/tests/test_milvus_manager.py \
    --mode image \
    --query /path/to/query_image.jpg \
    --image-mode dinov2
```

## 检索模式对比

| 模式 | 优势 | 适用场景 |
|------|------|----------|
| **hybrid** | 融合 SigLIP 语义理解和 DINOv2 视觉细节，RRF 融合 + Patch 精排 | **推荐**：工业配件精确检索，需要识别微小规格差异 |
| **siglip** | 速度快，语义理解能力强 | 快速检索，对精度要求不高的场景 |
| **dinov2** | 视觉细节匹配精确，Patch-level 局部特征 | 需要精确匹配视觉细节的场景 |

## 独立测试脚本

以下是各个模型的独立测试脚本，用于详细测试和调试。

## 使用方法

### 1. 文搜图测试

```bash
python vector_db/tests/test_siglip_search.py \
    --mode text \
    --query "管卡" \
    --top-k 5 \
    --output-dir vector_db/tests/test_images/text_search_results
```

**常用查询示例：**
- "管卡" - 搜索管卡类零件
- "螺栓" - 搜索螺栓类零件
- "垫片" - 搜索垫片类零件
- "半单管卡DN25" - 精确搜索特定型号

### 2. 图搜图测试

首先需要准备一张查询图像，然后：

```bash
python vector_db/tests/test_siglip_search.py \
    --mode image \
    --query /path/to/query_image.jpg \
    --top-k 5 \
    --output-dir vector_db/tests/test_images/image_search_results
```

**获取查询图像的方法：**
1. 从数据库中随机选一张图像作为查询
2. 使用 MinIO 或本地文件系统中的图像
3. 拍摄实物照片进行测试

### 3. 从数据库随机选择图像作为查询

```bash
# 先运行一次文搜图，下载一些结果图像
python vector_db/tests/test_siglip_search.py \
    --mode text \
    --query "管卡" \
    --top-k 3

# 然后使用下载的图像进行图搜图测试
python vector_db/tests/test_siglip_search.py \
    --mode image \
    --query vector_db/tests/test_images/rank1_score0.9876_半单管卡DN25.jpg \
    --top-k 5
```

## 输出说明

脚本会：
1. 打印检索结果到终端（包括相似度分数、零件信息）
2. 下载结果图像到指定目录
3. 图像文件名格式：`rank{排名}_score{相似度}_{零件名称}.jpg`

## 评估检索效果

检查下载的图像，验证：
- **文搜图**：返回的图像是否与查询文本语义相关
- **图搜图**：返回的图像是否与查询图像视觉相似
- **排序质量**：相似度分数高的结果是否确实更相关

## 示例输出

```
Search Results:
================================================================================

Rank 1:
  Score: 0.8234
  Item ID: 1555467253485408256
  Item Name: 半单管卡DN25
  Item Code: BDG-DN25
  Image ID: 1983442698417344512
  Image URL: bfr-ai-files/small-1983442698220081152.png

Rank 2:
  Score: 0.7891
  ...
```

## 混合检索测试（SigLIP + DINOv2）

测试融合 SigLIP 和 DINOv2 的两阶段混合检索系统。

### 使用方法

```bash
python vector_db/tests/test_hybrid_search.py \
    --query /path/to/query_image.jpg \
    --coarse-top-k 30 \
    --fine-top-k 5 \
    --alpha 0.6 \
    --output-dir vector_db/tests/test_images/hybrid_search
```

**参数说明：**
- `--query`: 查询图像路径
- `--coarse-top-k`: 粗排返回候选数量（默认 30）
- `--fine-top-k`: 精排返回结果数量（默认 5）
- `--alpha`: 加权系数（默认 0.6），最终分数 = alpha × RRF分数 + (1-alpha) × Patch分数
- `--output-dir`: 结果图像保存目录

### 两阶段混合检索原理

**阶段 1：RRF 融合粗排**
- 同时使用 SigLIP 图像向量和 DINOv2 全局向量进行检索
- 通过 RRF (Reciprocal Rank Fusion) 算法融合两个模型的检索结果
- RRF 分数计算：score = Σ(1 / (k + rank))，其中 k=60
- 输出融合后的 Top-K 候选集

**阶段 2：Patch Token 精排**
- 针对粗排候选集，加载 DINOv2 patch tokens（1369×1024）
- 计算查询图像与候选图像的 patch-level 交叉匹配相似度矩阵
- 使用最大相似度均值量化局部几何特征（螺纹、倒角等微观细节）
- 加权合并 RRF 分数和 Patch 分数，输出最终排序

### 输出说明

脚本会生成两个目录：
- `output-dir/coarse/`: RRF 融合粗排前 10 个结果
- `output-dir/fine/`: Patch 精排 top-K 结果

文件名格式：
- 粗排：`rank{排名}_rrf{RRF分数}_{零件名称}.jpg`
- 精排：`rank{排名}_final{最终分数}_{零件名称}.jpg`

### 优势

- **互补性**：SigLIP 擅长语义理解，DINOv2 擅长视觉细节
- **鲁棒性**：RRF 融合降低单一模型的误判风险
- **精确性**：Patch-level 匹配能识别工业配件的微小规格差异

## DINOv2 两阶段检索测试

测试 DINOv2 的粗排（全局特征）+ 精排（patch tokens）两阶段检索。

### 使用方法

```bash
python vector_db/tests/test_dinov2_search.py \
    --query /path/to/query_image.jpg \
    --coarse-top-k 20 \
    --fine-top-k 5 \
    --output-dir vector_db/tests/test_images/dinov2_search
```

**参数说明：**
- `--query`: 查询图像路径
- `--coarse-top-k`: 粗排返回候选数量（默认 20）
- `--fine-top-k`: 精排返回结果数量（默认 5）
- `--output-dir`: 结果图像保存目录

### 两阶段检索原理

**阶段 1：粗排（Coarse Ranking）**
- 使用全局特征向量（1024D）进行快速检索
- 从整个数据库中筛选出 top-K 候选图像
- 速度快，适合大规模初筛

**阶段 2：精排（Fine Ranking）**
- 加载候选图像的 patch tokens（1369×1024）
- 计算查询图像与候选图像的 patch-level 相似度矩阵
- 使用最大相似度的平均值作为精排分数
- 精度高，适合精细匹配

### 输出说明

脚本会生成两个目录：
- `output-dir/coarse/`: 粗排前 10 个结果
- `output-dir/fine/`: 精排 top-K 结果

文件名格式：
- 粗排：`rank{排名}_dist{距离}_{零件名称}.jpg`
- 精排：`rank{排名}_score{相似度}_{零件名称}.jpg`

## 注意事项

- 确保 Milvus 服务正在运行
- 确保已经运行过 `build_index.py` 建立索引
- MinIO 凭证需要正确配置在 `vector_db/config/db_config.ini`
- 相似度分数范围：COSINE 距离，越接近 1 表示越相似
- DINOv2 测试需要 patch tokens 文件存在（由索引构建时生成）
