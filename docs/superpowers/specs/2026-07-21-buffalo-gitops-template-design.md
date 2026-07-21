# Buffalo Platformized CI/CD and GitOps Automation Design

## Goal

把当前 Buffalo 本地实验环境升级成一个更接近公司平台的形态，使“新项目接入并发版到 K8s”尽量收敛到统一平台能力，而不是每个项目自己拼一套 CI/CD 与 GitOps 脚本。

本设计的最终目标是：

- 新项目不手工创建 `app.yaml`
- 业务仓库不存放平台部署脚本
- 新项目目标形态下不保留 `.gitlab-ci.yml`
- 应用名、镜像名、域名、端口、健康检查、持久化目录都自动推导
- Argo CD 自动发现新应用并部署到 K8s

本设计覆盖四件事：

1. 业务仓库与平台仓库的职责边界
2. 平台 CI 仓库的模板与脚本组织方式
3. GitOps 仓库的自动 bootstrap 与自动更新机制
4. Argo CD 从“手工单应用”切换到 `ApplicationSet` 自动发现模式

## Non-Goals

本设计暂时不解决这些问题：

- 非 HTTP 服务类工作负载的统一接入
- Helm 之外的复杂编排方式
- 项目测试命令的完全标准化
- 从 GitLab Variables 自动生成业务级 `ConfigMap` 和 `Secret`
- 多集群、多环境、多租户发布拓扑

这些方向可以在平台形态稳定后再单独设计。

## Current State

当前环境已经具备这些基础能力：

- `gitlab.buffalo.com` 可访问自建 GitLab
- `argocd.buffalo.com` 可访问 Argo CD
- `xi-cicd-test.buffalo.com` 已成功由 K3d/K8s 提供服务
- `recognition` 已具备构建镜像、推送镜像、更新 GitOps 仓库的基础流水线

当前痛点也很明确：

1. `app.yaml` 需要预先存在，首次接入仍然是人工动作
2. `update_gitops_repo.sh`、`extract_runtime_metadata.sh` 之类的平台脚本放在业务仓库里，不可扩展
3. `.gitlab-ci.yml` 当前仍由业务仓库持有，平台升级需要逐仓修改
4. Argo `ApplicationSet` 的目标结构已经设计出来，但尚未真正部署到集群
5. 当前 `cicd-test` 仍依赖手工创建的 Argo `Application`

## Design Principles

1. 业务仓库只负责业务代码与运行时契约
2. 平台仓库统一负责 CI/CD 与 GitOps 自动化
3. 首次发版就是首次注册，不额外做人手初始化
4. 能从 GitLab 元数据推导的字段，不允许手工重复填写
5. 能从 `Dockerfile` 推导的运行时契约，不允许写第二份
6. 平台默认值优先，人工只写少量例外 override
7. 切换方案必须兼容现有 `cicd-test`，不能靠大爆炸重建

## Approach Options

### Option A: 业务仓库保留超薄 `.gitlab-ci.yml`，平台模板通过 `include` 注入

做法：

- 每个业务仓库保留一个极薄的 `.gitlab-ci.yml`
- 文件内容只做 `include` 到平台 CI 仓库
- 平台脚本与模板统一在外部仓库维护

优点：

- 迁移成本低
- 和当前 GitLab 使用习惯最接近
- 不需要额外配置项目设置即可生效

缺点：

- 新项目仍然需要至少落一个 `.gitlab-ci.yml`
- 平台层仍然有一份“接入文件”散落在每个仓库

结论：

- 可作为兼容过渡方案

### Option B: 业务仓库无 `.gitlab-ci.yml`，项目设置直接指向外部平台 CI 配置

做法：

- 新项目默认不提交 `.gitlab-ci.yml`
- 在 GitLab 项目 `Settings > CI/CD` 中把 `CI/CD configuration file` 指向平台仓库模板
- 如果具备实例管理员权限，则为新项目设置默认 CI 配置路径
- 平台脚本、GitOps 回写、镜像构建逻辑全部在平台仓库中维护

优点：

- 最贴近公司式平台
- 业务仓库最干净
- 平台升级一次即可影响所有接入项目

缺点：

- 需要项目设置或实例默认设置配合
- 老项目迁移时需要额外切换 CI 配置来源

结论：

- 推荐方案

### Option C: 平台长期运行一个注册服务，CI 只发 API

做法：

- CI 不直接改 GitOps 仓库
- 发版时调用平台 API
- 平台服务统一处理应用注册、GitOps 回写、部署跟踪

优点：

- 自动化最彻底
- 最方便做权限隔离、审计和多环境扩展

缺点：

- 引入一个新长期在线服务
- 对当前本地实验环境来说过重

结论：

- 不作为本轮实现

## Chosen Design

采用 **Option B**，并保留 **Option A** 作为老项目兼容路径。

也就是说：

- 新项目目标形态：业务仓库无 `.gitlab-ci.yml`
- 老项目兼容形态：保留超薄 `include` 文件，后续再迁出

## Final Architecture

平台拆成三个仓库层级和一个集群内平台引导应用：

1. 业务仓库
2. 平台 CI 仓库
3. GitOps 仓库
4. Argo 平台引导 Application

### 1. Business Repo Responsibilities

业务仓库只保留这些内容：

- 业务代码
- `Dockerfile`
- `Dockerfile.vendor`
- 项目测试代码与测试脚本
- 项目文档与示例环境变量

业务仓库不再保留这些平台资产：

- `k8s/`
- `argocd/`
- GitOps 回写脚本
- 平台通用部署 YAML
- 平台生成逻辑

业务仓库最终只回答两个问题：

1. 这个项目如何构建
2. 这个项目运行时暴露什么契约

### 2. Platform CI Repo

新增一个专门的 CI 平台仓库，例如 `xi/buffalo-ci`。

建议目录结构：

```text
buffalo-ci/
├── templates/
│   └── vendor-service.yml
├── scripts/
│   ├── runtime/
│   │   └── extract_metadata.sh
│   └── gitops/
│       ├── bootstrap_app.sh
│       ├── ensure_manifests_skeleton.sh
│       ├── render_app_descriptor.py
│       ├── update_app_descriptor.sh
│       └── wait_for_rollout.sh
└── docs/
```

职责划分：

- `vendor-service.yml`
  - 定义统一的 `verify / image / deploy / verify-deploy` 流水线
- `extract_metadata.sh`
  - 从 `Dockerfile` 提取运行时契约
- `bootstrap_app.sh`
  - 首次发版时自动创建 `apps/<app>/` 骨架
- `update_app_descriptor.sh`
  - 更新镜像 tag 和 `generated` 区域
- `wait_for_rollout.sh`
  - 发布后等待 Argo/K8s 进入可用状态

### 3. GitOps Repo

`gitops-demo` 调整为真正的共享平台布局：

```text
gitops-demo/
├── apps/
│   └── <app>/
│       ├── app.yaml
│       └── manifests/
│           └── kustomization.yaml
├── argocd/
│   ├── applicationset.yaml
│   └── buffalo-platform.yaml
└── platform/
    └── charts/
        └── buffalo-http-service/
```

其中：

- `platform/charts/buffalo-http-service`
  - 承载共享 `Namespace / Deployment / Service / Ingress / PVC` 模板
- `apps/<app>/app.yaml`
  - 每个应用唯一声明文件
- `apps/<app>/manifests/`
  - 少量项目专属资源目录，例如额外 `ConfigMap`、`Secret`
- `argocd/applicationset.yaml`
  - 自动发现 `apps/*/app.yaml`
- `argocd/buffalo-platform.yaml`
  - 平台引导 Application，只同步 `argocd/` 目录

### 4. Argo Platform Bootstrap App

集群内不再让某个业务应用承担引导角色。

新增一个平台级 Argo Application：

- 名称：`buffalo-platform`
- 作用：同步 `gitops-demo/argocd/`
- 它不部署任何业务项目
- 它只保证 `ApplicationSet` 和平台级 Argo 配置存在

## Runtime Contract Source of Truth

运行时契约统一以 `Dockerfile` 为准，而不是再在 GitOps 仓库里重复写一份。

平台从 `Dockerfile` 推导这些字段：

- `EXPOSE` -> `containerPort`
- `HEALTHCHECK` -> `healthPath`
- `VOLUME /app/...` -> `appDataDirs`

这意味着：

- `Dockerfile` 负责运行时契约
- `Dockerfile.vendor` 负责发版构建包装
- `app.yaml` 只是平台消费的部署声明，不是人工运行时说明书

## GitLab Metadata Derivation

平台不允许在 CI 变量里硬编码 `recognition` 这种项目名。

统一从 GitLab 预定义变量自动推导：

- `APP_NAME = $CI_PROJECT_NAME`
- `PROJECT_SLUG = $CI_PROJECT_PATH_SLUG`
- `GROUP_SLUG = slug($CI_PROJECT_ROOT_NAMESPACE)`；若该变量不可用，则回退到 `slug($CI_PROJECT_NAMESPACE)` 的最后一级
- `GITOPS_BRANCH = $CI_DEFAULT_BRANCH`

镜像相关字段按统一规则生成：

```yaml
DOCKER_IMAGE_NAME: "${CI_PROJECT_NAME}:${CI_COMMIT_SHORT_SHA}"
PUSH_REGISTRY_IMAGE: "localhost:5000/${CI_PROJECT_PATH_SLUG}:${CI_COMMIT_SHORT_SHA}"
PUSH_REGISTRY_IMAGE_LATEST: "localhost:5000/${CI_PROJECT_PATH_SLUG}:latest"
K8S_REGISTRY_IMAGE: "cicd-test-registry:5000/${CI_PROJECT_PATH_SLUG}:${CI_COMMIT_SHORT_SHA}"
```

使用 `CI_PROJECT_PATH_SLUG` 而不是只用项目名，是为了避免不同 group 下同名仓库冲突。

关于外置 CI 配置与预定义变量，本设计依赖 GitLab 官方支持：

- 自定义外部 CI 配置文件：
  - [Customize pipeline configuration](https://docs.gitlab.com/ci/pipelines/settings/)
- GitLab Self-Managed 实例级 CI/CD 设置：
  - [CI/CD settings](https://docs.gitlab.com/administration/settings/continuous_integration/)
- 预定义变量参考：
  - [Predefined CI/CD variables](https://docs.gitlab.com/ci/variables/predefined_variables/)

## CI Configuration Ownership

### Target State

新项目默认不提交 `.gitlab-ci.yml`。

项目设置中的 `CI/CD configuration file` 直接指向平台仓库模板，例如：

```text
templates/vendor-service.yml@xi/buffalo-ci
```

如果具备实例管理员权限，则为新项目配置默认外置 CI 路径，减少逐项目手工设置。

### Compatibility State

对于已存在项目，允许暂时保留一个极薄的 `.gitlab-ci.yml`：

```yaml
include:
  - project: 'xi/buffalo-ci'
    ref: master
    file: '/templates/vendor-service.yml'
```

等平台稳定后，再迁出到项目设置。

## App Descriptor Model

每个应用在 GitOps 仓库里只保留一份 `apps/<app>/app.yaml`。

文件结构固定为两段：

- `generated`
  - 平台 CI 自动维护
- `overrides`
  - 人工维护的少量例外配置

示例：

```yaml
generated:
  appName: "recognition"
  group: "xi"
  host: "xi-recognition.buffalo.com"
  image:
    repository: "cicd-test-registry:5000/xi-recognition"
    tag: "fc3eab5c"
  runtime:
    containerPort: 65432
    healthPath: "/health"
    appDataDirs:
      - "logs"
      - "temp"
      - "state"

overrides:
  replicas: 1
  config:
    configMaps: []
    secrets: []
```

关键约束：

- `generated` 不允许人工维护
- `overrides` 不写默认值，只写偏离默认值的例外项

## First Release Bootstrap

首次发版时，平台自动完成应用注册，不再要求人工预建目录或文件。

`gitops-bootstrap` 阶段做这些事情：

1. 读取 GitLab 项目元数据
2. 读取 `Dockerfile` 运行时契约
3. 克隆 GitOps 仓库
4. 如果 `apps/<app>/` 不存在，则自动创建：
   - `apps/<app>/app.yaml`
   - `apps/<app>/manifests/kustomization.yaml`
5. 写入默认 `overrides`
6. 提交并推送到 GitOps 仓库

这意味着：

- `app.yaml` 不再需要手工创建
- 业务应用第一次发版就是第一次注册

## Repeated Release Update

非首次发版时，平台执行 `gitops-update`：

1. 更新 `generated.image.tag`
2. 如运行时契约变化，同步更新：
   - `host`
   - `containerPort`
   - `healthPath`
   - `appDataDirs`
3. 保留已有 `overrides`
4. 提交回 GitOps 仓库

平台脚本必须支持“文件不存在时 bootstrap，文件存在时 update”，而不是像当前实现那样要求 `app.yaml` 必须提前存在。

## ApplicationSet Auto-Discovery

`ApplicationSet` 是“自动进 K8s”成立的关键。

目标链路是：

1. CI 把 `apps/<app>/app.yaml` 写入 GitOps 仓库
2. `ApplicationSet` 自动发现 `apps/*/app.yaml`
3. 为每个 app 生成一个 Argo `Application`
4. `Application` 消费共享 Helm Chart 与 app 专属 `manifests/`
5. K8s 渲染并拉起 `Namespace / Deployment / Service / Ingress / PVC`

如果 `ApplicationSet` 未部署，则 GitOps 仓库虽然被更新，但新项目不会自动进入 K8s。

## Shared Chart Responsibilities

共享 Chart `buffalo-http-service` 负责这些平台默认资源：

- `Namespace`
- `Deployment`
- `Service`
- `Ingress`
- `PVC`

默认值建议：

- `namespace = appName`
- `servicePort = 80`
- `replicas = 1`
- `host = <group>-<appName>.buffalo.com`
- `image.repository = cicd-test-registry:5000/<project-slug>`

项目专属 `manifests/` 只负责少量额外资源，不允许再次定义平台默认对象，避免和共享 Chart 职责重叠。

## Verify Stage Scope

本设计只平台化 build/release/deploy 这一层，不强制统一所有项目的测试命令。

因此 `verify` 阶段采用两级模式：

1. 平台统一骨架
   - 提供 `verify` stage
   - 统一缓存、基础镜像、公共工具
2. 业务仓库自定义 hook
   - 可选 `scripts/ci/lint.sh`
   - 可选 `scripts/ci/test.sh`
   - 如果不存在，则对应 job 可跳过或 no-op

这样业务测试逻辑仍归业务仓库管理，但部署自动化完全由平台接管。

## Deployment Verification

为了避免“CI 成功但集群没动静”，平台应增加发布后验证。

`deploy-verify` 做两类检查：

1. GitOps 层检查
   - `apps/<app>/app.yaml` 是否已经是本次镜像 tag
2. 集群层检查
   - 对应 `Application` 是否已创建
   - Argo 状态是否 `Synced`
   - 健康状态是否 `Healthy`
   - 可选地对 `http://<host>/<healthPath>` 做探测

首次发版时，该阶段需要等待 `ApplicationSet` 生成新应用，而不是假设应用对象立即存在。

## Migration Plan

### Phase 1: 平台仓库抽离

- 创建 `xi/buffalo-ci`
- 把业务仓库中的平台脚本迁出
- 去掉硬编码项目名变量

### Phase 2: GitOps 仓库收敛

- 保留共享 Chart
- 引入最终版 `ApplicationSet`
- 把当前 `argocd/cicd-test.yaml` 替换为平台引导应用 `argocd/buffalo-platform.yaml`

### Phase 3: Argo 切换

按这个顺序操作：

1. 部署 `buffalo-platform`
2. 确认 `ApplicationSet` 已存在
3. 删除旧的手工 `cicd-test` Application
4. 让 `ApplicationSet` 按 `apps/cicd-test/app.yaml` 自动重建业务 Application

这样可以避免手工 Application 与自动生成 Application 并存冲突。

### Phase 4: 迁移业务项目

- `cicd-test` 先迁到平台 CI 仓库
- `recognition` 作为第二个真实项目迁入
- 老项目先保留超薄 `.gitlab-ci.yml`
- 新项目直接走外置 CI 配置

### Phase 5: 新项目默认接入

- 为新项目设置默认外置 CI 配置路径
- 让“创建项目 -> 放代码和 Dockerfile -> `[vendor]` 发版”成为标准流程

## Risks and Mitigations

### Risk 1: 现有 `cicd-test` 中断

风险：

- Argo 切换时旧手工 `Application` 与新自动生成对象冲突

缓解：

- 先部署平台引导，再删除旧对象，再等待自动重建

### Risk 2: 自动推导不覆盖特殊项目

风险：

- 某些项目端口、健康检查、卷挂载约定不规范

缓解：

- 第一版支持少量 `overrides`
- 对 `Dockerfile` 约定不满足的项目，先修正项目运行时契约

### Risk 3: 外部 CI 配置迁移不彻底

风险：

- 新旧项目混用本地 CI 和外部 CI，平台行为不一致

缓解：

- 明确“新项目无 `.gitlab-ci.yml`，老项目临时兼容”的策略
- 收敛后逐步移除老项目的超薄 include 文件

### Risk 4: 项目需要大量环境变量

风险：

- 自动创建 `app.yaml` 不等于自动创建业务配置

缓解：

- 本轮先只自动化应用注册与标准部署对象
- 业务配置仍通过 `manifests/` 中的 `ConfigMap`/`Secret` 或后续专项设计解决

## Success Criteria

当下面条件同时满足时，说明本设计达成目标：

1. 新建业务仓库时不需要放平台脚本
2. 新建业务仓库时不需要提交 `.gitlab-ci.yml`
3. 首次 `[vendor]` 发版会自动创建 `apps/<app>/app.yaml`
4. `ApplicationSet` 自动为新应用生成 Argo `Application`
5. 新应用自动出现在 K8s 中并获得标准域名
6. 平台镜像名、域名、应用名不再有 `recognition` 这种硬编码

## Recommendation Summary

最终推荐的目标形态是：

- 业务仓库只保留业务代码、`Dockerfile`、`Dockerfile.vendor`
- GitLab 项目设置直接引用外部平台 CI 配置
- 平台 CI 仓库统一管理所有发版与 GitOps 自动化脚本
- GitOps 仓库由 CI 自动 bootstrap 新应用目录与 `app.yaml`
- Argo `ApplicationSet` 自动发现新应用并部署到 K8s

这条路线比当前方案多做了一层“平台归位”，但它解决了两个根本问题：

1. 不再把平台逻辑复制到每一个业务仓库
2. 不再让“首次接入”依赖人工创建 GitOps 描述文件
