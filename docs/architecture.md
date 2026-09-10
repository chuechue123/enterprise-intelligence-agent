# 架构与数据流

## 为什么使用 AgentScope

本项目需要的不是单次问答，而是“规划—分工—工具取证—审查—交付”的有状态协作。AgentScope 2.0.7 提供 Agent、类型化工具、结构化输出、事件和 Agent Service，使模型推理与确定性业务计算可以分层治理。

```mermaid
flowchart LR
    U[CLI / Web UI] --> L[BizInsightLeader]
    L --> W1[FinanceSalesAgent]
    L --> W2[CustomerProductAgent]
    L --> W3[DeliveryAgent]
    L --> W4[ExternalResearchAgent]
    W1 & W2 & W3 --> M[AgentScope MCPClient]
    M --> T[Scoped Business Data MCP / 只读 SQL / 指标]
    W1 & W2 & W3 --> K[FunctionTool: 混合 RAG]
    K --> B1[Okapi BM25]
    K --> B2[AgentScope KnowledgeBase / Qdrant / Qwen Embedding]
    B1 & B2 --> RF[RRF 融合 / 元数据过滤 / 上下文预算]
    W4 --> X[Tavily / 本地降级资料]
    W1 & W2 & W3 & W4 --> R[EvidenceReviewerAgent]
    R -->|最多一次定向返工| W1
    R -->|通过的 Finding| B[ReportBuilder]
    B --> O[Markdown / HTML / PNG / Evidence Index]
```

## 与 Alias 的关系

Alias 使用旧版 AgentScope。BizInsight 只借鉴其 Meta Planner、领域 Worker 和 Toolkit 分层思想，基于 2.0.7 公共 API 重写。核心原创包括业务数据模型、领域权限、证据契约、确定性指标、Reviewer、报告和评测。这保留了官方案例的成熟职责划分，又避免维护脆弱的旧 API 兼容层。

## 两种执行路径

离线路径以确定性 Worker 替代模型判断，但仍运行同一 `AnalysisPlan`、异步调度、Finding、Reviewer、单轮返工、报告和 `CustomEvent` 契约，用于 CI 和稳定演示。在线路径显式创建 AgentScope Leader、领域 Worker 和 Reviewer，模型通过 `ChatModelBase` 注入，只有用户选择 `--mode online` 时才调用百炼。官方 Agent Service 使用 `custom_agent_cls` 适配会话，CLI、HTTP 和 Web 不复制业务链路。

## RAG 设计

文档先校验 front matter，按标题/段落切成保留文件与行号的 chunk。词法通道使用中文二元/三元切词和 Okapi BM25，适合产品名、版本号和制度编号；语义通道严格使用 AgentScope `DashScopeEmbeddingModel`、`KnowledgeBase`、`QdrantStore`。两个通道分数不可直接相加，因此用 Reciprocal Rank Fusion 合并名次，再执行元数据过滤、chunk 去重、Top-K 和上下文预算。向量不可用时保留 BM25 并记录 `rag_vector_degraded`。

## Alias 迁移映射

Alias `MetaPlanner` 的规划/分派职责对应 `BizInsightLeader + AnalysisWorkflow`；Alias `WorkerManager` 的定向执行对应四类领域 Worker；Alias `AliasToolkit`/data source 对应 AgentScope `Toolkit`、本地 `FunctionTool` 和 Scoped Business Data MCP。旧版 `ReActAgent`、Memory、消息块、私有 Hook 和 MCP runner 均未复制，生命周期由 AgentScope 2.0.7 公共 API 承担。

## 安全边界

- SQL 只允许单条 `SELECT`/只读 `WITH`，SQLite authorizer 再做一层写操作拦截。
- 每个 Worker 只能访问职责范围内的数据集和指标。
- MCP scope 来自子进程启动参数，不接受模型传入的角色声明。
- 模型不能自行给出关键指标最终值，Reviewer 会从数据库重新计算。
- WEB/DOC/CALC/DB 证据类型分开；外部信息不能单独证明内部因果。
- 报告只能写入调用方指定目录，图表文件名经过白名单校验。
- 密钥只从环境读取，健康检查只返回“是否配置”。
