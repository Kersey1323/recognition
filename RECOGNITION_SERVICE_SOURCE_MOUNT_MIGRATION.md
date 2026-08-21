# Recognition 主服务业务源码单挂载点改造说明

## 1. 改造目标

将 Recognition 主服务的业务源码收拢到现有 `csrcqsf` Python 包中，使甲方部署平台只需维护一个业务源码挂载点。

完成首次结构改造并发布基线镜像后，普通接口、数据库查询、同步流程、检索流程和任务管理逻辑发生变化时，只需完整替换宿主机上的 `csrcqsf` 目录并重启容器，不再重复传输完整 Python 依赖镜像。

目标挂载关系：

```text
甲方宿主机
├── csrcqsf/        ───────────────────────> /app/csrcqsf:ro
├── logs/           ───────────────────────> /app/logs
├── temp/           ───────────────────────> /app/temp
└── state/          ───────────────────────> /app/state

容器镜像层
├── Python 和系统依赖
├── 第三方 Python 包
├── csrcqsf/                                # 基线业务代码，未挂载时回退
└── 其他系统文件
```

业务源码使用只读挂载；日志、临时文件和持久化状态分别使用可写挂载。数据库、MinIO、Milvus、小模型服务和三维重构服务仍通过环境变量连接，不放入业务源码目录。

## 2. 当前主服务状态

当前项目主要结构为：

```text
/app/
├── main.py
├── globals_vars.py
├── csrcqsf/
│   ├── core/
│   ├── infra/
│   ├── models/
│   └── modules/
├── pyproject.toml
├── uv.lock
└── ...
```

当前镜像启动配置为：

```text
WorkingDir=/app
Cmd=["python", "main.py"]
```

当前不能直接只挂载 `/app/csrcqsf`，原因有三点：

1. 启动入口仍位于 `/app/main.py`；
2. 多个业务模块依赖根目录 `/app/globals_vars.py`；
3. `globals_vars.py` 会根据源码位置创建日志、缓存、模型和临时目录，只读挂载后会写入失败。

直接将宿主机项目目录挂载到 `/app` 会遮盖镜像中的依赖安装元数据和其他文件，不应作为正式方案。

因此，主服务同样需要先完成一次源码收拢，并发布新的基线镜像。

## 3. 收拢边界

### 3.1 应纳入业务挂载点

完整交付以下目录：

```text
csrcqsf/
├── __init__.py
├── __main__.py
├── core/
├── infra/
│   └── db/migrations/
├── models/
└── modules/
    ├── doc_parse/
    ├── image/
    ├── railway_parts/
    └── sgo/
```

除 Python 文件外，包内运行所需配置文件也必须整体交付，例如：

```text
csrcqsf/modules/railway_parts/vector_search/config/vector_db.ini
```

业务包包含的主要职责：

- FastAPI 应用、路由、中间件和异常处理；
- 配件、图片、检索历史和校验清单业务；
- SGO 配件、图片和询码历史同步；
- MySQL、Kingbase、MinIO 和 Milvus 访问逻辑；
- 索引构建、任务持久化、进度查询和恢复逻辑；
- 小模型服务和三维重构服务客户端；
- 主库建表、兼容迁移和迁移脚本。

### 3.2 不应纳入业务挂载点

- Python、系统包和第三方依赖；
- `.env`、数据库密码、MinIO 密钥和 SGO 凭证；
- Patch Tokens、索引检查点和任务运行状态；
- 日志、临时上传文件和缓存；
- Dockerfile、容器启动脚本和健康检查配置；
- 模型权重、CUDA、PyTorch 和三维重构算法环境；
- 本地测试数据、导出的镜像 tar 包和开发虚拟环境。

## 4. Python 入口和日志配置收拢

### 4.1 包入口

将当前根目录 `main.py` 的启动逻辑迁移到：

```text
csrcqsf/__main__.py
```

容器统一使用包入口启动：

```bash
python -m csrcqsf
```

入口内部继续导入：

```python
from csrcqsf.core.app import app
```

首次发布的新镜像不再保留根目录 `main.py` 兼容入口，避免镜像代码和挂载代码形成两套启动路径。

### 4.2 全局日志配置

将 `globals_vars.py` 中仍在使用的日志和运行目录配置迁入包内，例如：

```text
csrcqsf/core/logging_config.py
csrcqsf/core/runtime_paths.py
```

原有导入：

```python
from globals_vars import logger
```

统一改为：

```python
from csrcqsf.core.logging_config import logger
```

迁移完成后删除根目录 `globals_vars.py`，业务代码不得继续依赖源码挂载点外的项目模块。

## 5. 运行目录外置

源码挂载为只读后，所有运行时写入必须离开 `/app/csrcqsf`。

建议固定以下容器内路径：

| 内容 | 容器路径 | 权限 |
| --- | --- | --- |
| 应用日志 | `/app/logs` | 读写 |
| 临时文件 | `/app/temp` | 读写 |
| Patch Tokens | `/app/state/vector_db/patch_tokens` | 读写、持久化 |
| 索引检查点 | `/app/state/vector_db/checkpoint.json` | 读写、持久化 |
| 三维重构上传状态 | `/app/state/reconstruction` | 读写、持久化 |

对应环境变量建议明确使用绝对路径：

```env
APP_LOG_DIR=/app/logs
TEMP_DIR=/app/temp
STATE_DIR=/app/state
DINOV2_PATCH_TOKENS_DIR=/app/state/vector_db/patch_tokens
INDEXING_CHECKPOINT_FILE=/app/state/vector_db/checkpoint.json
INDEXING_LOG_DIR=/app/logs/vector_db
```

需要同步修正以下隐式路径：

- `globals_vars.py` 中基于 `PROJECT_ROOT` 创建目录的逻辑；
- `vector_search/config/env_config.py` 中相对项目根目录解析状态文件的逻辑；
- `vector_search/utils/logger.py` 中默认日志目录；
- 三维重构本地上传状态目录；
- 任何通过当前工作目录解析 `logs/`、`temp/` 或 `state/` 的代码。

服务启动时只允许创建 `/app/logs`、`/app/temp` 和 `/app/state` 下的目录，不能在 `/app/csrcqsf` 内创建文件。

## 6. 环境变量加载

生产环境使用部署平台环境变量或 `--env-file` 注入配置，不应从业务源码挂载目录读取 `.env`。

需要移除或限制以下隐式行为：

- `find_dotenv()` 自动向父目录查找 `.env`；
- 按源码目录固定加载 `.env`；
- 在业务压缩包中附带真实密码和访问密钥。

本地开发仍可显式加载项目根目录 `.env`，但生产容器应以外部注入的环境变量为准。

## 7. 运行时挂载来源日志

服务每次启动时，将业务源码来源追加记录到：

```text
/app/logs/source_mount.log
```

建议记录：

```json
{
  "timestamp": "2026-08-21T01:23:45.678901+00:00",
  "event": "source_mount_resolution",
  "service": "recognition-service",
  "source_type": "external-mount",
  "container_path": "/app/csrcqsf",
  "resolved_path": "/app/csrcqsf",
  "host_path": "/data/recognition-service/csrcqsf",
  "mount_root": "/data/recognition-service/csrcqsf",
  "filesystem": "ext4",
  "mount_source": "/dev/sdb1",
  "pid": 42,
  "argv": ["-m", "csrcqsf"]
}
```

`source_type`：

| 值 | 含义 |
| --- | --- |
| `external-mount` | 当前运行宿主机挂载的业务源码 |
| `image-layer` | 未检测到独立挂载，当前运行镜像内基线代码 |

建议环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RECOGNITION_MAIN_LOG_DIR` | `/app/logs` | 挂载来源日志目录 |
| `RECOGNITION_MAIN_SOURCE_LOG_ENABLED` | `1` | 是否记录源码来源 |
| `RECOGNITION_MAIN_SOURCE_CONTAINER_PATH` | `/app/csrcqsf` | 容器内业务包路径 |
| `RECOGNITION_MAIN_SOURCE_HOST_PATH` | 空 | 宿主机业务包路径，仅用于日志定位 |
| `RECOGNITION_MAIN_MOUNTINFO_PATH` | `/proc/self/mountinfo` | Linux 挂载信息文件 |

挂载识别失败或日志目录不可写时只记录警告，不能阻断 API 启动。

## 8. Dockerfile 改造

基线镜像必须保留一份能够独立启动的 `csrcqsf`，外部挂载只在运行时覆盖同名目录。

示意配置：

```dockerfile
WORKDIR /app

COPY pyproject.toml uv.lock README.md /app/

RUN uv venv "${VIRTUAL_ENV}"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --active --no-dev --no-install-project

COPY csrcqsf/ /app/csrcqsf/

RUN mkdir -p \
    /app/logs/vector_db \
    /app/temp \
    /app/state/vector_db/patch_tokens \
    /app/state/reconstruction

CMD ["python", "-m", "csrcqsf"]
```

业务包由源码路径直接导入，不再依赖把当前项目以 editable package 安装到虚拟环境中。这样外部挂载 `/app/csrcqsf` 后，Python 会直接使用挂载版本。

## 9. 部署挂载配置

### 9.1 Docker 命令示例

```bash
docker run -d \
  --name recognition-service \
  --restart unless-stopped \
  --network host \
  --env-file /data/recognition-service/.env.deployment \
  -e RECOGNITION_MAIN_SOURCE_HOST_PATH=/data/recognition-service/csrcqsf \
  -v /data/recognition-service/csrcqsf:/app/csrcqsf:ro \
  -v /data/recognition-service/logs:/app/logs \
  -v /data/recognition-service/temp:/app/temp \
  -v /data/recognition-service/state:/app/state \
  recognition-service:<基线版本>
```

若不使用 host 网络，则改为：

```bash
-p 65432:65432
```

### 9.2 部署平台路径映射

| 宿主机路径 | 容器路径 | 权限 |
| --- | --- | --- |
| `/data/recognition-service/csrcqsf` | `/app/csrcqsf` | 只读 |
| `/data/recognition-service/logs` | `/app/logs` | 读写 |
| `/data/recognition-service/temp` | `/app/temp` | 读写 |
| `/data/recognition-service/state` | `/app/state` | 读写 |

环境变量文件单独管理，不放入 `csrcqsf` 目录，也不通过业务源码压缩包交付。

## 10. 数据库迁移和后台任务注意事项

### 10.1 数据库迁移

Recognition 启动时会执行主业务库迁移。替换业务源码并重启前必须确认：

- 新旧代码均可兼容迁移后的数据库结构；
- 新增字段优先使用可空字段或安全默认值；
- 删除字段、修改字段类型和批量数据修复不能作为普通源码热更新直接执行；
- Kingbase 和 MySQL 的兼容 SQL 必须分别验证；
- 数据库迁移失败时应阻止服务启动并保留完整错误日志。

源码回滚不会自动回滚数据库。涉及不可逆数据库变更时，必须单独准备数据库备份和回滚脚本。

### 10.2 后台任务

替换源码前应确认没有正在运行的任务：

- SGO 配件、图片和询码历史同步任务；
- 批量索引构建任务；
- 三维重构上传或结果同步任务。

容器停止后，进程内任务会终止。索引重建任务有数据库持久化和恢复逻辑，但 SGO 同步任务当前主要保存在进程内，重启后不会从原进度自动续跑。

## 11. 后续业务代码更新流程

完成基线镜像发布后，普通业务更新流程为：

1. 开发方完成单元测试和接口回归；
2. 检查本次变更是否新增依赖或包含数据库迁移；
3. 将完整 `csrcqsf` 目录打包，不交付零散文件；
4. 生成 SHA-256 和变更说明；
5. 甲方确认没有正在运行的长任务；
6. 停止现有容器；
7. 备份当前宿主机 `csrcqsf` 目录；
8. 完整替换为新版本目录；
9. 启动容器并检查启动日志；
10. 执行健康检查和关键接口冒烟测试。

容器运行期间不要直接覆盖 Python 文件，避免同一进程同时持有旧模块对象和新磁盘文件。

建议交付物：

```text
csrcqsf-<业务版本>.tar.gz
SHA256SUMS
CHANGELOG.md
MIGRATION_NOTES.md      # 存在数据库变化时提供
```

## 12. 验收方法

### 12.1 健康检查

```bash
curl -fsS http://127.0.0.1:65432/health
```

### 12.2 检查实际导入路径

```bash
docker exec recognition-service \
  python -c 'import csrcqsf; print(csrcqsf.__file__)'
```

预期：

```text
/app/csrcqsf/__init__.py
```

### 12.3 检查挂载关系

```bash
docker inspect recognition-service \
  --format '{{range .Mounts}}{{println .Source "->" .Destination .Mode}}{{end}}'
```

必须看到源码、日志、临时目录和状态目录四个挂载关系。

### 12.4 检查源码来源日志

```bash
tail -n 5 /data/recognition-service/logs/source_mount.log
```

验收条件：

- `service` 为 `recognition-service`；
- `source_type` 为 `external-mount`；
- `container_path` 为 `/app/csrcqsf`；
- `host_path` 与甲方实际目录一致；
- 重启后产生带有新 `pid` 的记录。

### 12.5 检查可写目录

```bash
docker exec recognition-service sh -c \
  'test -w /app/logs && test -w /app/temp && test -w /app/state'
```

同时确认 `/app/csrcqsf` 为只读，服务运行期间没有在源码目录生成日志、缓存或状态文件。

### 12.6 关键业务冒烟测试

至少验证：

- `/health`；
- Swagger/OpenAPI；
- 配件列表和详情；
- 图片检索和检索历史详情；
- 索引任务创建、状态查询和取消；
- SGO 数据库查询及图片同步；
- MinIO 文件代理；
- 三维重构服务转发。

## 13. 自动化测试最低范围

- `python -m csrcqsf` 可正常启动；
- 根目录 `main.py` 和 `globals_vars.py` 已不再被业务代码引用；
- 挂载源码时导入路径指向 `/app/csrcqsf`；
- 未挂载时可回退到镜像内基线代码；
- 只读源码目录下服务可正常启动和处理请求；
- 日志、临时文件和状态数据只写入指定外部目录；
- `mountinfo` 可区分 `external-mount` 和 `image-layer`；
- 日志目录不可写时只警告，不阻断启动；
- 主库迁移、MinIO bucket 初始化和索引任务恢复仍按顺序执行；
- MySQL 和 Kingbase 两种 SGO 数据库配置均可完成关键查询；
- 真实容器挂载启动后健康检查通过。

## 14. 仍需重新构建镜像的情况

以下变化不能只替换 `csrcqsf`：

- 修改 `pyproject.toml` 或 `uv.lock`；
- 新增、删除或升级 Python 依赖；
- 修改 Python 版本或系统依赖；
- 新增编译扩展或原生动态库；
- 修改 Dockerfile、启动命令、工作目录或健康检查；
- 修改业务挂载点之外的镜像文件；
- 修改持久化目录或部署平台挂载结构。

在现有依赖范围内修改 API、数据库查询、同步逻辑、响应结构、检索流程、任务管理或外部服务调用时，只需交付完整 `csrcqsf` 目录。

## 15. 回滚方式

业务源码挂载提供两级回滚：

1. 恢复宿主机上一个已验证的 `csrcqsf` 完整目录并重启容器；
2. 临时移除 `/app/csrcqsf` 挂载，让容器回退到镜像内基线代码。

回滚后必须重新检查健康接口、源码来源日志和关键业务接口。

数据库结构不会随源码回滚自动恢复。若本次更新执行了不可逆迁移，必须使用对应数据库回滚方案，不能只回退 Python 源码。

## 16. 推荐实施顺序

1. 在 `csrcqsf/__main__.py` 建立包启动入口；
2. 将 `globals_vars.py` 的有效职责迁入 `csrcqsf/core`；
3. 替换所有根模块导入并删除旧入口和旧全局配置；
4. 将日志、临时文件和状态路径全部外置；
5. 调整生产环境变量加载方式，不再依赖源码目录 `.env`；
6. 增加源码挂载来源日志和单元测试；
7. 修改 Dockerfile，以 `python -m csrcqsf` 启动；
8. 使用只读源码挂载启动真实容器；
9. 验证数据库迁移、MinIO、Milvus、SGO、小模型和重构服务连接；
10. 构建并交付首个支持单业务挂载点的基线镜像；
11. 更新甲方部署平台路径映射和更新流程；
12. 后续普通业务版本只交付完整 `csrcqsf` 目录。

首次改造必须重新构建镜像，因为旧镜像仍执行 `/app/main.py`，并依赖 `/app/globals_vars.py`。只有新镜像已经使用包入口、外置运行目录并内置基线 `csrcqsf` 后，单目录源码挂载和轻量业务更新流程才正式生效。
