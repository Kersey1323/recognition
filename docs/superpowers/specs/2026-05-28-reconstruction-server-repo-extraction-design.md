# Reconstruction Server Repo Extraction Design

## Goal

将当前主业务仓库中的嵌入式三维重构服务彻底迁出：

- 把 `csrcqsf/biz/railwayparts/reconstruction_server` 迁移到 `/home/ubuntu/project-train/reconstruction_server`
- 让 `reconstruction_server` 作为独立 git 仓库存在并单独维护
- 让 `recognition` 只保留主业务、远端重构客户端、任务状态同步和业务落库
- 删除主业务仓内已经不参与运行链路的历史算法目录 `csrcqsf/biz/reconstruction`
- 保持当前前端访问主业务的接口 contract 不变

本次目标不是继续做“同仓双服务”，而是把物理目录边界也落地。

## Non-Goals

本次不包含以下内容：

- 修改前端访问路径、入参、返回值
- 改造三维重构算法本身
- 合并 `/home/ubuntu/project-train/reconstruction` 与 `reconstruction_server`
- 把主业务和重构服务做成单一仓库的 monorepo
- 对重构服务做新的任务框架替换
- 迁移 Milvus / MinIO / MySQL 的业务边界

## Current State

当前代码处于“逻辑上双服务、物理上混仓”的状态：

1. 主业务已经通过 `RECONSTRUCTION_SERVER_URL` 与重构服务交互，主业务本地不再执行 GPU 重构任务。
2. `csrcqsf/biz/railwayparts/reconstruction_server` 实际上已经是一个近似独立工程，内部包含：
   - FastAPI API
   - Celery / Redis / Worker
   - `pipeline_v2.py`
   - 文档、测试、运行日志、输出目录
3. `csrcqsf/biz/railwayparts/reconstruction_server` 在主仓中不是普通目录，而是一个 `gitlink` 形式的嵌套仓库。
4. 主仓内还残留大量对该内嵌路径的引用：
   - `README.md`
   - `部署文档.md`
   - `docker/reconstruction-server/Dockerfile`
   - `scripts/deployment/run_reconstruction_server.sh`
   - 多个直接 import 或拼接该路径的测试脚本
5. `csrcqsf/biz/reconstruction` 已经不在主业务实际运行链路中，仅剩历史算法代码、测试和少量脚本引用。

## Hard Requirements

### 1. 主业务仓必须不再包含嵌入式重构服务

迁移完成后，`recognition` 仓中不再保留：

- `csrcqsf/biz/railwayparts/reconstruction_server`
- 与其强绑定的 Docker / 部署 / 测试资产

主业务只保留远端调用能力。

### 2. `/home/ubuntu/project-train/reconstruction` 不动

该目录继续作为算法研发仓存在，不参与这次迁移，不合并，不复用。

### 3. 重构服务必须成为真正独立仓库

目标目录固定为：

- `/home/ubuntu/project-train/reconstruction_server`

迁移后它必须具备：

- 自己的 `.git`
- 自己的部署脚本和文档
- 自己的测试
- 自己的 API / Worker / Redis 运行边界

### 4. 主业务对前端的接口 contract 不变

以下内容不允许因为迁移而变化：

- 路径
- 入参
- 返回值结构

### 5. 主业务仍然只认 `RECONSTRUCTION_SERVER_URL`

主业务继续通过：

- `RECONSTRUCTION_SERVER_URL`
- `RECONSTRUCTION_SERVER_TIMEOUT_SEC`

访问远端重构服务，不允许重新引入任何“本地内嵌目录兜底执行”。

## Design Options

### Option A: 保留当前嵌套仓历史并整体迁出

做法：

- 直接把当前 `csrcqsf/biz/railwayparts/reconstruction_server` 工作树整体移动到 `/home/ubuntu/project-train/reconstruction_server`
- 保留其中已有的 `.git`
- 在 `recognition` 主仓中移除 `gitlink`

优点：

- 风险最低
- 不丢失当前 `reconstruction_server` 的提交历史
- 不需要重新初始化 API / Worker / 文档 / 测试仓

缺点：

- 新位置继承的是当前嵌套仓历史，而不是一个空白新仓

### Option B: 拷贝文件后重新 `git init`

做法：

- 复制代码到 `/home/ubuntu/project-train/reconstruction_server`
- 删除原嵌套仓 `.git`
- 在目标目录 fresh `git init`

优点：

- 仓库历史干净
- 结构上最“新”

缺点：

- 丢失已有重构服务历史
- 更容易遗漏隐藏文件、脚本和 git 配置
- 回滚与追查变更更困难

### Option C: 保留当前内嵌形态，只做软链接或镜像目录

做法：

- 主仓里仍保留 `reconstruction_server`
- 再映射一份到同级目录

优点：

- 实现快

缺点：

- 边界仍然模糊
- 会制造双份真相源
- 后续维护成本最高

## Recommendation

采用 Option A。

理由：

- 当前 `reconstruction_server` 已经是独立 git 仓形态
- 用户要的是“迁出成独立仓”，不是“抹掉历史重建一份空仓”
- 直接整体迁出最符合现状，也最不容易破坏当前已联调通过的服务

这里的“初始化独立仓库”按实现语义解释为：

- 迁移后保证 `/home/ubuntu/project-train/reconstruction_server` 是一个可直接维护的独立 git 仓
- 默认保留当前已有 git 历史，而不是重新生成空白历史

## Target Layout

### Main Business Repo

`/home/ubuntu/project-train/recognition` 迁移后只保留：

- `csrcqsf/app.py`
- `csrcqsf/services/parts.py`
- `csrcqsf/biz/railwayparts/reconstruction_manager.py`
- `csrcqsf/biz/railwayparts/reconstruction_client.py`
- `csrcqsf/biz/railwayparts/reconstruction_sync_manager.py`
- `csrcqsf/models/reconstruction*.py`
- 与主业务三维重构接口、上传、状态同步相关的测试

明确不再保留：

- 内嵌 `reconstruction_server`
- 本地训练流水线
- 本地 Celery / Redis / Worker 部署资产
- 历史算法包 `csrcqsf/biz/reconstruction`

### Reconstruction Service Repo

`/home/ubuntu/project-train/reconstruction_server` 保留：

- `api.py`
- `api_models.py`
- `celery_app.py`
- `tasks.py`
- `pipeline_v2.py`
- `pipelineManager.py`
- `convert.py`
- `requirements.txt`
- `redis.conf`
- `start_services.sh`
- `stop_services.sh`
- `docs/`
- `tests/`
- 运行目录约定 `data/`、`output/`、`logs/`

是否保留运行产物本身取决于当前目录内容清理策略，但这些目录边界归属重构服务仓，不再归主业务仓。

### Algorithm Research Repo

`/home/ubuntu/project-train/reconstruction` 保持现状，不参与任何文件搬运和依赖变更。

## Repository Strategy

### Main Repo Side

主仓需要做两件事：

1. 删除 `gitlink`：
   - 移除 `csrcqsf/biz/railwayparts/reconstruction_server` 的索引记录
   - 确保主仓不再把它当作子仓路径跟踪

2. 删除废弃算法目录：
   - 删除 `csrcqsf/biz/reconstruction`
   - 删除所有只为该目录服务的测试、脚本和引用

### Reconstruction Repo Side

目标目录 `/home/ubuntu/project-train/reconstruction_server` 需要满足：

- 如果目标目录不存在，则通过整体移动当前嵌套仓得到
- 如果目标目录已存在且非空，则中止迁移，避免覆盖
- 默认保留原 `.git` 历史
- 迁移后可根据需要补充新的 remote / branch 约定，但这不属于本次主目标

## Code and Asset Migration Scope

### A. 从主仓迁出的内容

以下内容迁出到独立仓或跟随独立仓维护：

- `csrcqsf/biz/railwayparts/reconstruction_server/**`
- `docker/reconstruction-server/Dockerfile`
- `scripts/deployment/run_reconstruction_server.sh`
- 主仓中仅服务于重构服务实现的脚本与说明文档

原则：

- 凡是“部署重构服务本身”的资产，都应归属 `reconstruction_server` 仓
- `recognition` 不再负责打包或启动 GPU 重构服务

### B. 在主仓删除的内容

以下内容从 `recognition` 删除：

- `csrcqsf/biz/reconstruction/**`
- `scripts/reconstruction/3d_reconstruction.py`
- `tests/test_mask.py`
- 所有直接 import `csrcqsf.biz.reconstruction.*` 的测试和脚本

删除依据：

- 该目录已不参与主业务线上运行链路
- 继续保留只会误导代码边界

### C. 在主仓保留但需改写的内容

以下内容继续保留，但必须改为“外部服务视角”：

- `README.md`
- `部署文档.md`
- `csrcqsf/services/parts.py` 中涉及 `reconstruction_server/data/...` 的说明性注释
- 与 `RECONSTRUCTION_SERVER_URL` 有关的环境变量说明

改写原则：

- 主仓只描述“如何连接重构服务”
- 不再描述“如何在主仓内部启动重构服务目录”

## Test Strategy

### Main Repo Keeps

主仓保留以下测试类型：

- 主业务重构接口 contract 测试
- `reconstruction_client` 远端调用测试
- `reconstruction_manager` 状态映射与业务落库测试
- `scheduler` 重构状态同步测试
- `RECONSTRUCTION_SERVER_URL` 缺失时的禁用行为测试

### Main Repo Removes or Rehomes

以下测试不应继续留在 `recognition`：

- 直接 import `csrcqsf.biz.railwayparts.reconstruction_server.api`
- 直接 import `...reconstruction_server.tasks`
- 依赖 `reconstruction_server/data`
- 依赖 `reconstruction_server/output`
- Celery / Redis / Flower 的本地联调脚本
- turntable 原型和诊断脚本

这些测试要么：

- 移到 `/home/ubuntu/project-train/reconstruction_server`

要么：

- 直接删除，如果已经没有持续价值

## Deployment and Documentation Rules

### Recognition Repo

主仓文档只保留以下部署认知：

- 主业务服务可以独立部署
- 如果要使用三维重构能力，需要额外部署独立的 `reconstruction_server`
- 主业务通过 `RECONSTRUCTION_SERVER_URL` 与其通信

### Reconstruction Server Repo

独立仓负责自己的：

- API 启动方式
- Redis / Celery / Flower 启动方式
- Dockerfile
- 日志目录
- 数据目录
- 输出目录
- 故障排查文档

## Migration Sequence

建议迁移顺序如下：

1. 写入新 spec 和 plan
2. 先更新主仓中所有路径级引用与测试边界
3. 迁出 `reconstruction_server` 到目标目录
4. 从主仓删除 `gitlink`
5. 在新目录验证独立仓可运行
6. 删除主仓中的 `csrcqsf/biz/reconstruction`
7. 跑主仓测试
8. 跑重构服务仓测试
9. 更新文档

这个顺序的重点是：

- 先切断主仓对内嵌目录的依赖
- 再做物理迁移
- 最后清理历史算法包

## Risks

### 1. 目标目录冲突

如果 `/home/ubuntu/project-train/reconstruction_server` 已存在非空目录，直接迁移会覆盖风险极高，必须中止并人工处理。

### 2. 主仓对子仓测试残留引用

如果未清理干净，主仓测试会继续假设 `reconstruction_server` 在仓内，导致 CI / 本地测试失败。

### 3. 文档误导

如果主仓文档仍保留“进入 `csrcqsf/biz/railwayparts/reconstruction_server` 启动服务”的说明，会让部署人员走错路径。

### 4. 历史算法目录误删连带

`csrcqsf/biz/reconstruction` 的删除必须以“无主业务运行时 import”为前提，只清理主业务不再使用的部分，不触碰 `/home/ubuntu/project-train/reconstruction`。

## Success Criteria

迁移完成后，应满足以下结果：

1. `recognition` 仓内不再存在 `csrcqsf/biz/railwayparts/reconstruction_server`
2. `/home/ubuntu/project-train/reconstruction_server` 可作为独立 git 仓存在
3. `recognition` 仓内不再存在 `csrcqsf/biz/reconstruction`
4. 主业务仍可通过 `RECONSTRUCTION_SERVER_URL` 正常提交和同步重构任务
5. 主业务对前端的三维重构接口 contract 不变
6. 主仓测试不再直接依赖重构服务代码目录
7. 文档中不再把重构服务描述为主仓内部子目录
