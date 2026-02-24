## 十、 多模态文本特征的深度挖掘：由视觉到语义的桥梁

仅仅依赖纯图像特征往往会在极其端部的某些长尾案例（Long-Tail Cases）中失效，尤其是当两块完全不同的主板由于背部的焊接点排列巧合极具相似性时。引入配件铭文中自带的标牌文字是纠正视觉偏差的无上法宝。我们利用 OCR（光学字符识别）与自然语言处理（NLP）深度融合的多模态检索引擎打破了维度的孤岛。

### 10.1 RapidOCR (PP-OCRv5) 检测与文字提取管线解析
对于工业环境，拍照时常常伴随文字倒挂、严重透视畸变与强光掩盖。开源的 RapidOCR 引擎内部封装了百度顶级的自监督多语种版 PP-OCR 系列流线操作。系统的文字捕获流包括：
1. **DBNet（Differentiable Binarization） 文本检测模型**：抛弃了传统的自底向上像素聚合生成文本边界框，采用了动态二值化阈值的端到端图像语义分割。它使得诸如被蚀刻在金属圆柱体曲面上产生强烈弯曲的零部件型号文本区域也能被精确套入并用仿射变换（Affine Transformation）进行水平展平还原。
2. **CRNN (Convolutional Recurrent Neural Network) + CTC (Connectionist Temporal Classification) 序列识别解析**：将拉平的文本灰度图利用卷积网络层转化为特征序列流，进入双向长短期记忆网络（Bi-LSTM）后在无需人工切割单字符宽度的场景下直接解析。CTC 解码器剔除连续重复及空白状态输出最终被机器印拓的高可信度厂牌货号。
由于其底层运算均推向 ONNX Runtime 原生加速核心，单张千万像素的原图文字解析均压缩于 180 毫秒（ms）以内。

### 10.2 NLP 向量表征：Sentence-Transformer 与语义模糊查全率
过去直接利用 `LIKE '%六角螺栓%'` 等传统的 SQL 搜索因为极其死板而被现代交互产品淘汰。系统转而采用了由 BERT 改 良 的 `Sentence-Transformers` 模型提取句向量。
它通过将 `[CLS]` 提取之后产生的 512 维隐语义嵌入，能明白“六方螺丝”、“六角螺柱”、“梅花带法兰螺帽”在中文工业语言环境下的高度近义相关度，或者理解某长串序列号间的编辑距离（Edit Distance）。
我们将这段文本产生的 512 维张量流同样一并打入 Milvus 中专门为此规划的 Collection 文本分区。最终用户的搜索查询经过同样的 Sentence-BERT 编码，从纯粹文本维度召回到数百件相关配件后，再利用双路高精（DINOv2）视觉向量进一步做相似度的二次倒排。这种由两端包抄（图搜图 + 语义搜图）的搜索架构，查准率与鲁棒性堪称业界翘楚。

---

## 十一、 服务器级硬件配置规划与拓扑节点部署清单

承接总计多达两万级（20,000 Pcs）的数字三维大网格生成与常态化高频检修检索服务，若缺乏严谨的硬件规划，一切皆是空中楼阁。系统在网络拓扑与硬件负载上需切分为 **存储集群**、**推理搜索节点（AI Inference/Search Nodes）** 和 **离线重算力图形节点（GPU Render Compute Nodes）** 三大物理域。

### 11.1 分区基建规划纲要
**A. 稳态数据及高频微服务层 (Data & Microservices Core) —— 混合负载要求极高 IOPS**
配置规划：（至少双机高可用 HA）
- CPU：双路 Intel Xeon Platinum 系列或 AMD EPYC 7003 系列，不低于 64 核 128 线程。
- 内存（RAM）：最低配置 256 GB ECC，为了避免极其庞大的 Postgres 连接与 Milvus 巨型 ANN 导航图在并发查找时引发内存换页（Swap Thrashing）。
- 存储介质：为了应对疯狂写入的 PostgreSQL 以及 Milvus 预写日志（WAL）极小的 IO 块，系统盘或数据卷只允许挂载 U.2/PCIe 4.0 的企业级 NVMe SSD 裸金属，读写极速要求在 5000 MB/s 以防数据库由于磁盘挂起引发的长耗时死锁事务。

**B. 极其海量对象的黑洞集群 (MinIO Distributed Pool)**
配置规划：（三至五可用节点构建）
- CPU：普通商用级（如 Intel Xeon Silver 系列 16 核心足够），其核心任务并非计算而是校验。
- 内存：64 GB。
- 存储介质：为了装载两万个资产的数百万张照片，通过多机外挂海量 16TB 或 20TB 高转速企业级机械硬盘（HDD 阵列），以 Erasure Code 将廉价的机械硬盘武装成永不丢失的高可用对象洋流。用最极致的低成本获取最辽阔的容量池。

**C. 万级配件的三维模型冶炼厂 (3D Rendering Farm / Reconstruct Nodes)**
此节点群是极其吞噬算力显存的深渊。它是处理 2DGS 反复求导训练，并执行移动立方体生成网格 `.obj` 的绝对核心动力源。
配置规划：（可利用 Kubernetes HPA 动态缩扩容的工作站集群）
- GPU 阵列：单节点内极力推荐插满配置例如 4 张到 8 张的 NVIDIA A100 (80GB VRAM) 或最低使用海量性价比较高的消费级卡王如 NVIDIA RTX 4090 (24GB VRAM) 阵列。如果采用后者极要求宿主机的 PCIe 总线及供电冗余充足。
- 内存分配策略：要求宿主物理 RAM 容量是全体挂载 GPU 显存加总的 1.5 倍（即单机 192GB GPU 显存至少需配 384 GB 物理 RAM）。之所以做此变态级要求，是因为 COLMAP (SFM 推断) 等 CPU 执行体在初始化匹配上万个关键点矩阵时，会如黑洞般吞吃主内存在完成推断后才交接进显卡的 Cuda Stream。
- 节点调度管理（Task Taint & Tolerations）排斥性污点隔离：
  基于 Kubernetes 编排环境部署时，必须给所有带深度 GPU 图形显卡的 Kubernetes 节点配置高权重“污点”（Taints）以及 Pods 的容忍度（Tolerations），严格阻止数据库、Nginx 等对延迟苛刻的常驻基础业务进程漂移到图形节点中，保证被隔离在这片法外之地的训练大军哪怕发生因为 OOM 导致的容器崩溃重启，主线系统依然岁月静好、岿然不动！

### 11.2 Nginx 控制流路由与端口编排网络拓扑（Load Balancing & Reverse Proxy）
为使所有的通讯安全穿越复杂机房的安全防护墙。前端一切入口无论是 HTTPS 或者是拉起双向 WebSocket，皆交由前端的一头反向代理级 Nginx 来截获并消化证书开解请求。
前端路由 `api.recognition.xxx/` 下游流量依照路径深度解剖：
- `location /api/v1/parts`：被 Upstream Pool 负载均衡至 FastAPI （通常运行于 `Uvicorn` 引擎加上 `Gunicorn` 在容器内的进程管理层），负责分流业务高频轻载短连接。
- `location /api/v1/milvus/search`：极易遭受长文本高宽带消耗。可以为其分配基于权重的更优先网络带宽。
- `location /assets/` 或直接重定向至内部专用解析域名分发：直接透明代理（Proxy Pass）给承载 MinIO 的 `9000` 端口集，实现纯二进制模型文件或者图片大流的高速越狱式拉取。Nginx 强制实施 `gzip_static` 或者 `Brotli` 压缩机制给那些诸如配置 `json`，但对已压缩好的 `jpg`, `.obj` 或图片则原样零拷贝（Zero Copy）`sendfile on` 推送至内网的每一个工业用终端，达成了物理上不可能完成的时间极点优化！
