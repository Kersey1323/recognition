# 铁路配件智能识别系统
https://github.com/Tencent-Hunyuan/Hunyuan3D-2
基于 FastAPI 的铁路配件主业务服务，当前覆盖以下能力：

- 配件基础管理
- 图片检索与文本检索
- V2 向量索引管理
- 检索历史与技术部核验闭环
- 配件图片分割与预处理
- 三维重构视频上传、任务提交、状态同步

本仓库现在只承载主业务服务；模型推理和三维重构训练链路都已经拆分为独立服务。

## 文档入口

- [部署文档](部署文档.md)
- [Docker 快速部署](docs/Docker镜像快速部署.md)
- [代码结构说明](docs/代码结构说明.md)
- [SGO网关与算法服务接口对接说明](SGO网关与算法服务接口对接说明.md)

## 当前架构

当前部署形态已经调整为“三服务解耦”：

- `recognition`：主业务服务，对前端保持现有接口路径与返回结构
- 模型推理服务：通过 `MODEL_SERVICE_URL` 提供 OCR、分割、向量特征等推理能力
- 三维重构服务：通过 `RECONSTRUCTION_SERVER_URL` 对接独立的 `reconstruction_server`

相关目录约定：

- 主业务仓库：`/home/ubuntu/project-train/recognition`
- 三维重构服务：`/home/ubuntu/project-train/reconstruction_server`
- 三维重构算法研发工程：`/home/ubuntu/project-train/reconstruction`

说明：

- 前端仍然只访问主业务服务
- 主业务服务本身不带统一前缀；如果线上通过 Nginx 代理增加 `/recognition_api`，那属于网关层行为
- 主业务已支持脱离 GPU 启动
- 未配置 `RECONSTRUCTION_SERVER_URL` 时，三维重构能力会禁用

## 代码结构

```text
recognition/
├── main.py                           # 启动入口
├── csrcqsf/
│   ├── core/                         # 应用入口、配置、运行时、调度
│   ├── infra/                        # 数据库、MinIO、Milvus、外部服务客户端
│   ├── modules/
│   │   ├── railway_parts/            # 铁路配件主业务模块
│   │   │   ├── routes/               # 路由定义
│   │   │   ├── schemas/              # 请求/响应模型
│   │   │   ├── services/             # 业务服务
│   │   │   ├── repositories/         # 仓储层
│   │   │   ├── integrations/         # 外部能力适配
│   │   │   ├── utils/                # 上传/文件等通用工具
│   │   │   └── vector_search/        # 向量检索子系统
│   │   ├── image/                    # 图像能力
│   │   ├── doc_parse/                # 文档解析
│   │   └── sgo/                      # SGO 集成
│   └── models/
│       └── orm/                      # ORM 模型
├── docs/                             # 项目文档
├── scripts/                          # 运维/测试/迁移脚本
├── tests/                            # 自动化测试
├── state/                            # 运行状态目录
└── temp/                             # 临时文件目录
```

这次结构治理后的几个关键变化：

- 旧的 `services / biz / data / models` 混合结构已经收敛到 `core / infra / modules / models`
- 三维重构运行时代码已从主仓库迁出到独立的 `reconstruction_server`
- 配件检索子系统已收口到 `csrcqsf/modules/railway_parts/vector_search`
- `patch_tokens` 不再放在源码目录，默认落在 `state/vector_db/patch_tokens`

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

按实际环境至少检查以下配置：

- 主业务 MySQL：`MAIN_DB_*`
- MinIO：`MINIO_*`
- Milvus：`MILVUS_*`
- Redis：`REDIS_*`
- 基础服务 HTTP 鉴权地址：`BASIS_API_HTTP_URL`
- 模型推理服务：`MODEL_SERVICE_URL`
- 三维重构服务：`RECONSTRUCTION_SERVER_URL`

说明：

- `MODEL_SERVICE_URL` 不可用时，依赖模型推理的接口无法正常使用
- `RECONSTRUCTION_SERVER_URL` 不配置时，主业务仍可启动，但三维重构相关接口会禁用
- `DINOV2_PATCH_TOKENS_DIR` 默认是 `state/vector_db/patch_tokens`，部署时应挂载持久化目录

### 3. 启动主服务

```bash
cd /home/ubuntu/project-train/recognition
source .venv/bin/activate
python main.py
```

默认访问地址：

- Swagger UI：`http://127.0.0.1:65432/docs`
- OpenAPI：`http://127.0.0.1:65432/openapi.json`

## 主服务与外部能力边界

主服务本身负责：

- 对前 HTTP API
- 主业务数据落库
- 检索历史、校验清单、上传记录、重构任务记录管理
- 调用外部模型服务和重构服务

主服务不再本地承担：

- OCR / 向量特征 / 分割模型推理
- 3D 重构训练与结果生成

如果需要启用完整能力：

- 部署模型服务并配置 `MODEL_SERVICE_URL`
- 部署 `reconstruction_server` 并配置 `RECONSTRUCTION_SERVER_URL`

## Docker 部署说明

当前主业务 Docker 镜像默认即为无 GPU 版本，重点用于甲方联调，不再单独维护 CPU 专属 Dockerfile 或部署脚本。

部署约束：

- 只容器化主业务服务
- MySQL、Redis、Milvus、MinIO 使用外部现成服务
- 模型推理与三维重构服务独立部署
- `logs`、`temp`、`state` 必须挂载到宿主机持久化目录
- 项目根目录 `Dockerfile` 定义运行时契约：端口、健康检查、持久化目录
- `Dockerfile.vendor` 作为 GitLab 发布流水线固定使用的镜像入口

详细步骤见：

- [Docker 快速部署](docs/Docker镜像快速部署.md)
- [部署文档](部署文档.md)

## 常用验证命令

### 验证向量库配置

```bash
PYTHONPATH=. .venv/bin/python scripts/testing/test_vector_db_config.py
```

### 验证主业务外部配置

```bash
PYTHONPATH=. .venv/bin/python scripts/testing/debug_model_paths.py
```

### 运行测试

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -q
```

### 本地模式分片上传调试页

如果要验证 `/railway/parts/v2/reconstruct/video/upload/part` 是否按真实分片方式上传，不要直接用 Swagger 选择整视频文件。

可直接打开：

- [reconstruct_local_upload_debug.html](/home/ubuntu/project-train/recognition/tools/reconstruct_local_upload_debug.html)

这个调试页会在浏览器里用 `file.slice(start, end)` 切出每个 `partBuffer`，再逐片调用：

- `/railway/parts/v2/reconstruct/video/upload/init`
- `/railway/parts/v2/reconstruct/video/upload/part`
- `/railway/parts/v2/reconstruct/video/upload/progress`
- `/railway/parts/v2/reconstruct/video/upload/complete`

当前分片模式说明：

- `storage_mode=local`
  - 前端分片后把每片传给主业务服务
  - 主业务服务先落本地
  - 后续再同步到 MinIO
- `storage_mode=remote`
  - 前端分片后把每片传给主业务服务
  - 主业务服务立即代理上传当前分片到 MinIO multipart upload
  - 前端不再直接访问 MinIO 预签名 URL

### 文件下载代理调试页

如果要验证 `/{bucket}/{object}` 是否已经能通过主业务鉴权并由 Nginx 内部回源 MinIO，可直接打开：

- [assets_download_debug.html](/home/ubuntu/project-train/recognition/tools/assets_download_debug.html)

配套 Nginx 示例配置：

- [nginx-assets-proxy-example.conf](/home/ubuntu/project-train/recognition/docs/deployment/nginx-assets-proxy-example.conf)

这个页面会：

- 带 `U-Token` 发起 `fetch`
- 请求主业务返回的 `bucket/object` 路径
- 自动预览图片/视频，或生成下载链接

本地如果没有真实 `U-Token`，可仅用于联调时启用：

```bash
export ASSET_PROXY_SKIP_AUTH=true
python main.py
```

这会让下载代理跳过 `U-Token` 校验，只建议本机调试使用。

如果本机没有安装 Nginx，可直接使用 Docker 启动一个本地代理容器：

```bash
bash scripts/deployment/run_assets_proxy_debug.sh
```

这个脚本会把容器内的 `host.docker.internal` 映射到宿主机，用来访问你本机启动的主业务 `65432` 端口。

## 文件下载代理

当前主业务保留接口中的原始 MinIO 业务路径，不再改写返回值：

- `bfr-3d-videos/...`
- `bfr-reconstruction-files/...`
- `bfr-search-history-files/...`

推荐部署方式：

- 前端只访问主业务返回的 `bucket/object`
- 下载时直接拼接代理域名，例如 `http://127.0.0.1:8080/bfr-3d-videos/raw-videos/...`
- 主业务接口校验 `U-Token` 后，返回 `X-Accel-Redirect: /recognition_oss/<bucket>/<object>`
- Nginx 配置 `location ^~ /recognition_oss { internal; proxy_pass http://<minio>; }`
- Nginx 再把 `/bfr-3d-videos/`、`/bfr-reconstruction-files/`、`/bfr-search-history-files/` 代理到主业务服务

## 说明

- README 只保留项目概览、目录说明和导航信息
- 具体部署步骤、环境准备和故障排查统一维护在 [部署文档](部署文档.md)
  "python.analysis.diagnosticSeverityOverrides": {
    "reportGeneralTypeIssues": "none"
  }
