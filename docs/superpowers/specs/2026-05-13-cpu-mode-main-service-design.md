# CPU Mode Main Service Design

## Goal

为当前项目提供一个可打包、可部署的主服务 CPU/无卡模式，用于后续甲方环境联调准备。

本次设计目标不是让整个项目“完全无卡可用”，而是：

- 主服务可在无 GPU 环境启动并提供核心业务接口
- 3D 重建域中不依赖 GPU 的基础业务接口继续开放，支持甲方联调视频上传、查询、删除等流程
- 仅对真正需要 GPU 的接口进行显式拒绝，不进入运行时深处后再失败
- 在甲方未提供本地模型路径时，服务仍可启动并联调不依赖模型/GPU 的主业务接口
- 提供独立的 CPU 镜像与部署入口，避免污染现有 GPU 部署流程

## Non-Goals

本次不覆盖以下内容：

- 3D 重建训练
- 2DGS / SuGaR / Gaussian / OpenSplat 完整流程
- 将重建链路改造成 CPU 可运行
- 优化 CPU 模式下的推理性能
- 合并 GPU 和 CPU 的部署脚本为单一复杂入口

## Current State

当前仓库已经具备部分 CPU 运行基础，但部署层仍是 GPU-first：

- `SegmentBiz`、SigLIP、DINOv2 的模型加载代码会在无 CUDA 时 fallback 到 CPU
- 当前 `Dockerfile` 使用 `nvidia/cuda` 基础镜像，并强制安装 CUDA 版 `torch/torchvision`
- 当前部署脚本强制 `docker run --gpus all`
- 应用启动阶段会执行 `SegmentBiz.init()`，这会触发模型检查、下载和 SAM 模型加载
- 3D 重建链路中存在直接依赖 CUDA 的实现，不能在 CPU 模式下继续暴露为“可用”

因此问题不在“主服务完全不能 CPU 运行”，而在：

1. 镜像构建方式与部署脚本仍绑死 GPU
2. 3D 重建接口缺少统一的“哪些接口依赖 GPU、哪些接口可无卡联调”的能力边界
3. 启动阶段仍默认假设本地模型可用，不满足“甲方不给模型路径也能部署”的诉求

## User-Facing Behavior

### GPU 正常模式

保持现状：

- 原 `Dockerfile`
- 原 `.env.deployment`
- 原部署脚本
- 原 3D 重建接口可见且可调用

### CPU / 无卡模式

新增一套平行部署入口：

- `docker/Dockerfile`
- `.env.deployment`
- `scripts/deployment/run_docker_deployment.sh`

CPU 模式下：

- 服务可以正常启动
- 不要求本地存在 SAM / SAM3 / SigLIP / DINOv2 模型路径
- 不要求启动时下载大模型
- 原始视频管理、重建结果管理和查询类接口继续开放
- 真正需要 GPU 的重建动作接口统一返回明确错误
- 真正依赖模型的接口统一返回明确错误
- 错误信息语义固定：`当前无GPU，无法使用`

## Design Options

### Option A: 仅替换镜像，不处理接口

做法：

- 增加 CPU 镜像和部署脚本
- 不改服务行为
- 3D 重建接口继续暴露，调用时在深层逻辑失败

优点：

- 实现最少

缺点：

- 联调体验差
- 外部无法从接口层判断当前部署能力边界
- 失败点分散，不利于排障

### Option B: CPU 镜像 + 服务层显式禁用整个重建接口域

做法：

- 增加 CPU 镜像和部署脚本
- 通过环境变量在服务层统一禁用 `/v2/reconstruct/*`

优点：

- 能力边界清晰
- 失败路径一致
- 风险最小
- 不需要改造重建内部实现

缺点：

- 需要在服务层补一层统一检查

### Option C: CPU 镜像 + 服务层按接口粒度区分可用能力

做法：

- 视频上传、视频查询、结果上传、结果删除、任务查询等不依赖 GPU 的接口保留
- 训练、完整重建提交、任务取消等需要 GPU 的接口禁用

优点：

- 更细粒度
- 满足甲方基础联调诉求
- 能缩短 CPU 镜像打包时间，同时保留大部分业务流程验证能力

缺点：

- 语义复杂
- 外部需要理解哪些“重建相关接口”还能用，哪些不能用
- 需要在路由层精确维护接口分组

## Recommendation

采用 Option C。

理由：

- 用户现在明确希望联调视频上传、查询、删除等基础业务接口
- 目标不仅是“服务能启动”，还要让甲方尽量提前打通非算力依赖流程
- 只禁用真正依赖 GPU 的动作接口，能在保持边界清晰的同时提升联调价值

## Architecture

### 1. Deployment Split

保留现有 GPU 部署链路不动，新增 CPU 部署链路。

新增文件职责：

- `docker/Dockerfile`
  - 使用普通 Linux/Python 基础镜像
  - 安装 CPU 版 `torch/torchvision`
  - 不安装大的 CUDA 相关依赖
  - 不要求镜像内预置本地模型
  - 复用主项目代码与依赖

- `.env.deployment`
  - 面向 CPU 模式的默认环境变量
  - 显式指定：
    - `SIGLIP_DEVICE=cpu`
    - `DINOV2_DEVICE=cpu`
    - `SAM3_DEVICE=cpu`
    - `ENABLE_GPU_RECONSTRUCTION=0`
    - `ENABLE_SEGMENT_MODEL=0`
    - `ENABLE_VECTOR_MODELS=0`
    - `ENABLE_OCR_MODEL=1`（若 OCR 也不联调则可设为 `0`）

- `scripts/deployment/run_docker_deployment.sh`
  - 不带 `--gpus all`
  - 挂载模型、日志、临时目录、状态目录
  - 默认使用 `.env.deployment`

### 2. Capability Flag

新增统一能力开关：

- `ENABLE_GPU_RECONSTRUCTION=0`
- `ENABLE_SEGMENT_MODEL=0`
- `ENABLE_VECTOR_MODELS=0`
- `ENABLE_OCR_MODEL=1`

语义：

- 当值为假时，当前服务实例不提供需要 GPU 的重建动作能力
- 当 `ENABLE_SEGMENT_MODEL=0` 时，启动阶段不初始化 `SegmentBiz`，相关分割接口直接拒绝
- 当 `ENABLE_VECTOR_MODELS=0` 时，不假设 SigLIP / DINOv2 / SAM3 本地模型存在，相关检索与建库接口直接拒绝
- 当 `ENABLE_OCR_MODEL=0` 时，不初始化 OCR 相关能力，OCR 接口直接拒绝
- 原始视频管理、结果上传删除、任务查询、统计查询等无 GPU 依赖接口不受影响
- 该能力开关与“是否存在 GPU”解耦
- CPU 模式默认关闭；GPU 模式默认开启

这样后续即使甲方机器后来有 GPU，也可以显式决定是否开放 GPU 重建动作能力。

### 3. Startup Gate

在 `csrcqsf/app.py` 的 `lifespan` 中加入启动期开关，避免 CPU 联调模式在服务刚启动时就因为模型缺失而失败。

建议规则：

- `ENABLE_SEGMENT_MODEL=0` 时跳过 `SegmentBiz.init()`
- `ENABLE_OCR_MODEL=0` 时跳过 OCR 相关初始化
- 不在 CPU 联调模式下自动下载 SAM / OCR / 向量模型

原因：

- 甲方当前没有卡，也可能没有模型目录
- 目标是“先把不依赖模型和 GPU 的主业务接口跑起来”
- 启动期就尝试模型下载/加载会直接违背这一目标

### 4. Service-Layer Gate

在 `csrcqsf/services/parts.py` 对两类接口加守卫：

- 需要 GPU 的接口
- 需要本地模型的接口

守卫行为：

- 在进入 `ReconstructionManager` 前执行
- 若 `ENABLE_GPU_RECONSTRUCTION=0`，立即抛出业务错误
- 错误文案固定，避免各接口返回不同提示
- 错误文案固定为：`当前无GPU，无法使用`

推荐方式：

- 抽一个轻量帮助函数，例如 `_ensure_gpu_reconstruction_enabled()`
- 抽一个轻量帮助函数，例如 `_ensure_model_capability_enabled(flag_name, message)`
- 在对应接口开头调用

不在 `ReconstructionManager` 深层做首要拦截，原因是：

- 用户侧希望从 API 层直接得到能力边界
- 服务层更适合作为对外 contract 的唯一入口

### 5. Scope of GPU-Gated Endpoints

CPU 模式下拒绝以下需要 GPU 的接口：

- 提交训练
- 从视频发起完整重建
- 取消任务

对应路由：

- `POST /v2/reconstruct/train`
- `POST /v2/reconstruct/tasks/video`
- `DELETE /v2/reconstruct/cancel/{task_id}`

### 6. Scope of Model-Gated Endpoints

CPU 联调模式下，当甲方未提供模型路径时，拒绝以下依赖本地模型的接口：

- OCR 识别
- 图像分割
- V2 检索
- V2 索引重建
- 任何需要显式加载 SigLIP / DINOv2 / SAM / SAM3 的接口

错误文案建议固定为：

- `当前未配置模型，无法使用`

说明：

- 这类接口不一定依赖 GPU，但依赖模型文件或模型下载
- 当前用户目标是主业务联调，不应让模型缺失阻塞整体部署

### 7. Scope of CPU-Available Endpoints

CPU 模式下继续开放以下不依赖 GPU 的接口：

- 配件基础 CRUD
- 图片管理（不依赖分割/检索模型的部分）
- 检索历史、校验清单、统计、列表、详情等纯业务接口
- 上传原始视频
- 原始视频列表 / 查询 / 更新 / 删除
- 上传 / 删除已有三维重构结果
- 查询任务状态
- 查询配件任务列表
- 查询全部任务列表
- 查询重建统计
- 查询场景列表

对应路由：

- `POST /v2/reconstruct/video`
- `POST /v2/reconstruct/video/list`
- `GET /v2/reconstruct/video/{item_id}`
- `PUT /v2/reconstruct/video/{item_id}`
- `DELETE /v2/reconstruct/video/{item_id}`
- `POST /v2/reconstruct/result/{item_id}`
- `DELETE /v2/reconstruct/result/{item_id}`
- `GET /v2/reconstruct/status/{task_id}`
- `GET /v2/reconstruct/item/{item_id}`
- `POST /v2/reconstruct/tasks/list`
- `POST /v2/reconstruct/statistics`
- `GET /v2/reconstruct/scenes`

原因：

- 这些接口本身不直接依赖 GPU 算力
- 这些接口也不应要求本地模型存在
- 即使查询结果为空，也不影响甲方提前联调接口 contract
- 能显著提高 CPU 模式下的业务联调价值

## Testing Strategy

### Config / Deployment Tests

新增测试覆盖：

- CPU 环境文件包含 `ENABLE_GPU_RECONSTRUCTION=0`
- CPU 环境文件包含 `ENABLE_SEGMENT_MODEL=0`
- CPU 环境文件包含 `ENABLE_VECTOR_MODELS=0`
- CPU 环境文件包含 `SIGLIP_DEVICE=cpu`、`DINOV2_DEVICE=cpu`、`SAM3_DEVICE=cpu`
- CPU 部署脚本不包含 `--gpus all`
- CPU Dockerfile 不基于 `nvidia/cuda`
- CPU Dockerfile 不安装大的 CUDA 依赖
- CPU Dockerfile 使用 CPU 版 `torch/torchvision`

### Route Contract Tests

新增测试覆盖：

- 重建路由定义仍然存在
- CPU 模式下 GPU 接口返回固定错误
- CPU 模式下模型依赖接口返回固定错误
- `ENABLE_SEGMENT_MODEL=0` 时应用启动不会调用 `SegmentBiz.init()`
- 在 `ENABLE_GPU_RECONSTRUCTION=0` 时，GPU 动作接口返回 `当前无GPU，无法使用`
- 在 `ENABLE_GPU_RECONSTRUCTION=0` 时，视频管理 / 查询 / 结果管理接口仍可进入正常业务分支
- 在 CPU 模式下，不影响 V2 检索和主服务其他路由 schema

### Startup Safety

至少验证：

- 主应用在 CPU 配置下可导入
- 不要求在测试中真实加载大模型
- 通过 mock 或静态契约测试确认重建 gate 生效

## Risks

### 1. CPU 性能明显下降

影响：

- SAM 分割慢
- SigLIP / DINOv2 建索引慢
- 检索首响应慢

处理：

- 本次不做性能承诺
- 只确保功能可用

### 2. 镜像依赖切换可能带来安装差异

影响：

- CPU 版 `torch/torchvision` 安装方式与当前 CUDA 版不同
- 某些第三方包可能隐式依赖 GPU wheel 组合

处理：

- CPU 镜像独立文件，不改现有 GPU Dockerfile
- 通过单独构建验证

### 3. GPU/非GPU接口边界划分错误

影响：

- 误把需要 GPU 的接口放开，会在深层失败
- 误把不需要 GPU 的接口拦住，会降低联调价值

处理：

- 在 spec 中明确路由清单
- 优先补 route-level 行为测试，不大改原有 schema 测试

## Implementation Outline

1. 新增 CPU 配置与部署入口
2. 新增统一 GPU 重建能力开关读取逻辑
3. 在需要 GPU 的重建路由层增加 gate
4. 新增/更新 CPU 模式相关测试
5. 运行聚焦测试与构建校验

## Acceptance Criteria

满足以下条件即视为完成：

- 可以构建 CPU 专用镜像
- 可以用 CPU 专用部署脚本启动服务
- 主服务核心非重建接口仍可启动并提供服务
- `ENABLE_GPU_RECONSTRUCTION=0` 时 GPU 动作接口统一返回 `当前无GPU，无法使用`
- `ENABLE_GPU_RECONSTRUCTION=0` 时视频上传、视频查询、结果上传删除、任务查询类接口仍可调用
- 现有 GPU 部署入口行为不变
