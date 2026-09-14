# AgentScope MCP 运行与配置中心设计

## 目标

把现有的 MCP 静态目录改造成真实反映 AgentScope 运行架构的控制中心。页面必须回答四个问题：项目配置了哪些 MCP Server、连接是否可用、发现了哪些工具、这些工具被授权给哪些 Agent。

新增的自定义 MCP 不再只写入 YAML。Agent 会话创建时，系统按照显式授权关系连接已启用的 MCP Server，并把发现的工具注入对应 AgentScope `Toolkit`。

## 范围

本次包含：

- 展示 Supervisor、三个业务 Worker、其 Toolkit 与 MCP Server 的真实关系；
- 修正内置 Business MCP 的 scope 标识和启用状态；
- 新增 stdio、streamable HTTP 和 SSE 自定义 MCP 配置；
- 配置 Supervisor、FinanceSalesAgent、CustomerProductAgent、DeliveryAgent 授权；
- 保存前连接探测、工具发现、超时和安全错误返回；
- 自定义 MCP 启停、重新探测和删除；
- 新 Agent 会话按配置加载 MCP，现存会话明确标记为等待重建；
- 注册表、探测器、Agent 注入、HTTP API 与页面测试。

本次不包含：

- 在请求执行中热替换现有 Agent 的 Toolkit；
- 向 ExternalResearchAgent 注入任意 MCP；
- OAuth 登录流程、远程密钥托管或多人权限管理；
- 把 MCP 工具开放为绕过 Agent 的人工直接执行面板。

## 方案选择

采用“显式 Agent 授权”方案。每个自定义 MCP 保存 `targets`，只允许来自固定 Agent 枚举的值。相比只注入 Supervisor，它能支持专业 Worker；相比注入所有 Agent，它避免无关工具污染 ReAct 上下文和扩大权限面。

## 架构

```text
MCP 控制中心
    │  配置 / 探测 / 状态
    ▼
MCP Registry ─── MCP Probe
    │                └── AgentScope MCPClient → list_tools
    │
    └── Agent session factory
          ├── Supervisor Toolkit
          ├── FinanceSalesAgent Toolkit
          ├── CustomerProductAgent Toolkit
          └── DeliveryAgent Toolkit
```

注册表只负责经过验证的持久化配置。探测器负责构造与运行时相同类型的 AgentScope `MCPClient`、建立连接、发现工具并可靠关闭。运行时加载器读取启用配置，按 `targets` 创建独立连接并把工具加入对应 Toolkit。

同一个有状态 MCP Client 不跨 Agent 共享，避免连接生命周期和并发状态互相干扰。

## 数据模型

每个自定义服务器保存：

- `name`：稳定、安全字符组成的唯一标识；
- `display_name`、`description`：界面文本；
- `transport`：`stdio`、`streamable_http` 或 `sse`；
- `connection`：规范化的命令或 URL；
- `targets`：允许的 Agent 名称列表；
- `enabled`：是否在新会话加载；
- `tools`：最近一次成功探测得到的工具名与描述；
- `last_probe`：探测时间、结果、耗时和安全错误摘要；
- `api_key_env`：可选的环境变量名，只保存名称，不保存密钥值。

内置服务器不写入 YAML。其定义直接引用 `WorkerName` 和 MCP 合同，避免页面模型与运行时 scope 漂移。

YAML 写入采用临时文件加原子替换。解析失败时返回明确错误，禁止把损坏配置当成空列表覆盖。

## 运行时行为

Business MCP 继续由经营分析链路按 Worker 创建，并受 `BIZINSIGHT_ENABLE_BUSINESS_MCP` 控制。Weather MCP 继续由 Supervisor 在天气意图期间按需连接。页面将二者标记为“按需连接”，不会伪装为常驻在线。

自定义 MCP 在新的 Web Agent 会话创建时加载。配置变更后，API 返回 `requires_new_session: true`；页面提示用户新建会话，不声称当前会话已经热更新。

单个自定义 MCP 连接失败只降低该项能力，不阻止 Agent 创建；失败会产生安全状态，但不会记录连接中的密钥或完整异常堆栈。

## HTTP 接口

- `GET /bizinsight/mcp/servers`：返回内置与自定义 MCP、配置状态及最近探测信息；
- `POST /bizinsight/mcp/probe`：校验临时配置并执行一次连接和工具发现，不持久化；
- `POST /bizinsight/mcp/servers`：要求探测成功后保存；
- `PUT /bizinsight/mcp/servers/{name}`：修改启用状态或授权目标；
- `POST /bizinsight/mcp/servers/{name}/probe`：重新探测并更新工具快照；
- `DELETE /bizinsight/mcp/servers/{name}`：删除自定义配置。

请求使用 Pydantic 模型严格校验长度、类型、transport、URL、命令和 Agent 枚举。接口只返回可展示的中文错误，不泄露绝对路径、环境变量值或堆栈。

## 页面设计

页面沿用现有 BizInsight 蓝灰视觉体系。核心识别元素是“AgentScope 接线图”：Agent、Toolkit、MCP 和 Tool 以结构关系呈现，而不是普通服务器卡片列表。

页面由三部分组成：

1. 顶部运行摘要，显示已配置服务器、探测正常服务器、可用工具和待重建会话数量；
2. AgentScope 接线图，按 Agent 展示已授权 MCP，并区分内置按需连接与自定义会话级加载；
3. MCP 详情列表，提供探测、启停、授权调整和删除操作。

新增表单根据 transport 切换字段说明，并在保存前显示探测出的工具及目标 Agent。所有外部文本使用 DOM `textContent` 渲染；状态同时使用文字、图标和颜色。窄屏下接线图改为纵向关系卡。键盘焦点清晰，并尊重 reduced-motion。

## 错误与安全

- 探测设置短连接超时和工具发现超时，并保证关闭子进程或 HTTP 会话；
- stdio 配置拆分为可执行命令与参数，不通过 shell 执行；
- HTTP 只接受 `http` 或 `https` URL；
- 前端不使用可控字符串拼接 `innerHTML`；
- 探测或切换失败时恢复控件原状态；
- 内置 MCP 不可删除或人工伪造在线状态；
- API Key 仅通过命名环境变量注入，页面永不返回其值。

## 测试与验收

自动测试覆盖：

- 内置 scope 与 `MCP_SCOPES` 完全一致；
- YAML 校验、原子写入、损坏文件保护和重复名称；
- 三种 transport 的配置构造；
- 探测成功、超时、连接失败和工具发现；
- 自定义工具只进入获授权 Agent 的 Toolkit；
- 单服务器失败不会阻断 Agent 创建；
- CRUD、重新探测、严格布尔值与错误脱敏；
- MCP 页面静态结构、安全渲染和失败回滚；
- 现有 Business MCP、Weather MCP、Supervisor 与 Web 测试继续通过。

完成标准：页面展示的每个“可用”状态都有真实后端依据；新增且启用的自定义 MCP 会在新 Agent 会话进入指定 Toolkit；未授权 Agent 无法看到其工具；页面不存在已知的持久化 XSS 路径。
