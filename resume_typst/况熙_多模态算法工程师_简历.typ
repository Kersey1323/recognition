#import "modernpro-cv.typ": *

// Based on modernpro-cv 2.1.1 from jxpeng98/Typst-CV-Resume (MIT).
#let profile = (
  name: [况熙],
  role: [多模态算法工程师 · 大模型应用开发],
  address: [成都 · 2026 届硕士],
  contacts: (
    (text: [199 8204 2910], link: "tel:+8619982042910"),
    (text: [492700414\@qq.com], link: "mailto:492700414@qq.com"),
  ),
)

#show: cv.with(
  profile: profile,
  preset: "relaxed",
  font-type: ("Noto Serif CJK SC", "Noto Serif CJK JP", "Libertinus Serif"),
  accent: rgb("#1e3a5f"),
  options: (date: "2026-09-09"),
)

#section("个人简介")
#summary[
  成都大学计算机技术硕士在读，具备多模态检索、视觉分割、RAG 与 Agent 应用的完整项目经验。
  能将模型能力落到数据同步、向量索引、业务接口、权限鉴权和容器化部署等工程链路，参与过铁路配件智能识别、企业文档脱敏与医疗报告质控项目。
]
#section-gap

#section("实习经历")
#experience(
  title: "多智能体研发实习生",
  institution: [布法罗机器人科技（成都）有限公司],
  location: "成都",
  date: "2026.03-2026.07",
  details: [
    - 参与中车配件智能识别系统核心研发与工程化交付，覆盖多模态检索、询码语义检索、技术核验和三维重构等业务链路。
    - 协同完成主业务、模型推理与三维重构三类服务的接口联调、部署配置和现场问题排查，支持内部部署、系统对接与验收。
  ],
)
#experience(
  title: "算法实习生",
  institution: [四川安正企业管理集团],
  location: "成都",
  date: "2025.11-2026.03",
  details: [
    - 参与企业级文档脱敏一体机与大模型应用平台研发，负责 OCR 预处理、敏感实体识别和 RAG 问答链路实现。
    - 完成大模型统一调用、检索增强与链路观测能力集成，配合推进私有化环境部署和功能验证。
  ],
)
#section-gap

#section("教育经历")
#education(
  institution: [成都大学],
  major: [计算机技术 · 硕士],
  date: "2024.09-至今",
  location: "成都",
  description: [研究方向：大模型应用、多模态检索与医疗文本智能分析。],
)
#education(
  institution: [成都大学],
  major: [软件工程 · 本科],
  date: "2019.09-2023.06",
  location: "成都",
)
#section-gap

#section("项目经历")
#entry(
  title: [中车配件智能识别系统],
  right: "2026.03-2026.07",
  meta: [布法罗机器人科技 · 核心研发与工程化交付],
  location: [FastAPI · SigLIP · DINOv2 · SAM2 · BGE-M3 · Milvus],
  details: [
    - *多模态检索工程化：*融合 SigLIP、DINOv2、YOLO-World / SAM2、OCR 与 Milvus，打通图片预处理、目标分割、特征提取、向量入库、相似检索、结果回写和业务 API 服务链路；分割失败时保留原图兜底，提升工业现场数据的可用性。
    - *询码语义检索：*基于 BGE-M3 构建历史询码描述文本索引，支持自然语言描述召回配件；设计全量重建、SGO 同步后增量索引、任务状态追踪与失败告警机制，索引失败不回滚主数据同步。
    - *企业系统对接：*对接 SGO 业务系统以及 Kingbase / MySQL 数据源，完成配件主数据、图片和询码历史同步；处理 KingbaseES 私有时间类型兼容，并补齐失败明细、任务取消和重试流程。
    - *三维重构链路：*参与视频上传、分片处理、任务提交、状态同步与结果文件管理，支持 Viewer360 展示、任务目录清理和原图访问兜底。
    - *工程交付：*完成主业务服务容器化，接入 Redis、Milvus、MinIO、模型服务和重构服务；实现 SGO Token 鉴权、缓存及 Nginx + MinIO 文件代理。系统当前承载 7.8 万+配件主数据、1.4 万+样本图片和 2 万+业务向量数据，覆盖 70+核心业务接口。
  ],
)
#entry(
  title: [企业级文档脱敏一体机与大模型应用平台],
  right: "2025.11-2026.03",
  meta: [四川安正企业管理集团 · 算法研发],
  location: [OCR · LangChain · RAG · Langfuse],
  details: [
    - 面向法律文档搭建 OCR 与敏感信息脱敏流程，结合对比度增强、超分辨率和版面解析，提高扫描件与低清图片的识别质量。
    - 设计姓名、企业名称、地址等 6 类敏感实体抽取与高亮能力，支持结构化结果输出和脱敏前后内容核验。
    - 基于 LangChain 构建文档切分、向量化、召回与问答链路，接入 Langfuse 记录调用、检索和生成过程，便于效果评估与问题定位。
  ],
)
#entry(
  title: [成都大学附属医院病历报告质控系统],
  right: "2024.06-至今",
  meta: [成都大学研究生课题 · 算法研发],
  location: [Qwen2.5-7B · LoRA · GRPO · RAG · 知识图谱],
  details: [
    - 面向病历报告实时与事后质控，使用 Qwen2.5-7B 开展 LoRA 微调，并以 BLEU 设计奖励信号进行 GRPO 优化；实验中 ROUGE-1 F1 提升 6.1%，ROUGE-2 F1 提升 3.9%。
    - 构建医疗知识 RAG 与知识图谱检索链路，为问题定位、依据召回和修改建议生成提供上下文支撑。
    - 设计 Agent 规则引擎，将确定性校验规则与大模型判断组合，覆盖字段完整性、逻辑一致性和医学表述规范等质控场景。
  ],
)
#section-gap

#section("技术能力")
#detail-line(
  title: "大模型与智能体",
  content: [熟悉 RAG、Agent、Prompt Engineering、LoRA 微调、推理与量化，具备 LangChain、LlamaIndex 和 PyTorch 实践经验。],
)
#detail-line(
  title: "多模态与视觉",
  content: [熟悉 SigLIP、DINOv2、SAM / SAM2、YOLO-World、OCR，具备图像分割、视觉特征提取和图文检索经验。],
)
#detail-line(
  title: "检索与数据",
  content: [熟悉 BGE-M3、向量索引与语义检索，能够使用 Milvus、MySQL、Kingbase、Redis 和 MinIO 构建数据链路。],
)
#detail-line(
  title: "工程化",
  content: [熟悉 Python、FastAPI、Flask、Django、Linux、Docker 与 Nginx，具备模型服务解耦、接口联调、权限鉴权和私有化部署经验。],
)
#section-gap

#section("荣誉与证书")
#award(award: "大学英语六级（CET-6，468 分）", institution: "全国大学英语四六级考试委员会", date: "")
#award(award: "校学科建设交叉项目立项", institution: "成都大学", date: "")
#award(award: "一等奖学金", institution: "成都大学", date: "")
