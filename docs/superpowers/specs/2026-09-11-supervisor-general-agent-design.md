# BizInsight 通用 Supervisor Agent 设计

## 目标

在不改动现有经营分析核心链路的前提下，新增一个基于 AgentScope 2.0.7 的通用入口 `SupervisorAgent`。它负责理解用户意图，并在通用模型回答、内部知识库检索、现有经营分析链路和实时天气工具之间进行选择。

完成后，用户既可以询问“你是谁”、进行普通聊天，也可以检索企业专业知识、查询实时天气，或启动现有的 Leader–Worker–MCP–RAG–Reviewer 报告流程。

## 设计原则

- 保留现有 `run_analysis`、`BizInsightLeader`、专业 Worker、Business Data MCP、Hybrid RAG、Reviewer 和 ReportBuilder。
- Supervisor 必须使用 AgentScope 的 `Agent`、`ReActConfig`、`Toolkit`、`FunctionTool`、`MCPClient` 和 Agent State。
- 普通问题不启动耗时的经营分析。
- 实时信息必须来自工具，不能由模型根据训练记忆编造。
- 不同会话的上下文和待补参数必须隔离。
- 新能力失败不得破坏已经稳定的经营分析链路。

## 总体架构

```text
用户消息
   |
   v
AgentScope SupervisorAgent
   |-- 身份、闲聊、写作、常识 --> 通用模型直接回答
   |-- 企业专业知识 -----------> 现有 Hybrid RAG
   |-- 企业经营诊断 -----------> 现有 run_analysis
   `-- 实时天气 ---------------> 独立 Weather MCP
```

只新增一个面向用户的 Supervisor Agent，不新增第二套经营分析 Worker 系统。现有 `BizInsightServiceAgent` 作为 AgentScope 服务适配器，把会话消息交给 Supervisor，而不是无条件调用 `run_analysis`。

## SupervisorAgent

### AgentScope 组成

Supervisor 使用正式的 AgentScope `Agent`，配置独立 system prompt、`ReActConfig`、`Toolkit` 和会话 State。每个用户会话创建或恢复一个独立 Supervisor 状态，禁止跨会话共享可变 Agent 上下文。

### 身份与普通对话

以下请求由 Supervisor 模型直接回答，不调用工具：

- “你是谁？”
- “你能做什么？”
- 普通闲聊、解释、写作、总结和稳定的常识问题。

身份回答应说明：BizInsight 是基于 AgentScope 构建的企业智能助手，能够进行普通交流、内部知识检索、实时工具查询和经过 Reviewer 审查的经营分析。不得声称具备尚未接入的能力。

### 工具集

Supervisor Toolkit 包含三类能力：

1. `search_internal_knowledge`
   - 复用当前 BM25 + AgentScope KnowledgeBase/Qdrant 的 Hybrid RAG。
   - 输入查询和 `top_k`，输出文档编号、标题、时间、部门、定位和摘要。
   - Supervisor 依据检索证据生成简洁回答并保留引用。

2. `run_business_analysis`
   - 直接调用现有 `run_analysis`，不复制或改写其内部逻辑。
   - 返回运行状态、Reviewer 状态、通过审查的核心结论、报告地址、错误和数据限制。
   - 仅在用户明确要求经营诊断、多维分析、原因分析或管理报告时调用。

3. Weather MCP 工具
   - 通过独立 AgentScope `MCPClient` 连接 Weather MCP Server。
   - Weather MCP 与 Business Data MCP 分离，避免权限和生命周期混杂。
   - 提供地点解析、当前天气和短期预报。

## 路由规则

Supervisor 的 system prompt 明确以下决策顺序：

1. 身份、能力、闲聊、写作和稳定常识由模型直接回答。
2. 企业内部制度、产品、交付规范、客户访谈等专业知识先调用内部 RAG。
3. 需要多维经营数据、原因诊断、Reviewer 或报告时调用现有经营分析。
4. 天气、温度、降水和预报等实时请求调用 Weather MCP。
5. 实时天气缺少城市时先追问，不调用工具。
6. 问题包含多种意图时，只调用必要工具并合并结果。
7. 路由不确定或高成本分析意图不明确时先澄清。

RAG 未命中时，Supervisor 可以提供一般性知识，但必须明确区分“内部知识库没有找到依据”和“以下是通用回答”。

## Weather MCP

### 数据源

Weather MCP 使用 Open-Meteo，无需新增 API Key：

- Geocoding API：将城市名称解析为经纬度、行政区和时区。
- Forecast API：查询当前天气、当天和短期预报。

### MCP 工具

- `resolve_weather_location(query, language="zh")`
  - 返回有限数量的候选地点。
  - 城市存在歧义时由 Supervisor 请用户确认。

- `get_weather(latitude, longitude, timezone, forecast_days=2)`
  - 返回当前温度、体感温度、湿度、降水、天气代码、风速以及逐日最高最低温和降水概率。
  - `forecast_days` 设置明确上限，避免无界响应。

所有网络调用设置连接与读取超时。MCP 返回结构化错误，不返回 Python 堆栈。响应包含数据来源和时间，便于 Supervisor 向用户说明时效性。

## 会话级多轮上下文

第一版只支持会话级短期上下文，不做跨会话长期记忆：

- “今天天气怎么样？”时 Supervisor 追问城市。
- 用户下一轮回答“上海”后，Supervisor 结合上一轮意图调用 Weather MCP。
- “那明天呢？”沿用当前会话已经确认的城市。
- 新会话不会自动继承城市或聊天内容。
- 经营分析只把摘要和报告引用放回 Supervisor 上下文，不注入完整报告和全部证据，避免上下文膨胀。

会话继续使用 AgentScope State 和现有 Service Agent 的 session 生命周期；不额外引入 Redis 之外的新记忆框架。开发和单元测试可以使用内存 State，部署方式继续遵循现有 AgentScope Service 配置。

## 与现有链路的边界

现有经营分析链路保持为单一入口：

```text
run_business_analysis tool
  -> run_analysis
  -> BizInsightLeader
  -> Finance / Customer / Delivery / External Workers
  -> Business MCP + Hybrid RAG + Tavily
  -> EvidenceReviewerAgent
  -> ReportBuilder
```

Supervisor 不直接查询经营数据库，不接管 Reviewer，不修改 Worker 数据权限，也不根据工具结果自行替代经营报告。它只决定是否调用完整链路，并向用户呈现结果。

## 错误和降级

- 天气请求缺少城市：主动追问。
- 地点匹配存在歧义：展示少量候选项，请用户确认。
- Weather MCP 或 Open-Meteo 不可用：明确说明实时数据暂不可用，不输出推测天气。
- RAG 无结果：标注未命中，可选择给出明确标识的通用回答。
- 经营分析返回 `partial`：作为正常审查结果展示通过结论和限制，不视为系统异常。
- 经营分析失败：返回安全错误说明，保留 Supervisor 会话，使用户可以继续聊天或重试。
- Supervisor 模型输出或工具调用失败：允许一次受控重试，之后返回可理解的失败响应。
- MCP 连接必须幂等关闭；Weather MCP 的异常不能影响 Business Data MCP。

## 事件与可观测性

Supervisor 记录：

- 选中的处理路径；
- 调用的工具名和耗时；
- 模型 token；
- RAG 命中或未命中；
- Weather MCP 成功、歧义或降级；
- 经营分析的 `run_id`、Reviewer 状态和报告引用。

事件和日志不得记录 API Key、完整会话隐私数据或内部异常堆栈。

## 测试与验收

### 自动测试

- “你是谁？”直接回答身份，工具调用数为零。
- 普通写作请求由通用模型回答，不调用 RAG 或经营分析。
- 企业专业知识问题调用 Hybrid RAG，并保留文档引用。
- 经营诊断问题只调用一次现有 `run_analysis`。
- 天气缺少城市时追问，Weather MCP 调用数为零。
- 下一轮补充城市后调用 Weather MCP。
- 完整天气问题直接调用 Weather MCP，并返回时间和来源。
- 歧义城市、网络超时和 MCP 错误均返回安全响应。
- 两个会话的城市和消息上下文互不串线。
- Supervisor 关闭时可靠释放 Weather MCP。
- 现有经营分析、MCP、RAG、Reviewer、报告及评测测试全部继续通过。

### 真实在线验收

使用真实模型逐项验证：

1. “你是谁？”自然回答且不调用工具。
2. 普通常识或写作问题由模型直接回答。
3. 企业内部专业问题检索现有知识库并引用来源。
4. 经营问题完整进入现有多 Agent 分析链路。
5. “今天天气怎么样？”追问城市；下一轮“上海”成功返回实时天气。
6. “北京明天会下雨吗？”单轮调用 Weather MCP。
7. 经营分析与天气能力连续使用后，Agent 状态和 MCP 均正常。

## 完成定义

满足以下条件即完成：

- 用户不再被迫把所有问题转换成经营分析报告。
- Supervisor 能可靠选择模型、RAG、现有经营分析和 Weather MCP。
- 多轮天气补参有效，会话之间完全隔离。
- 现有核心经营分析代码和运行结果没有回归。
- 项目能够清晰展示 AgentScope Agent、ReAct、Toolkit、MCP、RAG、State 和多 Agent 编排能力。
