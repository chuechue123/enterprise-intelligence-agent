# BizInsight Agent 1.0 设计规格

- 日期：2026-09-10
- 状态：待用户书面确认
- 基线：MVP commit `5c85e54`
- AgentScope：`2.0.7`
- Alias 固定参考：`agentscope-samples@c7f3174cbbd32a96c796571d0fe930ac80ddd523`

## 1. 目标与完成边界

BizInsight Agent 1.0 是可用于求职展示的正式作品版本。它必须同时具备真实模型运行、离线降级、AgentScope 多智能体协作、MCP 数据工具、混合 RAG、一次证据返工、官方 Agent Service/Web UI 展示、动态期间分析和可重复评测。

1.0 不连接真实企业系统，不自动修改 CRM/财务数据，不实现生产级多租户、长期记忆、审批发布、预测模型或 Kubernetes 部署。所有数据和文档继续使用合成内容。

## 2. 参照优先原则

实现前必须先定位 Alias 固定 commit 中的职责来源和 AgentScope 2.0.7 的公共 API。不得为了代码外形相似而复制不兼容的私有 Hook、旧 Memory、旧消息块或旧运行器，也不得绕过 AgentScope 自建另一套 Agent 框架。

| 1.0 模块 | Alias 职责参照 | AgentScope 2.0.7 实现参照 | 处理方式 |
|---|---|---|---|
| Leader | `_meta_planner.py`、`meta_planner_utils/_planning_notebook.py`、`_roadmap_manager.py`、`_worker_manager.py` | `Agent`、`UserMsg`、`ReActConfig`、`structured_schema` | 保留规划、Worker 描述、计划执行分离；用类型化计划重写 |
| 领域 Worker | `_react_worker.py` | `Agent`、`Toolkit`、`FunctionTool` | 保留统一 Worker 基类、限定迭代和结构化结果；用 2.0.7 API 重写 |
| 数据分析 | `_data_science_agent.py`、`data_source/`、`ds_agent_utils/ds_toolkit.py` | `Toolkit`、`MCPClient`、`MCPTool` | 保留数据描述、先计算后解释；删除任意代码执行，改成只读 MCP |
| 外部研究 | `_deep_research_agent_v2.py`、`dr_agent_utils/` | `Agent`、`FunctionTool`、Tavily 适配器 | 保留有界检索、来源捕获和证据综合；删除第二套通用研究树 |
| 工具组织 | `tools/alias_toolkit.py`、`tools/add_tools.py`、`tools/share_tools.py` | `Toolkit.add_tool`、`MCPClient.list_tools` | 保留按 Worker 分组；改成公共工具注册和显式 allowlist |
| RAG | Alias DeepResearch 的检索/引用职责 | `DashScopeEmbeddingModel`、`KnowledgeBase`、`QdrantStore`、`RAGMiddleware` 官方示例 | 用 AgentScope RAG 组件建立向量通道，与现有 BM25 融合 |
| 服务/Web | 删除 Alias 自有 runner/frontend | `agentscope.app.create_app` 官方 Agent Service 示例 | 复用官方 Service 和 Web UI 协议，不开发大型独立前端 |

每个新核心文件都要在模块文档或归因表中记录上述来源；若官方 API 不能满足需求，先记录差距，再编写最小适配器。

## 3. 最终架构

```text
AgentScope Web UI / CLI
          |
          v
AgentScope Agent Service + BizInsightServiceAgent
          |
          v
BizInsightLeader (qwen-plus)
          |
          v
AnalysisPlan（动态当前期间、对比期间、最多四个任务）
   |             |              |              |
   v             v              v              v
FinanceSales  CustomerProduct  Delivery  ExternalResearch
   |             |              |              |
   +-------------+--------------+              |
                 |                             |
                 v                             v
       Business Data MCP                  Tavily/本地降级
                 |
                 +----------+------------------+
                            |
                            v
        Hybrid RAG（BM25 + AgentScope KnowledgeBase/Qdrant）
                            |
                            v
                  Finding + Evidence
                            |
                            v
              EvidenceReviewerAgent
                            |
               最多一次定向返工
                            |
                            v
        ReportBuilder -> Markdown/HTML/PNG/证据索引
```

## 4. 在线、离线与测试三条路径

### 4.1 在线路径

- `qwen-plus` 用于 Leader 和领域 Worker 的规划、ReAct 工具选择与结构化 Finding。
- `text-embedding-v4`、1024 维用于企业文档向量化和语义查询。
- Tavily 用于实时外部行业资料。
- Reviewer 的硬规则始终先执行；模型只补充语义支持度与因果强度审查。
- 记录模型 ID、token、耗时、工具调用、结构化输出失败和降级原因。

### 4.2 离线路径

- 确定性 Leader/Worker 继续作为无模型兜底，但必须读取计划中的动态期间，不能硬编码 Q1/Q2。
- Business Data MCP 可本地 STDIO 运行；MCP 失败时允许回退到同一 `BusinessDataProvider` 的本地 FunctionTool，并记录降级事件。
- RAG 在无百炼 Embedding 时使用 BM25；外部研究使用本地备用资料。
- 离线和在线必须输出相同的 `AnalysisPlan`、`Finding`、`Evidence` 和 `ReviewResult` 契约。

### 4.3 测试路径

- Mock Model 真实运行 AgentScope `Agent.reply`、消息、工具调用与结构化输出。
- 单元测试默认不访问网络。
- 在线评测必须显式启用并单独记录费用与结果。

## 5. 动态规划与经营分析

`BizInsightLeader` 继续采用组合而非继承：业务包装器持有可选的 AgentScope `Agent`。在线通过 `structured_schema=AnalysisPlan` 规划，离线通过确定性解析兜底。

计划新增标准季度表示和从 `DateRange` 推导 `YYYY-Qn` 的公共函数。每个 Worker 只能使用 `AnalysisTask` 所属计划中的当前和对比期间。数据存在范围内支持：

- 任意季度与上一季度对比；
- 用户明确指定两个季度的对比；
- 收入、毛利率、赢单率、续费率、按时验收率；
- 区域、行业、客户规模、产品版本等可用维度的细分；
- 综合问题最多四个并行任务，专项问题只路由所需 Worker；
- 缺少期间、维度或数据时记录 assumption/limitation，不伪造结果。

Worker 先调用确定性工具获取事实，再由模型解释，不允许模型自行计算关键指标。

## 6. Business Data MCP

新增本地 STDIO MCP Server，底层复用现有 `BusinessDataProvider`、指标字典和 SQL 安全校验，不复制第二套计算逻辑。对外工具为：

- `list_business_datasets`
- `describe_business_dataset`
- `calculate_business_metric`
- `compare_business_periods`
- `query_business_data`

AgentScope 客户端使用 `MCPClient(name="bizinsight-data", StdioMCPConfig(...), is_stateful=True)`，连接后通过 `list_tools()` 获得 `MCPTool`，再使用 `Toolkit.add_tool()` 按 Worker allowlist 注册。

安全要求：

- MCP Server 仍拒绝写 SQL、多语句、DDL/DML 和越权表；
- 查询限制行数和超时；
- Worker 只注册本领域所需工具；
- MCP 返回与本地 FunctionTool 相同的 Metric/Evidence 结构；
- STDIO 生命周期由工作流统一打开和关闭；
- Server 异常时记录 `mcp_degraded`，离线允许本地回退，在线报告明确限制。

图表、报告和 Reviewer 硬规则保留为本地可信代码，不为展示 MCP 而服务化。

## 7. 混合 RAG

### 7.1 索引

保留当前文档 YAML 元数据、标题/段落感知切分和行号定位。新增 AgentScope 官方 RAG 通道：

```text
Markdown bytes
 -> TextParser/受控元数据适配
 -> ApproxTokenChunker（目标 256 tokens，32 overlap）
 -> DashScopeEmbeddingModel(text-embedding-v4, 1024)
 -> KnowledgeBase.insert_document
 -> QdrantStore 本地持久化目录
```

文档内容为合成数据。真实企业应用若向百炼发送内部文档，必须另行完成数据合规审批；该事项不在求职版 1.0 中伪装为已解决。

### 7.2 检索

一次查询并行执行：

1. 现有词法索引升级为 BM25，擅长产品名、编号和指标名；
2. `KnowledgeBase.search` 执行语义向量召回；
3. 使用 Reciprocal Rank Fusion 合并两路排名；
4. 根据 department、document_type、date 等元数据过滤；
5. 去重并在上下文预算内选择 Top-K；
6. 转换成带 document/chunk/行号的 `DOC-*` Evidence。

Agent 侧采用 agentic retrieval：Worker 根据问题决定何时查询和查询内容。为支持 BM25/RRF，业务层提供一个混合检索 FunctionTool；其向量部分必须调用 AgentScope `KnowledgeBase`，不得另写一套向量框架。

第一版不默认增加云端 rerank。只有当专项评测表明 RRF 未达到门槛时，才评估 `qwen3-rerank`，并单独记录成本收益。

### 7.3 降级

- Embedding/Qdrant 不可用：退回 BM25，并记录 `rag_vector_degraded`；
- BM25 无结果：返回明确 no-match，不让模型补造文档；
- 两路都无结果：数据库分析继续，Finding 添加限制；
- 索引模型、维度或源文档哈希变化：拒绝复用旧向量集合并要求重建。

## 8. Reviewer 与一次返工

主链路必须调用 `run_review_cycle()`，不能只在测试中存在。

```text
硬规则初审
 -> 可修复：生成 RevisionRequest
 -> 同一轮并行返工所有目标 Finding
 -> 硬规则终审（禁止第二轮）
 -> accepted/rejected/limitations
```

硬规则负责数值复算、Evidence 链接、冲突和外部因果边界。在线语义 Reviewer 使用 AgentScope `Agent` 检查“证据内容是否支持表达”和“因果措辞是否过强”，但不得覆盖硬规则的拒绝结果。

返工请求包含 finding ID、目标 Worker、原因和必需修改。Worker 只重做被点名的 Finding。第二次仍失败的结论不得进入报告，只进入限制与未决问题。

## 9. Agent Service 与官方 Web UI

采用 AgentScope 官方 `create_app`，不复制 Alias 前端。新增 `BizInsightServiceAgent`/适配层，使标准会话消息进入 `run_analysis()`，并将业务状态转换成 AgentScope 事件流。

Web UI 至少展示：

- 用户问题和 online/offline 模式；
- Leader 的计划与 assumption；
- 每个 Worker 的 started/completed/failed/timed_out 状态；
- MCP、RAG、Tavily 的工具调用摘要和降级事件；
- Reviewer 初审、返工和终审；
- 最终报告链接或内嵌 HTML。

保留 `/bizinsight/health` 和 `/bizinsight/analyze`，健康检查只返回配置状态，不返回 Key。Redis、Qdrant、模型、MCP、知识库和 Tavily 分别报告 readiness。CLI 与 Web 使用同一个应用服务函数，防止两套业务逻辑漂移。

若 AgentScope 官方 Web UI 不支持内嵌业务 HTML，只增加最小报告链接/静态文件路由，不创建独立大型前端。

## 10. 配置与秘密

模型配置：

- `BIZINSIGHT_MODEL_NAME=qwen-plus`
- `BIZINSIGHT_EMBEDDING_MODEL=text-embedding-v4`
- `BIZINSIGHT_EMBEDDING_DIMENSIONS=1024`
- `DASHSCOPE_API_KEY`、`TAVILY_API_KEY` 只从 `.env`/环境读取。

已经出现在聊天、日志或提交中的 Key 一律视为泄露，必须撤销；代码和文档不得包含真实 Key，错误消息不得打印 Key。

## 11. 测试与评测

### 11.1 自动测试

- Leader：动态期间、双期间、专项/综合路由、模型非法计划降级；
- Worker：MCP 工具 allowlist、ReAct 结构化 Finding、动态期间；
- MCP：工具发现、STDIO 生命周期、SQL 越权与写入拒绝、本地降级；
- RAG：切分、BM25、向量结果转换、RRF、元数据过滤、索引失配和降级；
- Reviewer：语义问题、硬规则优先、单轮返工和最终拒绝；
- Service/Web：健康检查、标准消息入口、事件顺序、报告静态路由；
- E2E：离线、Mock AgentScope、显式在线三条路径。

### 11.2 RAG 评测

建立独立查询集，至少覆盖产品事故、定价、收入确认、销售输单、客服升级、客户访谈和无答案问题。记录 BM25、向量、混合三组结果：

- Hit@1、Hit@3；
- MRR；
- 引用定位完整率；
- 无答案拒答率；
- 延迟和 Embedding token/费用。

验收门槛：混合检索 Hit@3 不低于 90%，MRR 不低于 0.75，且不得显著低于单独 BM25。

### 11.3 在线稳定性

黄金问题至少重复 5 次，结构化计划/Findings 成功率至少 80%，每次识别至少 4/5 核心异常；真实结果原样保留，不能用离线结果冒充在线结果。记录模型 ID、token、工具调用、延迟、错误和总成本。

## 12. 实施顺序

1. 在线可观测性与真实模型基线；
2. Reviewer 主链路返工；
3. AgentScope Agent Service/Web UI 标准会话接入；
4. 动态期间和细分分析；
5. Business Data MCP；
6. AgentScope 混合 RAG 与专项评测；
7. 全量回归、在线重复运行、截图、演示和面试材料更新。

每一步先添加失败测试，再实现，再执行局部和全量验证，并形成小型 Conventional Commit。

## 13. Definition of Done

只有同时满足以下条件，1.0 才完成：

- 官方 AgentScope Web UI 能提交问题并看到计划、Worker、工具、审查和报告事件；
- `qwen-plus` 在线黄金案例达到稳定性门槛，Tavily 成功与降级均有证据；
- Reviewer 在真实主链路最多返工一次；
- 所有 Worker 使用计划中的动态期间，支持至少一组非 Q1/Q2 用例；
- AgentScope `MCPClient` 真实连接 Business Data MCP，且安全/降级测试通过；
- 向量检索真实使用 `DashScopeEmbeddingModel + KnowledgeBase + QdrantStore`，混合 RAG 达到专项门槛；
- 离线模式在无任何 Key、无网络时仍能生成报告；
- 全量测试、评测、README、架构图、真实截图、演示脚本和 Alias 归因全部更新；
- 仓库不包含任何真实密钥，项目边界明确说明数据完全合成、未在真实企业生产部署。
