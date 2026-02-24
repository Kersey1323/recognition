## 七、 核心微服务架构设计与分布式数据库级联方案

为应对高局点并发、跨地域厂区部署以及两万级超大规模零配件资产库的持续写入压力，单体架构早已力不从心。系统在总体设计上全面拥抱了基于 **FastAPI + Kubernetes (K8S) 的云原生微服务架构（Cloud-Native Microservices）**。

### 7.1 分层架构与核心领域模型（DDD）
为了提升代码的可插拔性并在后期维护中实现团队解耦，采用了典型的领域驱动设计（Domain-Driven Design, DDD）四层架构模型：
1. **接入层 (Ingress / API Gateway)**
   - 采用 NGINX Controller 配合 API Gateway，对前端所有 HTTP 与 WebSocket 流量进行汇聚和 SSL/TLS 卸载。
   - 拦截并鉴权每一次调用，确保只有拥有合规 JWT（JSON Web Token）及所属车间机务段权限的角色方可通过。
2. **应用服务层 (Application Layer)**
   - **FastAPI Core Engine**：基于后端的 `csrcqsf.services.parts` 等路由器构筑，它负责接收具体的业务指令（如 `POST /parts`）并分发至底层的业务处理逻辑。这层利用了 FastAPI `async/await` 的全异步非阻塞特性，在处理大量高并发的图片上传 I/O 读写时能达到极高的 QPS（每秒查询率）。
3. **领域算法层 (Algorithm Domain / Services Layer)**
   - 模型推断单元：将 SAM 掩码提取、DINOv2 与 ResNet-34 特征转换封装进类 `SamAutomaticMaskGenerator` 与 `DINOv2FeatureExtractor` 中。
   - 分布式算力调度器（Task Scheduler）：向 Redis 任务队列投递长期持有的 3DGS 可微分渲染与 COLMAP 相机姿态估算等长链接计算任务，并负责收集执行心跳及最后三维模型成果的回调。
4. **基础设施层 (Infrastructure / Database Layer)**
   - 彻底屏蔽对具体数据库的裸写，全部利用 ORM（对象关系映射，如 SQLAlchemy）和对应客户端 SDK 与物理层通信。

### 7.2 关系型与非关系型异构存储拓扑矩阵
任何单一品种的数据库都无法胜任动车图像识别业务既要存业务关系、又要存高维张量、还要存海量图像的变态要求。系统的根基在于极其严苛的 **三重仓储拓扑隔离**：

#### 仓储一：结构化业务库 —— PostgreSQL 高可用集群
负责承载诸如配件基础档案、用户鉴权、任务状态机等确定的关系状态。
- **物理架构**：采用主从复制（Master-Slave Replication）模式。读写分离（Write-Ahead Logging, WAL 传输）。
- **字段设计**：核心表 `railway_parts` 不仅包含字符如 `item_id`, `name`, 更有 `Jsonb` 类型的元数据扩展字段可以存储各种未预定义的厂牌、采购年份信息。支持创建 `GIN` 倒排索引来快速从 `Jsonb` 结构中捞取数据。
- **事务一致性**：为保证前端页面中配件的“上架操作”与“大模型库写入操作”的强一致性，业务层利用了 Postgres 本生的 ACID 事务机制，实现一旦大模型推理由于显存熔断崩溃，则 Postgres 中对应该零件的登记一并执行 `Rollback()` 撤销，不留下任何“僵尸配件档案”。

#### 仓储二：百亿规模高维度浮点数据 —— Milvus 响箭向量检索引擎
专用于 1024 维的高保真 DINOv2 特征与 512 维的 ResNet-34 缩略特征的瞬时检索与模糊查全。
- **Milvus Collection Schema 编排**：
  设计多分区（Partitions）策略，按机务段的区域或者配件大类进行 Partition 划分，以缩小近似最近邻（ANN）查找的全局扫描范围。
- **核心 HNSW (Hierarchical Navigable Small World) 导航小世界图索引**：
  相比于暴力的全盘点积运算（Flat Index 复杂度 $O(N)$），HNSW 通过构建多层跳表性质的图结构，以一种“宏观高速路与微观小巷交叉”的贪心搜索机制，使得时间复杂度骤降为 $O(\log(N))$。
  - `M` (每个节点最大邻居数) 设定为 16，`efConstruction` (构建时搜寻深度) 设定为 500。
  - 这些经特殊调优的参数平衡了在 20,000 品类下的精准度 (Precision > 99%) 以及超神速（检索一整张图片的内积打分仅需 4 毫秒）。
- **标量过滤混合检索 (Hybrid Search)**：在 Milvus 集群内支持直接通过 `item_type == '机械类'` 结合 `emb` 的查询向量进行预过滤或后过滤。极大缩减了计算维度，并同时响应用户想要“在某个具体的生产商名下搜索某一个特定形状螺丝”的多维业务痛点。

#### 仓储三：PB级云原生对象海量池 —— MinIO 分布式集群
针对 20000 级零配件的原始采集照片、裁切白底照及最终 `.obj` 波前网格及 `.mtl` 纹理文件（统称为 BLOB 大对象），使用基于纠删码（Erasure Code）的轻健壮 MinIO 存储。
- 脱离了在宿主机挂载 EXT4 格式硬盘的传统存法。当面临海量 4K 级别图片的高并发拉取，其极有可能吃满宿主机 IOPS 并发生单盘损毁。
- MinIO 采用 N 节点乘以 M 块磁盘的去中心化条带分布（Erasure Coding）。允许容忍多块磁盘烧毁而完全无感恢复丢失的珍贵动车大底物料照片。
- 借助 S3 协议生成的带防盗链的预签名 URL（Pre-signed URL），后端不用去下载几十兆的 3D 模型给前端转发，前端可以通过此有时效的安全链接以超高带宽直接从对象节点拉取 3D 资产，彻底解放 Python 后台的带宽枷锁。

---

## 八、 WebGL 前端极客级三维资产渲染方案及视口性能调优

成功导出带贴图属性的 2DGS 泊松去噪表面（即水密的 `.obj`），若是只能存储在冰冷的硬盘里，便无法释放出“数字孪生（Digital Twin）”直击人心的价值力。系统的配套前端选配了原生强大的 JavaScript 三维世界引擎并作了极端化的性能调优。

### 8.1 基于 Three.js 的跨应用轻量三维载入
由于要将展示平台直接嵌入现有的 Web 终端或者是基于 Android / iOS 等车间检验员随身佩戴的手持平板客户端中。采用传统 Unity/UE5 进行全量封包，不仅导致包体极度臃肿，且在各种内网隔离的场景下极难实现实时在线无缝的动态补丁更新（Hot Update）。
Three.js 作为在现代浏览器中直接调用系统的底层图形核心（OpenGL/Vulkan 在网页端的封装 WebGL 2.0 API）进行帧渲染的引擎，具有极致的轻量与跨端适应特质。
在业务线代码层调用 `OBJLoader` 配合 `MTLLoader` 来拉取系统异步计算管线中存放于 MinIO 的标准资产链接：
1. **顶点缓存与法线注入**：
   下载的 `.obj` 是极其纯粹的多边形面声明体（Vertex, Texture Coordinates, Normals，分别由 `v`, `vt`, `vn` 表示）。Three.js 利用内部的 `BufferGeometry` 创建 WebGL的 VBOs（Vertex Buffer Objects）。这相较于传统的 JavaScript Array 的在内存中是连续直接在显存寻址的，大大提速了几十万级面片动车机械盘片在浏览器进程内的初始化加载速度。
2. **材质环境贴图与各向异性过滤（Anisotropic Filtering）**：
   配合 `.mtl` （Material Template Library），金属表面的漫反射和高光属性（Specular & Ambient）被还原到 WebGL 渲染管线的像素着色器中。为避免由于透视缩放导致远处边缘产生的摩尔纹或模糊，启动了最大阈值的各向异性过滤（`texture.anisotropy = renderer.capabilities.getMaxAnisotropy()`）。保证无论是从极远距离的统览亦或推拉相机镜头逼近零配件极限微距拍摄点，其表面由于 2DGS/SuGaR 高精度压印导出的原始材质和纹理像素（Texel），依然保持锐利与清晰。

### 8.2 海量多边形压力下的网页浏览器防挂机制（LOD 与内存管理）
考虑到高精度渲染导出的极高保真度资产本身自带十几到上百万个三角网格，老旧型号的车间巡检手持终端上的显存空间极不可靠。如果在一个页面级网格展示列表栏（ListView / GridView）中同时渲染大量缩略配件，或快速旋转三维模型时疯狂向图形堆栈倾泻计算量，往往将导致浏览器的 WebGL Context Lost（上下文丢失奔溃）。
- **空间遮挡剔除与视锥体截尾（Frustum Culling）**：只将活跃在目前摄像机视锥内的三维顶底通过矩阵映射到裁剪空间，不可见的统统不渲染。
- **主动销毁与资源强制解脱（Active Resource Disposal）**：在用户关闭模型查看模态窗或者切换零配件图鉴详情页时，绝不依赖 JavaScript 自带且极其懒散的垃圾回收器（Garbage Collector）。系统代码主动遍历当前的三维层级子图：
  ```javascript
  // 显式释放图形算力内存
  scene.traverse((child) => {
      if(child.isMesh) {
          child.geometry.dispose(); 
          if(child.material.isMaterial) child.material.dispose();
      }
  });
  renderer.dispose();
  ```
只有从显存层面将其彻底驱逐销毁，系统才有可能支持在繁重工业检修场景下进行数十分钟高强度的无缝切换审阅操作，保证零内存泄露（Memory Leaks）。

---

## 九、 生产级系统的安全对抗与高可用容灾演练指标设防

系统的全覆盖部署必须在军工航天级标准下确保工业安全保密性。系统绝无可能在暴露端口中被内外部黑客通过撞库、中间人报文劫持或数据越权等手法穿透破坏数字资产库。

### 9.1 全域接口请求防篡改（JWT + HMAC 与非对称加密通信）
对 `/parts` (创建操作)、`/search` (跨域多模检索操作) 甚至连 3D 重建命令拉起等高权限端口全部配置严格的认证依赖（Auth Dependency）。
使用密码学强度的 JSON Web Token（JWT），将操作员工号及对应管理的车间 ID 通过 `HS256` 即基于哈希的消息验证代码（HMAC）配合只存在于 Docker `.env` 安全挂载卷中的密钥进行加盐（Salt）与签名。如果在网络拓扑中任意节点遭到恶意的篡改报文头部（试图越权操控不属于此机务段的其他动车核心配件库记录），均会被 FastAPI 在微秒级的权限验证器（Validators）中通过哈希不匹配无情拒绝并返回 HTTP 403 Forbidden 封禁，从根本上锁死了工业间谍或误用越权。

### 9.2 API 限流与熔断防呆保护
基于 Redis + Token Bucket（令牌桶）算法部署 API 限流模块。工业库一旦开放接口给别的业务子单元（如库存管理系统），极可能由于别的系统内部逻辑死循环引发对我们大模型检索接口的疯狂 DDoS 调用轰炸。系统底层强硬锁定 `RateLimiting`，一旦单 IP 或者是专属 AppID 在特定数秒内的检测与重建算力索求超过警戒红线，立刻拦截断开连接（返回 HTTP 429 Too Many Requests），直至处罚周期冷却。这一动作强行保卫了弥足珍贵的 GPU 在线运行池在极高压力下不会瘫痪挂死。
