# BizInsight Web 分析工作台设计

## 目标

在不修改已经验证通过的 `SupervisorAgent`、Leader、专业 Worker、Business Data MCP、混合 RAG、天气 MCP、Reviewer 与报告生成逻辑的前提下，为项目增加一个自包含的网页工作台。用户能够在浏览器中输入问题、发送请求并看到智能体回复；当问题触发经营分析时，页面进一步展示执行链路与生成的 HTML 报告。

网页和 API 由现有 FastAPI 服务统一提供。普通问答、内部知识检索、天气查询和经营分析全部复用命令行已经使用的同一个 Supervisor，不建立第二套路由或业务逻辑。

## 范围

本次包含：

- 与参考设计一致的三栏企业分析工作台；
- 同源静态页面与专用问答 API；
- 基于 `session_id` 的多轮会话隔离；
- 用户问题、智能体文本回复、路由类型和报告链接的完整传递；
- 请求中、成功、空状态和失败状态；
- 桌面端与窄屏响应式布局；
- 后端接口测试、静态页面测试和现有测试回归；
- 自包含的一键启动方式。

本次不包含：

- 修改 Supervisor 的提示词、路由规则或工具；
- 修改经营分析的计划、Worker、证据审核、指标、RAG 或报告逻辑；
- 用户账户、权限管理、会话持久化数据库或多人协作；
- 复制或改造项目外部的 AgentScope 官方 Web UI；
- 在首版实现报告编辑器或 Markdown/HTML 内容转换器。

## 方案选择

采用“原生 HTML/CSS/JavaScript + FastAPI 同源托管”。它不增加 Node 构建链，能够直接放入现有 Python 包，并避免跨域和双服务启动问题。React/Vite 对首版交互而言成本偏高；改造 AgentScope 官方 Web UI 则难以精确实现参考设计，而且会继续依赖项目外目录。

## 系统架构

```text
Browser Web Workbench
        │
        │ POST /bizinsight/chat
        ▼
FastAPI Web Adapter
        │  validate input / resolve session / normalize result
        ▼
Existing BizInsightServiceAgent (SupervisorAgent)
        ├── general conversation
        ├── internal RAG
        ├── real-time weather MCP
        └── existing run_analysis workflow
                 │
                 └── controlled /bizinsight/reports/... URL
```

Web 适配层只承担 HTTP 输入输出转换和会话生命周期管理。它通过项目现有模型构建函数创建 `BizInsightServiceAgent`，调用其 `reply()`，并从返回消息的文本和 metadata 中提取页面所需数据。核心智能体及其工具保持原样。

## 后端组件

### 页面托管

FastAPI 在 `/` 提供工作台入口，并在受控前缀下托管打包进 `bizinsight` 的 CSS 和 JavaScript。页面与 API 同源运行在 `127.0.0.1:8000`，无需 CORS 配置。

### 问答接口

新增 `POST /bizinsight/chat`：

请求：

```json
{
  "question": "请综合分析2026年第二季度经营表现下降的主要原因",
  "session_id": "web-generated-session-id"
}
```

约束：

- `question` 去除首尾空白后不能为空，并设置合理长度上限；
- `session_id` 只接受安全字符和合理长度；
- 缺失 `session_id` 时允许服务端生成，但浏览器正常流程始终显式发送；
- 不接受由浏览器覆盖模型、工具、系统提示词或输出目录。

成功响应：

```json
{
  "session_id": "web-generated-session-id",
  "answer": "智能体的最终文本回复",
  "route": "business_analysis",
  "report_url": "/bizinsight/reports/.../report.html",
  "run_id": "optional-run-id",
  "review_status": "optional-review-status"
}
```

`route` 取 Supervisor 实际记录的路由，例如 `general`、`knowledge`、`weather`、`weather_unavailable` 或 `business_analysis`。`report_url`、`run_id` 和 `review_status` 仅在智能体 metadata 实际提供时返回，不由 Web 层推断或伪造。

### 会话管理

服务进程内维护有限容量的 `session_id -> BizInsightServiceAgent` 映射，使同一浏览器会话保留 Supervisor 上下文，不同会话互相隔离。创建和访问受异步锁保护；采用有限容量或过期回收，防止长期运行时无限增长。同一会话的并发请求串行化，避免同一个有状态 Agent 同时执行。

该内存会话只用于本地首版，不改变 AgentScope Service 的现有存储配置，也不承诺服务重启后恢复。

### 错误处理

- 输入问题不合法时返回 `422` 和可直接展示的中文原因；
- 模型、MCP 或工作流异常时返回稳定的错误结构，不向页面泄露密钥、堆栈或绝对文件路径；
- 页面显示“本次请求未完成，请重试”，保留输入内容并重新启用发送按钮；
- `/bizinsight/health` 继续用于状态检查，仍只返回 readiness，不返回凭据。

## 页面设计

### 视觉系统

页面忠实采用参考图的清爽企业分析风格，但不依赖外部字体或图标服务：

- `Canvas`：`#F4F8FD`，页面冷白底；
- `Surface`：`#FFFFFF`，主要卡片；
- `Biz Blue`：`#1268F3`，主操作和执行进度；
- `Signal Cyan`：`#DCEBFF`，选中态和信息背景；
- `Healthy Green`：`#16A66A`，真实在线/完成状态；
- `Ink`：`#17233C`，正文和数据文本。

标题和正文使用系统中文无衬线字体栈，数据、时间和短状态使用等宽数字特征。阴影保持克制，主要依靠浅色分区、细边框和间距建立层级。

页面的识别性元素是“可验证执行链路”：只有实际发生的路由和产物才会点亮，不用装饰性动画假装工具正在运行。

### 桌面布局

```text
┌──────────────────────────── Header / readiness ────────────────────────────┐
├──────────────┬──────────────────────────────────────┬───────────────────────┤
│ Navigation   │ Ask + conversation                   │ Report preview        │
│              ├──────────────────────────────────────┤                       │
│              │ Execution route / capability cards  │ Empty or HTML report  │
└──────────────┴──────────────────────────────────────┴───────────────────────┘
```

- 顶部：品牌、整体在线状态，以及 AgentScope、MCP、RAG、Tavily readiness；
- 左侧：分析工作台、报告预览、知识库/RAG；首版以分析工作台为主视图；
- 中部上方：问题输入、示例问题、发送按钮和会话消息；
- 中部下方：Supervisor、Leader、专业 Worker、外部研究和 Reviewer 节点；
- 右侧：报告空状态或经营分析生成后的 HTML 预览及完整报告入口。

在窄屏下按“问答、执行链路、报告”顺序纵向排列，左侧导航收拢为横向入口。所有操作具备清晰的键盘焦点，状态不只依赖颜色表达，并尊重 `prefers-reduced-motion`。

## 页面状态与交互

### 初始状态

页面启动后调用健康检查并显示真实 readiness。右侧明确显示“尚未生成报告”，提示只有经营分析问题会生成报告。输入区展示参考图中的经营分析示例，同时也允许普通聊天、知识问答和天气查询。

### 发送状态

用户点击“开始分析”或使用约定的键盘操作后：

- 用户消息立即进入会话区；
- 输入区保留问题但暂时禁用重复发送；
- 显示运行计时和中性的“正在处理”；
- 在响应返回前不伪造 Worker 逐步完成状态。

### 成功状态

- 始终展示 `answer`；
- `general` 只点亮 Supervisor，右侧保持报告空状态；
- `knowledge` 点亮 Supervisor 与 RAG；
- `weather` 点亮 Supervisor 与天气 MCP；
- `business_analysis` 点亮完整经营分析链路，并使用返回的 `report_url` 加载右侧报告；
- `weather_unavailable` 展示降级状态，但仍以智能体最终回答为准。

报告使用受控 iframe 预览，并提供“打开完整报告”链接。只有同源且位于 `/bizinsight/reports/` 下的 URL 才能进入 iframe。

### 失败状态

会话区显示明确错误，运行计时停止，发送按钮恢复可用。用户问题和输入内容不被清空，便于直接重试。右侧已有报告不因后续一次失败而消失。

## 安全边界

- 浏览器不能控制模型参数、工具列表、系统提示词、工作模式或文件输出路径；
- 报告继续由现有受控静态目录暴露；
- 页面通过文本节点或等价安全方式渲染回答，不把模型文本作为任意 HTML 注入；
- iframe 只接受受控报告 URL；
- API 错误不返回内部堆栈、环境变量或绝对路径；
- 会话 ID 经校验后使用，不直接拼接为任意文件系统路径。

## 启动方式

`scripts/start_backend.ps1` 继续启动同一个 FastAPI 服务。`scripts/start_webui.ps1` 改为启动或复用本项目后端，并提示/打开本地工作台地址，不再要求相邻目录中的 AgentScope Web UI。README 给出安装 service extra、配置现有在线模型环境变量、启动和访问步骤。

## 测试与验收

后端自动化测试覆盖：

- `/` 和静态资源可访问；
- 健康检查仍可用且不泄露密钥；
- 普通问答返回真实 `answer` 且无 `report_url`；
- 同一 `session_id` 复用 Agent，不同会话隔离；
- 知识、天气和经营分析路由字段来自 Supervisor 的实际状态；
- 经营分析 metadata 正确转换为报告 URL、run ID 和审核状态；
- 空问题、非法会话 ID 和内部异常返回稳定错误；
- 现有 CLI、Supervisor、经营分析和 Service 测试保持通过。

页面验收覆盖：

1. 启动服务后访问根地址可以看到与参考图一致的三栏工作台；
2. 输入普通问题后，页面显示用户消息和智能体回复，报告区保持空状态；
3. 输入知识或天气问题后，页面展示回复并点亮实际能力节点；
4. 输入经营分析问题后，页面最终显示智能体回复、完整分析链路与 HTML 报告；
5. 请求失败后能看到原因并直接重试；
6. 桌面和窄屏布局均可用，键盘可以完成输入和发送。

## 完成标准

实现完成时，浏览器问答与命令行问答调用同一个 Supervisor 行为；页面能够可靠展示最终回复，并只在真实生成报告时展示报告。已有智能体功能代码没有因为 Web UI 而被重写或复制，现有回归测试和新增 Web 链路测试均通过。
