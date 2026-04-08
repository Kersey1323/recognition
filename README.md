# 动车配件图像识别系统

基于 FastAPI 的铁路配件智能识别系统，集成了图像识别、3D重建、文档解析等功能。

## 项目结构

```
recognition/
├── csrcqsf/              # 主应用代码
│   ├── app.py           # FastAPI 应用入口
│   ├── settings.py      # 配置文件
│   ├── biz/            # 业务逻辑
│   ├── data/           # 数据层
│   ├── models/         # 数据模型
│   └── services/       # API 服务
├── scripts/             # 工具脚本（按功能分类）
│   ├── database/       # 数据库维护
│   ├── data_processing/ # 数据处理
│   ├── deployment/     # 部署配置
│   ├── document/       # 文档处理
│   ├── embedding/      # 特征提取
│   ├── minio/         # MinIO管理
│   ├── reconstruction/ # 3D重建
│   └── testing/       # 功能测试
├── tests/              # 单元测试
├── docs/               # 项目文档
│   ├── API.md         # API文档
│   ├── diagrams/      # 架构图
│   └── archive/       # 历史文档
├── models/             # AI模型
│   ├── embedding/     # 嵌入模型
│   └── resnet/        # ResNet模型
├── data/              # 数据文件
│   ├── temp/          # 临时文件
│   ├── logs/          # 日志
│   └── video/         # 测试视频
└── tools/             # 工具HTML

详细重构说明见：docs/重构完成报告.md
```

## 环境依赖

### Python 依赖 (使用 uv)
```bash
uv sync
```


### 模型文件下载

#### 1. ResNet34 模型 (标准模式)
```bash
mkdir -p ./models/resnet
# 放置 pytorch_model.bin 到 ./models/resnet/
```

#### 2. DINOv2-Large 模型 (高精度模式)
```bash
mkdir -p ./models/dinov2
wget https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_pretrain.pth -O ./models/dinov2/dinov2_vitl14_pretrain.pth
```

#### 3. Embedding 模型
```bash
# 放置 sentence-transformer 模型到 ./models/embedding/
```

#### 4. SAM 模型 (自动分割)
```bash
mkdir -p ./sam_models
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth -O ./sam_models/sam_vit_h_4b8939.pth
```

### 3D 重建依赖 (可选)

#### COLMAP
```bash
# Ubuntu
apt install colmap

# 或从源码编译
# https://colmap.github.io/install.html
```

#### 3D Gaussian Splatting
```bash
git clone https://github.com/graphdeco-inria/gaussian-splatting /opt/gaussian-splatting
cd /opt/gaussian-splatting && pip install -e .
export GS_REPO_PATH=/opt/gaussian-splatting
```

#### SuGaR (Mesh 提取)
```bash
git clone https://github.com/Anttwo/SuGaR /opt/SuGaR
cd /opt/SuGaR && pip install -e .
export SUGAR_REPO_PATH=/opt/SuGaR
```

## 运行

```bash
python -m csrcqsf.main
```

## API 文档

启动后访问: `http://localhost:65432/docs`

详细API说明见：`docs/API.md`

## 测试

```bash
# 运行所有测试
python -m pytest tests/

# 测试API接口
python tests/test_all_apis.py

# 测试数据库连接
python tests/test_db_connection.py

# 测试MinIO
python tests/test_minio.py
```

## 工具脚本

所有工具脚本位于 `scripts/` 目录，按功能分类：

```bash
# 数据库维护
python scripts/database/fix_db_columns.py

# 数据处理
python scripts/data_processing/sync_image_all.py

# 文档生成
python scripts/document/gen_word.py

# 特征提取
python scripts/embedding/embed_word.py

# 3D重建
python scripts/reconstruction/3d_reconstruction.py
```

## 配置

- 数据库：PostgreSQL (192.168.100.2:5432)
- MinIO：192.168.100.2:9000
- 服务端口：65432

配置文件：`csrcqsf/settings.py`
