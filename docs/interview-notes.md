# 面试准备

## 30 秒项目表达

我基于 AgentScope 2.0.7 做了一个企业经营异常诊断智能体。它参考官方 Alias 的 Planner–Worker–Toolkit 架构思想，但针对版本不兼容进行了重写。Leader 拆解问题，三个内部领域 Worker 和一个外部研究 Worker 并行取证，Reviewer 复算指标并审查证据，最终输出可追溯报告。项目有固定种子的合成数据、离线降级和 15 条自动评测，离线基线 99.93 分。

## 高频追问

### 为什么不是单 Agent？

财务销售、客户产品、交付和外部资料的数据权限、指标口径和提示词不同。拆成 Worker 后职责更清晰，工具可以按域授权，综合问题还能并行；Leader 只做计划和汇总，不直接接触所有细节。

### AgentScope 的优势体现在哪里？

不是只调用一次模型，而是使用了 `Agent` 统一智能体生命周期，`Toolkit/FunctionTool` 暴露类型化只读工具，Pydantic 结构化输出约束 Agent 间协议，`CustomEvent` 记录任务状态，并通过官方 `create_app` 接入 Agent Service。模型通过 `ChatModelBase` 注入，所以测试和在线模型可以替换。

### 如何参考 Alias，而不是换皮？

我固定了 Alias commit，先审计旧版与 2.0.7 差异，只保留 Meta Planner、领域 Worker 和 Toolkit 的职责划分。数据生成、业务指标、权限、Evidence、Reviewer、模板和评测均为本项目重新设计，未迁移 Alias 前端、Memory、用户系统或旧 API。

### 如何减少幻觉？

关键数字不由模型心算，而由白名单 SQL 和指标函数计算；Finding 中的 MetricValue 必须引用 Evidence；Reviewer 再按同一指标字典复算。没有证据的结论被拒绝，外部趋势只能作为背景或待验证假设。

### 工具安全怎么做？

先解析并拒绝非 `SELECT/WITH`、多语句和写关键字，再用 SQLite authorizer 拦截写动作；每个 Worker 还有数据集和指标白名单，查询行数、耗时、图表文件名及输出目录均受限。

### 为什么需要离线模式？

默认测试若依赖模型会产生费用、网络失败和随机波动。单元/集成测试使用 Mock Model 验证真实 AgentScope 消息和结构化输出；端到端离线 Worker 验证整条业务链路。真实百炼调用只在 `online` 标记或 CLI 显式模式下进行。

### 如何证明效果？

使用 15 个问题从指标准确性 35%、异常覆盖 25%、证据 20%、稳健性 10% 和报告质量 10% 五方面评分。黄金案例覆盖 5/5 异常，离线平均 99.93。这个结果只代表合成场景基线，我不会把它包装成真实生产效果。

### 最值得讲的失败与修复是什么？

一开始最容易犯的错误是为了复用 Alias 而兼容旧接口。审计后我发现维护两套抽象会让系统复杂且难测，于是改为“职责迁移、代码重写”，并用结构化契约把各 Agent 解耦。这比简单复刻 Demo 更能体现工程判断。
# BizInsight Agent 1.0 面试主线

一句话：这是一个基于 AgentScope 2.0.7 的多智能体经营诊断系统，借鉴 Alias 的 Planner–Worker–Toolkit 分工，用新版公共 API 重构，并通过确定性工具、证据审查和单轮返工控制大模型幻觉。

讲链路时按这个顺序：Leader 把自然语言问题转成带期间、维度和依赖的 `AnalysisPlan`；Workflow 并行调度领域 Worker；Worker 通过 AgentScope Toolkit 调用本地 RAG 和 Scoped MCP，不直接编造指标；Reviewer 从数据库复算并审查证据，问题只退回原 Worker 一次；通过的 Finding 才进入十一节报告。官方 Web UI、HTTP 和 CLI 最终都调用同一个 `run_analysis`。

RAG 的重点不是“用了向量库”，而是为什么混合：BM25 擅长 CloudFlow v3.2、制度编号等精确词，Qwen embedding 擅长同义表达；AgentScope KnowledgeBase 管理 embedding 与 Qdrant，BizInsight 用 RRF 融合名次，避免把不同量纲的分数硬相加。向量失败会有事件并降级到 BM25。

MCP 的重点是权限边界：每个 Worker 一个 AgentScope MCPClient/STDIO 子进程，角色 scope 固定在启动参数中；Server 只暴露五个业务只读工具，SQLite authorizer、表/指标 allowlist、单语句、超时和行数上限共同防止越权。

测试策略：默认 Mock/离线测试真实跑 AgentScope 消息、结构化输出、Toolkit、MCPClient 和 KnowledgeBase 的代码路径，不联网、不花钱、结果可复现；真实百炼/Tavily/embedding 通过显式 online 命令单独做五次稳定性验收。

## 真实模型验证记录（2026-09-10）

首次真实模型验收（qwen-plus + Tavily，`evaluations/run_online_stability.py`，每轮独立进程跑 CLI）：

- 结果：5/5 轮成功（`outputs/online-stability/summary.json`），每轮 4 个 Worker 全部产出 Finding；4 轮零错误，1 轮因 DashScope 服务端偶发 400（模型生成非法 JSON function.arguments）有 1 个 Worker 失败，属供应商侧波动。
- 过程中修复的四个真实模型路径问题（Mock 测不出来）：
  1. MCP 关闭时 anyio 内部 cancel scope 的 CancelledError 穿透 `except Exception` 取消主任务 → close 时吞掉并 `uncancel()` 复位；
  2. LLM Leader 幻觉数据集名（把指标名当数据集）→ 提示词给权威清单 + 代码层白名单归一化兜底；
  3. `ReActConfig(max_iters=1)` 不足以完成"取证→输出 Finding"→ 提到 3，Worker 耗时 50-80s，workflow 超时提至 120s；
  4. AgentScope 权限引擎把未标注只读的 MCP 工具默认判 ASK，裸 CLI 无人确认直接退出 → MCP 工具加 `readOnlyHint` 标注走只读快速通道。
