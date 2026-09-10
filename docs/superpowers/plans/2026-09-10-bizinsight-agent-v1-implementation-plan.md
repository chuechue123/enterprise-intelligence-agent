# BizInsight Agent 1.0 实施计划

- 日期：2026-09-10
- 设计依据：[BizInsight Agent 1.0 设计规格](../specs/2026-09-10-bizinsight-agent-v1-design.md)
- MVP 基线：`5c85e54`
- 设计规格提交：`7fb135a`
- AgentScope：`2.0.7`
- Alias 固定参考：`agentscope-samples@c7f3174cbbd32a96c796571d0fe930ac80ddd523`
- 实施方式：逐任务测试先行、局部验证、全量回归、小型 Git commit

## 0. 实施约束

1. 每个 Agent/MCP/RAG/Service 模块实施前，先读取本计划指定的 Alias 文件和 AgentScope 2.0.7 公共实现或官方示例。
2. 不复制 Alias 的旧 `ReActAgent`、Memory、私有 Hook、旧消息块、旧 MCP 或 runner；保留职责和交互结构，使用 2.0.7 公共 API 改写。
3. 不绕过 AgentScope 自建另一套 Agent 生命周期。领域确定性逻辑可以作为工具、审查规则和离线适配器存在。
4. 任何真实 Key 不写入源代码、测试、日志、报告、事件或 Git；聊天中曾暴露的 Key 不再使用。
5. 在线调用必须显式启用，记录模型、token、耗时、工具调用和费用；离线测试不得访问网络。
6. 工作区中的既有修改视为用户资产，不覆盖无关内容。

## 1. 配置、在线可观测性与基线运行器

### 参照

- Alias：`_meta_planner.py` 的任务状态记录、`common_agent_utils.py` 的执行状态保存职责。
- AgentScope：`Agent`、`Msg`、`CustomEvent`、模型响应 usage 字段和官方 agent-service 事件流。

### 文件

- 修改 `src/bizinsight/config.py`
- 新增 `src/bizinsight/observability.py`
- 修改 `src/bizinsight/app.py`
- 修改 `.env.example`
- 新增 `scripts/run_online_baseline.py`
- 新增 `tests/unit/test_observability.py`
- 新增 `tests/integration/test_online_run_contract.py`

### 测试先行

1. 健康检查只显示配置状态，不包含 Key。
2. Mock Model 运行后产生统一的 run ID、Agent 名、模型名、耗时、工具调用和错误记录。
3. online 未配置模型时在任何网络调用前失败。
4. 事件 JSON 可序列化且不包含 SecretStr 内容。

### 实现

1. 增加 `BIZINSIGHT_MODEL_NAME=qwen-plus`、`BIZINSIGHT_EMBEDDING_MODEL=text-embedding-v4`、`BIZINSIGHT_EMBEDDING_DIMENSIONS=1024` 配置和合法性校验。
2. 定义 `RunTelemetry`、`AgentTelemetry`、`ToolTelemetry`，由 workflow event sink 和模型 usage 汇总。
3. 让 CLI、HTTP 和基线脚本共享同一个 `run_analysis`，禁止基线脚本复制业务流程。
4. 基线脚本支持 `--runs`、`--question`、`--output-dir`，在线调用前打印预计运行次数，不打印密钥。

### 验证与提交

```powershell
pytest tests/unit/test_observability.py tests/integration/test_online_run_contract.py -q
ruff check src tests scripts
```

提交：`feat(observability): add safe online run telemetry`

## 2. 将 Reviewer 单轮返工接入主链路

### 参照

- Alias：MetaPlanner 的 planning/execution 循环和 WorkerManager 定向调度职责。
- AgentScope：`Agent.reply(..., structured_schema=ReviewResult)`；不覆盖确定性硬规则。

### 文件

- 修改 `src/bizinsight/agents/reviewer.py`
- 修改 `src/bizinsight/orchestration/review_loop.py`
- 修改 `src/bizinsight/orchestration/workflow.py`
- 修改 `src/bizinsight/app.py`
- 修改 `src/bizinsight/prompts/reviewer.md`
- 新增 `tests/integration/orchestration/test_main_revision_cycle.py`
- 新增 `tests/integration/agents/test_semantic_reviewer.py`

### 测试先行

1. 错误指标只退回原 Finding 的 owner。
2. 多个返工请求在同一轮并行执行，`revision_count` 仍为一轮。
3. 第二次失败直接拒绝，不发起第三次调用。
4. 模型语义审查不能推翻硬规则拒绝。
5. `run_analysis` 的事件顺序包含初审、返工、终审。

### 实现

1. Workflow 结果保留 Finding 到原始 task/Worker 的映射。
2. `run_analysis` 使用 `run_review_cycle()`；revise callback 调用原 Worker，并将 RevisionRequest 附加到任务消息。
3. 在线 Reviewer 在硬规则通过后执行一次 AgentScope 结构化语义审查；离线仅执行硬规则。
4. 报告只接收终审 accepted Finding，未解决项进入 limitations。

### 验证与提交

```powershell
pytest tests/integration/orchestration/test_main_revision_cycle.py tests/integration/agents/test_semantic_reviewer.py -q
pytest -q
```

提交：`feat(review): wire one-round revision into the main workflow`

## 3. AgentScope Agent Service 与官方 Web UI 会话接入

### 参照

- Alias：只参考 runner 的“会话输入转 Agent 回复”和流式状态职责，不迁移 Alias frontend/service。
- AgentScope：`examples/agent_service/main.py`、`agentscope.app.create_app`、`custom_agent_cls`、标准消息和事件协议。

### 文件

- 新增 `src/bizinsight/agents/service_agent.py`
- 重构 `src/bizinsight/service.py`
- 修改 `src/bizinsight/app.py`
- 修改 `scripts/start_backend.ps1`
- 修改 `scripts/start_webui.ps1`
- 新增 `tests/integration/service/test_agentscope_chat_entry.py`
- 新增 `tests/integration/service/test_event_stream.py`
- 新增 `tests/e2e/test_web_service_report.py`

### 测试先行

1. 官方 Agent Service 的标准会话消息进入 BizInsight 工作流，而非通用默认 Agent。
2. 测试客户端能按顺序收到 plan、worker、tool、review、report 事件。
3. 报告静态 URL 只能访问指定 output 根目录。
4. health 分别报告 Redis、Qdrant、MCP、数据库、知识库、模型和 Tavily 状态，不泄密。

### 实现

1. 按 `custom_agent_cls` 构造契约实现 `BizInsightServiceAgent`；适配层只负责消息/事件转换，业务逻辑仍调用 `run_analysis`。
2. 将 workflow `CustomEvent` 转换为官方 Web UI 可消费的事件。
3. 使用受控静态路由暴露报告和图表；若 UI 不支持内嵌 HTML，返回可点击报告链接。
4. 保留 `/bizinsight/analyze` 作为自动化入口，CLI、HTTP、Web 共用同一流程。

### 验证与提交

```powershell
pytest tests/integration/service tests/e2e/test_web_service_report.py -q
python -c "from bizinsight.service import app; print(app.title)"
```

人工验证官方 Web UI 能输入问题并看到事件及报告链接。

提交：`feat(service): connect BizInsight to AgentScope Web UI sessions`

## 4. 动态期间与细分经营分析

### 参照

- Alias：DataScienceAgent 的“先理解数据源与 schema，再制定分析步骤”；删除任意 IPython/code execution。
- AgentScope：结构化 `AnalysisPlan` 和 Worker `structured_schema=Finding`。

### 文件

- 修改 `src/bizinsight/schemas/plan.py`
- 新增 `src/bizinsight/time_periods.py`
- 修改 `src/bizinsight/agents/leader.py`
- 修改 `src/bizinsight/orchestration/workflow.py`
- 修改 `src/bizinsight/orchestration/offline.py`
- 修改三个领域 Worker prompt
- 扩展 `src/bizinsight/tools/metrics.py`
- 新增 `src/bizinsight/tools/segments.py`
- 新增 `tests/unit/test_time_periods.py`
- 新增 `tests/integration/orchestration/test_dynamic_periods.py`
- 新增 `tests/integration/tools/test_segment_analysis.py`

### 测试先行

1. 解析 `2025-Q4`、`2026年第一季度`、明确双季度和未指定期间。
2. Worker 实际查询计划期间，不允许出现硬编码 `2026-Q2`。
3. 数据范围外请求返回 limitation，不偷偷改为 Q2。
4. 区域、行业、客户规模和产品版本过滤使用参数化 SQL。
5. 专项问题不启动无关 Worker。

### 实现

1. 新增不可变 `AnalysisContext`，将当前期间、对比期间和维度过滤连同 task 一起交给 Worker，避免修改共享 Worker 状态。
2. Leader 在线/离线都生成相同 Context；默认期间从数据清单推导，不在代码中写死。
3. 指标函数支持数据库已有季度；细分分析使用受控维度枚举和参数化 SQL。
4. 离线 Finding 标题/解释根据真实变化方向和维度生成，不使用固定 Q2 文案。

### 验证与提交

```powershell
pytest tests/unit/test_time_periods.py tests/integration/orchestration/test_dynamic_periods.py tests/integration/tools/test_segment_analysis.py -q
pytest -q
```

提交：`feat(analysis): support dynamic periods and business segments`

## 5. Business Data MCP Server

### 参照

- Alias：`data_source/` 的统一数据入口、`alias_toolkit.py` 的工具分组和 Worker 工具隔离。
- AgentScope：`MCPClient`、`StdioMCPConfig`、`MCPTool`、`Toolkit.add_tool` 公共 API；Python MCP SDK 的 FastMCP Server。

### 文件

- 新增 `src/bizinsight/mcp/__init__.py`
- 新增 `src/bizinsight/mcp/server.py`
- 新增 `src/bizinsight/mcp/client.py`
- 新增 `src/bizinsight/mcp/contracts.py`
- 修改 `src/bizinsight/agents/worker_base.py`
- 修改 `pyproject.toml`
- 新增 `scripts/start_mcp_server.ps1`
- 新增 `tests/unit/mcp/test_server_tools.py`
- 新增 `tests/integration/mcp/test_agentscope_client.py`
- 新增 `tests/integration/mcp/test_mcp_security.py`

### 测试先行

1. AgentScope `MCPClient.list_tools()` 能发现五个业务工具。
2. 每个 Worker 的 Toolkit 只包含其领域允许的 MCP 工具/指标。
3. 写 SQL、多语句、越权表、越权指标、超时和超行数全部失败。
4. MCP 与本地 FunctionTool 对同一指标返回相同 Metric/Evidence。
5. MCP 子进程异常时离线降级并产生事件。

### 实现

1. FastMCP Server 只做协议适配，底层调用现有 Provider/metrics/segments。
2. 每个 Worker 使用独立 STDIO MCPClient，并通过不可变 `--scope <WorkerName>` 启动；Server 根据 scope 建立表和指标 allowlist，不能信任模型传入角色。
3. 连接后调用 `list_tools()`，通过 `Toolkit.add_tool()` 注册；统一管理 connect/close 生命周期。
4. 本地回退适配器实现相同 contracts，避免双套业务逻辑。

### 验证与提交

```powershell
pytest tests/unit/mcp tests/integration/mcp -q
pytest -q
```

提交：`feat(mcp): expose scoped read-only business data tools`

## 6. AgentScope 向量知识库基础

### 参照

- Alias：DeepResearch 的来源捕获、查询细化和有界证据职责。
- AgentScope：`examples/rag/index_and_search.py` 的 parse → chunk → embed → insert → search；`DashScopeEmbeddingModel`、`KnowledgeBase`、`QdrantStore`。

### 文件

- 新增 `src/bizinsight/rag/__init__.py`
- 新增 `src/bizinsight/rag/vector_index.py`
- 修改 `scripts/build_knowledge_base.py`
- 修改 `src/bizinsight/config.py`
- 修改 `pyproject.toml`
- 新增 `tests/unit/rag/test_vector_metadata.py`
- 新增 `tests/integration/rag/test_agentscope_knowledge_base.py`

### 测试先行

1. Mock Embedding 下 AgentScope KnowledgeBase 能插入和检索 Chunk。
2. 每个结果保留 document ID、chunk ID、部门、日期、文件和行号。
3. 源哈希、模型或维度变化时拒绝旧索引。
4. 没有 Key 时构建命令明确说明只生成 BM25，不网络调用。

### 实现

1. 按官方示例构建 `DashScopeEmbeddingModel(text-embedding-v4, 1024)`、本地持久化 `QdrantStore(path=...)` 和 `KnowledgeBase`。
2. 复用现有 front matter 校验；将标题/段落和行号元数据适配到 AgentScope Chunk。
3. 索引 manifest 保存源哈希、模型、维度、collection 和构建时间，不保存 Key。
4. 向量索引构建必须显式 `--online-embedding`，避免普通数据构建产生费用。

### 验证与提交

```powershell
pytest tests/unit/rag tests/integration/rag/test_agentscope_knowledge_base.py -q
python scripts/build_knowledge_base.py
```

提交：`feat(rag): add AgentScope Qwen vector knowledge base`

## 7. BM25、向量召回与 RRF 混合检索

### 参照

- Alias：DeepResearch 的多来源证据聚合和有界检索。
- AgentScope：`KnowledgeBase.search` 与 `RAGMiddleware` agentic 模式；混合排序由 BizInsight 检索适配层实现。

### 文件

- 新增 `src/bizinsight/rag/bm25.py`
- 新增 `src/bizinsight/rag/hybrid.py`
- 修改 `src/bizinsight/tools/knowledge.py`
- 修改 `src/bizinsight/agents/worker_base.py`
- 新增 `evaluations/rag/cases.yaml`
- 新增 `evaluations/run_rag_evaluation.py`
- 新增 `tests/unit/rag/test_bm25.py`
- 新增 `tests/unit/rag/test_rrf.py`
- 新增 `tests/integration/rag/test_hybrid_retrieval.py`

### 测试先行

1. 产品名/编号查询由 BM25 精确命中。
2. 同义表达由向量通道命中。
3. RRF 对共同高排名文档提升，不直接相加异构分数。
4. 元数据过滤、去重、Top-K 和上下文预算生效。
5. 向量异常时自动 BM25 降级并产生 `rag_vector_degraded`。
6. 无答案问题返回 no-match，不构造虚假 Evidence。

### 实现

1. 使用标准 Okapi BM25 实现/轻量依赖替换现有简化 IDF 打分，并保留中文二元/三元 tokenization。
2. `HybridKnowledgeRetriever` 并行调用 BM25 和 AgentScope `KnowledgeBase.search`。
3. 使用 RRF 融合排名，再按元数据、重复 chunk 和 token 预算过滤。
4. 将最终结果统一转换为 `KnowledgeSearchResult` 和 `DOC-*` Evidence。
5. 通过 AgentScope Toolkit 暴露一个 agentic `retrieve_internal_document`，由 Worker 决定何时查询。

### 验证与提交

```powershell
pytest tests/unit/rag tests/integration/rag -q
python evaluations/run_rag_evaluation.py --mode offline
```

在线向量索引就绪后执行混合评测，要求 Hit@3 ≥ 90%、MRR ≥ 0.75。

提交：`feat(rag): add evaluated BM25 vector hybrid retrieval`

## 8. 在线重复验证与 Agent 调优

### 参照

- Alias：MetaPlanner/Worker 的有界迭代、明确结束条件和失败记录。
- AgentScope：真实 `Agent.reply`、ReAct 工具调用、结构化输出和事件/usage。

### 文件

- 修改 Leader、Worker、Reviewer prompts（仅根据失败证据）
- 修改 `evaluations/run_evaluation.py`
- 新增 `evaluations/run_online_stability.py`
- 新增 `docs/online-baseline.md`

### 操作

1. 用户在本机 `.env` 配置重新生成的 Key；程序只读取是否存在。
2. 先运行一次最小 Leader/Worker/Tavily/Embedding 冒烟测试。
3. 黄金问题运行 5 次，保存每次原始结构化产物、事件、token、耗时、错误和报告。
4. 只根据真实失败调整 prompt、schema 描述、工具说明、超时和迭代上限；不得修改评测真值迎合结果。
5. 对 Tavily 成功、Tavily 降级、Embedding 成功和 BM25 降级分别留存证据。

### 验证与提交

```powershell
python evaluations/run_online_stability.py --runs 5
pytest -q
ruff check src tests evaluations scripts
```

门槛：结构化成功率 ≥ 80%，每次至少覆盖 4/5 黄金异常。未达标时保留真实结果和修复清单，不能报告为完成。

提交：`test(online): record BizInsight 1.0 stability baseline`

## 9. 1.0 文档、截图与最终验收

### 文件

- 修改 `README.md`
- 修改 `docs/architecture.md`
- 修改 `docs/evaluation.md`
- 修改 `docs/demo-script.md`
- 修改 `docs/retrospective.md`
- 修改 `docs/interview-notes.md`
- 修改 `references/alias-attribution.md`
- 更新 `docs/assets/` 中的真实 Web UI、事件和报告截图

### 操作

1. README 写出 offline、online、MCP、向量索引、Agent Service/Web UI 的可复现命令。
2. 架构文档逐项链接 Alias 固定 commit 参照与 AgentScope 2.0.7 API。
3. 评测文档分别报告离线、在线、BM25、向量和混合结果。
4. 录制 6～8 分钟演示：提问、规划、并行 Worker、MCP/RAG、Reviewer 返工、报告、降级、评测。
5. 面试材料明确哪些是 AgentScope 能力、Alias 职责迁移、BizInsight 原创和未完成的生产能力。

### 最终验收

```powershell
python scripts/generate_data.py
python scripts/build_knowledge_base.py
pytest -q
ruff check src tests evaluations scripts
python evaluations/run_evaluation.py --mode offline
python evaluations/run_rag_evaluation.py --mode offline
python -m bizinsight.cli --mode offline --question "分析公司2025年第四季度经营表现"
```

配置有效的新 Key 后：

```powershell
python scripts/build_knowledge_base.py --online-embedding
python evaluations/run_rag_evaluation.py --mode hybrid
python evaluations/run_online_stability.py --runs 5
```

人工验证官方 AgentScope Web UI 完整链路。检查 Git 历史、仓库无密钥、工作区干净。

提交：`docs: complete BizInsight Agent 1.0 delivery`

## 10. 停止条件

达到设计规格 Definition of Done 后停止增加 2.0 功能。真实企业数据、生产权限、长期记忆、定时监控、审批和多租户只记录为后续方向，不进入本轮实现。
