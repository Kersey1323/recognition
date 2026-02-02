# 动车配件图像识别系统

## 环境依赖

### Python 依赖 (使用 uv)
```bash
uv sync
```


### 模型文件下载

#### 1. ResNet34 模型 (标准模式)
```bash
mkdir -p ./resnet_models
# 放置 pytorch_model.bin 到 ./resnet_models/
```

#### 2. DINOv2-Large 模型 (高精度模式)
```bash
mkdir -p ./dinov2_models
wget https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_pretrain.pth -O ./dinov2_models/dinov2_vitl14_pretrain.pth
```

#### 3. Embedding 模型
```bash
# 放置 sentence-transformer 模型到 ./embedding_models/
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

启动后访问: `http://localhost:8000/docs`
