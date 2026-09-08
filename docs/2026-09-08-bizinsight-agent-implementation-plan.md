# BizInsight Agent 实施计划

- 日期：2026-09-08
- 依据：[BizInsight 企业经营异常诊断智能体设计规格](../specs/2026-09-08-bizinsight-agent-design.md)
- 目标：10 个工作日内交付可运行、可演示、可评测的 MVP
- 实施方式：测试优先；每个阶段通过验证后再进入下一阶段

## 0. 开始前的目录与权限约定

正式项目目标目录为：

```text
G:\Agent\AgentScope\enterprise-intelligence-agent
```

官方参考仓库目标目录为：

```text
G:\Agent\AgentScope\agentscope-samples
```

这两个目录与 `agentscope-main` 保持同级。开始实施前，需要将目标项目目录加入 Codex 当前工作区的可写根目录，或在 Codex 中直接打开该目录。不要把 `agentscope-samples` 克隆进 `agentscope-main`。

完成每项任务后提交一次小而清晰的 Git commit。提交信息使用 Conventional Commits 风格，例如 `feat(data): add deterministic synthetic dataset generator`。

## 1. 克隆参考仓库并建立独立项目

### 目标

获得只读参考代码、独立项目和可追溯的 Alias 来源。

### 操作

1. 克隆 `https://github.com/agentscope-ai/agentscope-samples.git` 到同级目录。
2. 记录克隆时的 commit SHA。
3. 创建 `enterprise-intelligence-agent` 独立目录并执行 `git init`。
4. 添加基础文件：
   - `README.md`
   - `LICENSE`
   - `NOTICE`
   - `.gitignore`
   - `.env.example`
   - `pyproject.toml`
   - `references/alias-attribution.md`
5. 将设计规格和本实施计划复制到独立项目的 `docs/`。
6. 在 attribution 中写明 AgentScope Samples URL、Alias 路径、commit SHA、许可证和计划迁移模块。

### 验证

- `git status` 只显示独立项目文件。
- Alias 来源和版本可从 attribution 文档追溯。
- `.env`、数据库和输出文件被 `.gitignore` 排除。

### 提交

`chore: initialize standalone BizInsight Agent project`

## 2. Alias 兼容性审计与最小 AgentScope 冒烟测试

### 目标

在迁移代码前确定 Alias 与 AgentScope 2.0.7 的真实兼容边界。

### 文件

- `docs/alias-compatibility-audit.md`
- `src/bizinsight/app.py`
- `src/bizinsight/config.py`
- `tests/integration/test_agent_smoke.py`

### 操作

1. 检查 Alias 的 `_meta_planner.py`、`_react_worker.py`、`_data_science_agent.py`、`_deep_research_agent_v2.py`、`data_source/` 和 `tools/`。
2. 记录每个模块的 AgentScope API、第三方依赖、可直接迁移部分和需重写部分。
3. 在独立虚拟环境安装 AgentScope 2.0.7 和最小依赖。
4. 从环境变量读取百炼 API Key 和模型名称；缺失时给出明确错误，不提供隐式默认密钥。
5. 创建一个最小 AgentScope Agent，完成一次结构化响应冒烟测试。

### 验证

- 不导入 Alias 时，最小 Agent 能在 AgentScope 2.0.7 上运行。
- 兼容性文档对每个计划迁移模块给出明确的“迁移、改写或删除”结论。
- 测试默认使用 Mock 模型；真实百炼调用放在显式 smoke 标记下。

### 提交

`chore(core): audit Alias compatibility and add AgentScope smoke test`

## 3. 定义领域模型和结构化契约

### 目标

先固定 Agent 之间的接口，再实现行为。

### 文件

- `src/bizinsight/schemas/plan.py`
- `src/bizinsight/schemas/evidence.py`
- `src/bizinsight/schemas/finding.py`
- `src/bizinsight/schemas/review.py`
- `tests/unit/schemas/test_plan.py`
- `tests/unit/schemas/test_finding.py`
- `tests/unit/schemas/test_review.py`

### 操作

1. 用 Pydantic 定义 `AnalysisPlan`、`AnalysisTask`、`MetricValue`、`Evidence`、`Finding`、`RevisionRequest` 和 `ReviewResult`。
2. 约束计划最多四个任务。
3. 约束置信度范围为 0～1。
4. 约束每个关键 Finding 至少引用一个证据。
5. 约束网页证据必须包含 URL 和访问时间。

### 测试顺序

1. 先写非法数据应失败的测试。
2. 运行测试并确认失败。
3. 实现最小 Schema。
4. 运行测试并确认通过。

### 提交

`feat(schemas): define plans findings evidence and review contracts`

## 4. 实现确定性合成数据生成器

### 目标

生成可重复、有跨表关联、有隐藏经营异常的数据环境。

### 文件

- `scripts/generate_data.py`
- `src/bizinsight/data/generator.py`
- `src/bizinsight/data/scenarios.py`
- `data/data_dictionary/metrics.yaml`
- `data/data_dictionary/tables.yaml`
- `evaluations/ground_truth/golden_case.json`
- `tests/unit/data/test_generator.py`
- `tests/unit/data/test_scenarios.py`

### 操作

1. 使用固定随机种子生成客户、商机、合同、订阅、使用、项目、工单和回款数据。
2. 实现五类隐藏异常及其跨表关联。
3. 生成 CSV 和 SQLite。
4. 生成只供评测读取的标准答案。
5. 生成数据质量摘要，包括记录数、缺失率、主外键完整率和目标指标。

### 验证

- 相同种子产生相同文件哈希和核心指标。
- 主外键完整率为 100%。
- 2026 Q2 的核心指标落入设计规格规定的合理区间。
- Agent 运行目录和知识库路径不能访问 `ground_truth`。

### 提交

`feat(data): add reproducible synthetic business dataset`

## 5. 生成企业知识文档并建立本地检索

### 目标

让部分结论必须结合结构化数据和内部文档才能得出。

### 文件

- `scripts/build_knowledge_base.py`
- `data/knowledge/*.md`
- `src/bizinsight/tools/knowledge.py`
- `tests/unit/tools/test_knowledge.py`
- `tests/integration/test_knowledge_retrieval.py`

### 操作

1. 创建 10～15 份虚构内部文档。
2. 每份文档包含稳定文档 ID、标题、日期、部门和正文。
3. 通过 AgentScope RAG 或经兼容性审计确认的本地检索接口建立索引。
4. 返回 `DOC-*` 证据编号、文档位置和引用片段。

### 验证

- 能检索 v3.2 发布说明、故障复盘、SLA、验收规则和输单会议纪要。
- 引用包含正确文档 ID 和片段位置。
- 检索不到时返回空结果和明确原因，不生成伪引用。

### 提交

`feat(rag): add synthetic enterprise knowledge base`

## 6. 实现只读数据库与指标工具

### 目标

把数字计算从 LLM 中移出，提供可复算证据。

### 文件

- `src/bizinsight/data/provider.py`
- `src/bizinsight/tools/database.py`
- `src/bizinsight/tools/metrics.py`
- `src/bizinsight/tools/charts.py`
- `tests/unit/tools/test_readonly_sql.py`
- `tests/unit/tools/test_metrics.py`
- `tests/unit/tools/test_charts.py`

### 操作

1. 实现 `BusinessDataProvider`。
2. SQL 解析后只允许 `SELECT` 和只读 CTE。
3. 拒绝多语句、写操作、DDL 和危险 pragma。
4. 为常用经营指标提供确定性函数。
5. 每次查询生成 `DB-*` 或 `CALC-*` 证据记录。
6. 图表只读取结构化序列并写入指定输出目录。

### 验证

- 所有危险 SQL 测试均被拒绝。
- 核心指标与 ground truth 精确一致。
- 查询结果受行数和超时限制。
- 图表可在无 GUI 环境生成。

### 提交

`feat(tools): add safe business analytics toolkit`

## 7. 实现 Worker 基类和三个内部分析 Agent

### 目标

形成职责隔离、输出一致的业务分析 Worker。

### 文件

- `src/bizinsight/agents/worker_base.py`
- `src/bizinsight/agents/finance_sales.py`
- `src/bizinsight/agents/customer_product.py`
- `src/bizinsight/agents/delivery.py`
- `src/bizinsight/prompts/*.md`
- `tests/integration/agents/test_internal_workers.py`

### 操作

1. 基于 Alias ReAct Worker 思路实现统一 Worker 基类。
2. 每个 Worker 只注册授权的数据集和工具。
3. Prompt 明确事实、解释、因果和限制的边界。
4. Worker 输出必须通过 `Finding` 校验。
5. 结构错误时只允许一次纠正重试。

### 验证

- 财务销售 Agent 无法访问客服原始明细。
- 客户产品 Agent 能联合订阅、使用和工单数据。
- 交付 Agent 能识别延期、超工时和毛利关联。
- 三个 Agent 不得读取 ground truth。

### 提交

`feat(agents): add domain-specific internal analysis workers`

## 8. 实现 Tavily 外部情报 Agent 和离线降级

### 目标

获得带来源的实时行业背景，同时保证断网可运行。

### 文件

- `src/bizinsight/tools/external_search.py`
- `src/bizinsight/agents/external_research.py`
- `data/knowledge/external_fallback/*.md`
- `tests/unit/tools/test_external_search.py`
- `tests/integration/agents/test_external_research.py`

### 操作

1. 封装 `search`、`extract` 和 `health_check`。
2. 输出 `WEB-*` 证据，保存标题、URL、摘要和访问时间。
3. Prompt 禁止使用外部资料直接证明虚构企业内部因果。
4. API 缺失、超时或失败时切换本地行业资料。

### 验证

- Mock 在线检索能产生合法网页证据。
- 无 Tavily Key 时自动进入离线模式。
- 离线报告明确标注未完成实时搜索。

### 提交

`feat(research): add Tavily intelligence with offline fallback`

## 9. 实现 Leader 规划和并行调度

### 目标

把 Alias Meta Planner 思路收敛为经营诊断工作流。

### 文件

- `src/bizinsight/agents/leader.py`
- `src/bizinsight/orchestration/workflow.py`
- `tests/unit/orchestration/test_routing.py`
- `tests/integration/orchestration/test_workflow.py`

### 操作

1. 规范时间范围、指标、业务对象和分析假设。
2. 生成最多四个结构化任务。
3. 依据任务依赖并行执行 Worker。
4. 隔离单个 Worker 超时和失败。
5. 收集 Finding、Evidence、执行耗时和错误信息。

### 验证

- 综合问题能路由到所有必要 Worker。
- 专项问题只调用必要 Worker。
- 一个 Worker 失败时其他结果仍能返回。
- 计划和执行状态能通过 AgentScope 事件流观察。

### 提交

`feat(orchestration): add business planning and worker coordination`

## 10. 实现 Reviewer 和一次定向返工

### 目标

阻止数字错误、伪证据和过度因果表述进入最终报告。

### 文件

- `src/bizinsight/agents/reviewer.py`
- `src/bizinsight/orchestration/review_loop.py`
- `tests/unit/agents/test_reviewer_rules.py`
- `tests/integration/orchestration/test_revision_loop.py`

### 操作

1. 先执行确定性指标复算和证据存在性检查。
2. 再让 Reviewer 检查语义支持、冲突和因果强度。
3. 输出接受、拒绝和修订请求。
4. 工作流最多执行一次定向返工。
5. 未解决问题写入限制，不进入无限循环。

### 验证

- 故意注入错误续费分母时 Reviewer 必须拒绝。
- 无证据 Finding 必须拒绝或降级为假设。
- 外部趋势被错误用作内部原因时必须要求修订。
- 返工次数严格不超过一次。

### 提交

`feat(review): add evidence validation and bounded revision loop`

## 11. 实现报告和图表输出

### 目标

生成管理者可阅读、关键结论可追溯的正式产物。

### 文件

- `src/bizinsight/tools/reports.py`
- `src/bizinsight/templates/report.md.j2`
- `src/bizinsight/templates/report.html.j2`
- `tests/unit/tools/test_reports.py`
- `tests/golden/test_report_snapshot.py`

### 操作

1. 仅接收已审查的 Finding 和明确的限制。
2. 生成设计规格规定的十一节报告。
3. 行动建议包含优先级、依据、负责人类型和时间范围。
4. 生成收入、毛利、续费、赢单和验收趋势图。
5. 汇总 DB、DOC、WEB 和 CALC 证据索引。

### 验证

- 报告中的数字与 Finding 一致。
- 每个关键结论都能跳转或定位到证据索引。
- HTML 离线打开时文本和本地图表正常显示。
- Snapshot 变化需要人工确认，防止模板意外退化。

### 提交

`feat(reporting): generate traceable business diagnosis reports`

## 12. 接入 Agent Service、Web UI 与 CLI

### 目标

提供可展示界面和可靠兜底入口。

### 文件

- `src/bizinsight/app.py`
- `src/bizinsight/cli.py`
- `scripts/start_backend.ps1`
- `scripts/start_webui.ps1`
- `tests/e2e/test_cli_golden_case.py`
- `tests/e2e/test_service_health.py`

### 操作

1. 通过 AgentScope Agent Service 暴露 BizInsight 工作流。
2. 复用 AgentScope Web UI 的聊天、任务和事件展示能力。
3. CLI 支持问题、在线/离线模式、输出目录和会话 ID。
4. 启动时检查数据库、知识库、模型配置和 Tavily 状态。
5. 敏感配置只从环境变量加载。

### 验证

- 健康检查返回模型、数据库、知识库和搜索状态，但不泄露密钥。
- CLI 能离线完成黄金案例。
- Web UI 能看到计划、工具执行、审查和最终报告事件。

### 提交

`feat(app): expose BizInsight through AgentScope service and CLI`

## 13. 建立自动评测系统

### 目标

用数据证明智能体效果，而非只依赖演示观感。

### 文件

- `evaluations/cases/*.yaml`
- `evaluations/run_evaluation.py`
- `evaluations/scorers/metrics.py`
- `evaluations/scorers/evidence.py`
- `evaluations/scorers/robustness.py`
- `tests/unit/evaluations/test_scorers.py`

### 操作

1. 编写约 15 个评测问题。
2. 实现指标准确性、异常覆盖、证据完整性、稳健性和报告质量评分。
3. 分开记录在线与离线运行结果。
4. 记录模型、时间、token、工具次数、耗时和错误。
5. 输出 JSON 和 Markdown 评测报告。

### 验证

- 评分器对人工构造的正确和错误答案给出预期分数。
- 黄金案例识别至少 4/5 关键异常。
- 综合分不低于 80/100。
- 未达标时保留真实结果并建立修复清单。

### 提交

`feat(evaluation): add reproducible business-agent benchmark`

## 14. 文档、演示与交付验收

### 目标

让项目能被 MT、面试官和其他开发者复现与理解。

### 文件

- `README.md`
- `docs/architecture.md`
- `docs/dataset.md`
- `docs/evaluation.md`
- `docs/demo-script.md`
- `docs/retrospective.md`
- `docs/interview-notes.md`

### 操作

1. README 写明安装、配置、数据生成、CLI、Web UI、测试和评测命令。
2. 明确数据完全合成、项目未在真实公司生产环境部署。
3. 添加架构图、数据关系图、报告截图和评测表。
4. 准备 6～8 分钟演示脚本和录屏。
5. 复盘记录问题、取舍、修复过程和下一阶段方向。
6. 面试材料覆盖 AgentScope 选型、Alias 改造、工具安全、证据机制、评测和局限。

### 最终验收命令

```powershell
python scripts/generate_data.py
pytest
python evaluations/run_evaluation.py --mode offline
python -m bizinsight.cli --mode offline --question "分析公司2026年第二季度经营表现下降的主要原因"
```

随后执行一次显式在线冒烟测试，验证百炼和 Tavily。

### 提交

`docs: complete BizInsight delivery and interview materials`

## 15. 工作日映射

| 工作日 | 对应任务 |
|---|---|
| 1 | 任务 1～3 |
| 2 | 任务 4 |
| 3 | 任务 5～6 |
| 4 | 任务 7 |
| 5 | 任务 9 |
| 6 | 任务 8 |
| 7 | 任务 10 |
| 8 | 任务 11～12 |
| 9 | 任务 13 |
| 10 | 任务 14 与最终验收 |

## 16. 风险优先级

1. **Alias 版本不兼容**：第一天完成审计；只迁移职责清晰的模块。
2. **模型结构化输出不稳定**：Pydantic 校验、一次纠错和确定性兜底。
3. **数据太随机导致无明确结论**：固定种子、场景注入和自动指标测试。
4. **多 Agent 成本和耗时过高**：专项问题按需路由，综合问题最多四个并行任务。
5. **Tavily 或网络失败**：本地资料降级，外部研究不阻塞内部诊断。
6. **Web UI 环境问题**：CLI 和录屏作为交付兜底。
7. **项目像官方 Demo 换皮**：独立数据模型、领域工具、证据契约、Reviewer、评测和归因文档明确原创贡献。

## 17. 完成判定

只有设计规格中的 Definition of Done、评测阈值、离线降级和复现步骤全部满足，MVP 才标记完成。功能存在但测试不通过、只能依靠一次幸运模型输出、或无法在无 Tavily 情况下运行，均不视为完成。
