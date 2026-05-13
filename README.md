# 铁路配件智能识别系统

基于 FastAPI 的铁路配件智能识别系统，覆盖以下核心能力：

- 配件基础管理
- 图片检索与文本检索
- V2 向量索引重建
- 检索历史与技术部核验闭环
- 配件图片分割与预处理
- 视频三维重构

## 文档入口

甲方部署、联调和运维建议优先阅读以下文档：

- [部署文档](部署文档.md)
- [SGO网关与算法服务接口对接说明](SGO网关与算法服务接口对接说明.md)

如果需要查看项目结构，可参考：

- [代码结构说明](docs/代码结构说明.md)

## 技术栈

- FastAPI
- PostgreSQL
- Milvus
- MinIO
- Redis / Celery / Flower
- SigLIP
- DINOv2
- SAM / SAM3
- COLMAP / 3D Gaussian Splatting

## 代码结构

```text
recognition/
├── csrcqsf/                         # 主应用代码
│   ├── app.py                       # FastAPI 应用入口
│   ├── settings.py                  # 配置读取
│   ├── services/                    # API 路由层
│   ├── biz/                         # 业务逻辑层
│   ├── data/                        # 数据访问层
│   └── models/                      # ORM / 数据模型
├── tests/                           # 单元测试
├── scripts/                         # 工具脚本
├── docs/                            # 项目文档
└── csrcqsf/biz/railwayparts/reconstruction_server/
                                     # 三维重构独立服务
```

## 快速开始

### 1. 安装依赖

```bash
cd /home/ubuntu/project-train/recognition
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

然后按实际环境修改 `.env`，重点包括：

- PostgreSQL
- Milvus
- MinIO
- Redis
- `MODEL_DIR`

### 3. 准备模型文件

当前项目依赖的模型默认通过 `MODEL_DIR` 指向本地目录。  
模型放置规范、公司 OSS 上传建议和下载命令，请参考：

- [部署文档 - 公司 OSS 模型准备与下载](部署文档.md)

### 4. 启动主服务

```bash
cd /home/ubuntu/project-train/recognition
source .venv/bin/activate
python main.py
```

默认地址：

- Swagger: `http://127.0.0.1:65432/docs`

### 5. 按需启动三维重构后台服务

如果需要使用视频三维重构，还需要启动：

- Redis
- Celery Worker
- Flower
- reconstruction_server API

详细步骤见：

- [部署文档](部署文档.md)
- [reconstruction_server README](csrcqsf/biz/railwayparts/reconstruction_server/README.md)
- [Celery 说明](csrcqsf/biz/railwayparts/reconstruction_server/docs/README_CELERY.md)

## Docker 部署交付

当前项目已补齐第一版 GPU Docker 交付物，适合“乙方打镜像，甲方直接 `docker load` 运行”的场景。

推荐交付内容：

- 镜像包 `recognition.tar`
- 部署环境文件 `.env.deployment`
- 启动脚本 `scripts/deployment/run_docker_deployment.sh`
- 模型下载说明和公司 OSS 地址

第一版 Docker 部署约束：

- 只容器化 FastAPI 主服务
- PostgreSQL、Redis、Milvus、MinIO 继续使用外部现成服务
- 模型目录不打进镜像，运行时挂载到容器内 `/models`
- `patch_tokens`、`logs`、`temp`、`state` 必须挂载到宿主机持久化目录

具体步骤见：

- [部署文档](部署文档.md)

## 常用验证命令

### 验证模型路径

```bash
PYTHONPATH=. .venv/bin/python scripts/testing/debug_model_paths.py
```

### 验证向量库配置

```bash
PYTHONPATH=. .venv/bin/python scripts/testing/test_vector_db_config.py
```

### 运行相关测试

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q
```

## 说明

- 当前仓库 README 只保留项目简介和导航信息。
- 甲方实际部署步骤、模型下载、Docker 启动顺序和故障排查统一维护在 [部署文档](部署文档.md)。
