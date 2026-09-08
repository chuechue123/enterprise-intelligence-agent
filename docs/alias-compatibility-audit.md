# Alias compatibility audit for BizInsight Agent

- Audit date: 2026-09-08
- Alias repository: `https://github.com/agentscope-ai/agentscope-samples.git`
- Alias path: `alias/`
- Pinned Alias commit: `c7f3174cbbd32a96c796571d0fe930ac80ddd523`
- Alias declared AgentScope version: `agentscope[full]==1.0.11`
- BizInsight target version: `agentscope==2.0.7`
- Audit outcome: preserve responsibilities and selected patterns; do not copy the Alias runtime architecture

## 1. Method

The audit inspected the pinned source files, their direct imports, adjacent helper modules, and dependency declarations. Compatibility probes then imported the corresponding public symbols from an isolated Python 3.13 environment containing AgentScope 2.0.7. The minimal BizInsight smoke test uses only the installed 2.0.7 package and never adds Alias to `PYTHONPATH`.

The audit distinguishes three decisions:

- **Migrate**: a small implementation can be adapted with the same public API.
- **Rewrite**: preserve the responsibility or pattern but implement it against 2.0.7 contracts.
- **Delete**: the capability is outside the BizInsight MVP or replaced by a narrower component.

## 2. Executive conclusion

Alias cannot be imported unchanged under AgentScope 2.0.7. Its base class imports `ReActAgent`, while 2.0.7 exports a unified `Agent`. Alias also depends on the removed `agentscope.memory` module, renamed message blocks, former structured-output calling conventions, former MCP client exports, private framework utilities, and a custom runtime/sandbox/service stack.

BizInsight will therefore use AgentScope 2.0.7 as a clean dependency. It will retain Alias ideas such as task decomposition, bounded ReAct execution, specialized toolkits, data-source descriptions, and evidence-oriented research, but will express them through BizInsight-owned schemas and orchestration.

## 3. Framework API boundary

| Concern | Pinned Alias / AgentScope 1.0.11 | AgentScope 2.0.7 | Decision |
|---|---|---|---|
| Agent class | `ReActAgent` and `AliasAgentBase(ReActAgent)` | unified `agentscope.agent.Agent` | Rewrite |
| Constructor | separate `sys_prompt`, formatter, memory and `max_iters` | `system_prompt`, model-owned formatter, `AgentState`, `ReActConfig` | Rewrite |
| ReAct loop | subclasses override private `_reasoning` and `_acting` | `Agent` owns reply/reasoning/action lifecycle | Use public `Agent`; avoid private overrides |
| Context storage | `agentscope.memory.MemoryBase` and long-term memory | no `agentscope.memory` package; state/middleware-oriented context | Rewrite; long-term memory excluded from MVP |
| Tool-call block | `ToolUseBlock` / `tool_use` | `ToolCallBlock` / `tool_call` | Rewrite |
| Message construction | positional `Msg(name, content, role)` is common | `Msg` model is keyword-oriented; `UserMsg` is the simple public helper | Rewrite |
| Structured agent reply | partial application with `structured_model=...` | `Agent.reply(..., structured_schema=Model)` and `Msg.structured_output` | Rewrite |
| Structured model call | several Alias paths call model with `structured_model` | model exposes `generate_structured_output`; Agent-level schema is preferred | Rewrite |
| Tool API | `Toolkit` and `ToolResponse` exist | `Toolkit`, `ToolBase`, `ToolChunk`, and `ToolResponse` exist, but internals differ | Migrate organization only; use public registration/call APIs |
| Hooks | `register_instance_hook` around private lifecycle methods | middleware and Agent lifecycle configuration | Rewrite as middleware or orchestration |
| Tracing | `agentscope.tracing.trace_reply` | module not exported | Delete old decorator; use 2.0.7 events/tracing later |
| MCP clients | `StdIOStatefulClient`, `HttpStatelessClient`, base client classes | those names are not exported by `agentscope.mcp` | Rewrite adapter after selecting 2.0.7 public API |
| Runtime | Alias-specific runner, stream adapter and service state | new Agent/service/state interfaces | Delete Alias runner; integrate service in task 12 |

## 4. Module decisions

### 4.1 `_meta_planner.py` — rewrite

The 818-line Alias planner mixes mode selection, dynamic Worker construction, tool-group mutation, filesystem setup, clarification, state persistence, browser/QA/data-science switching, and long-term memory. BizInsight needs only a bounded business planner: normalize the question, create at most four typed analysis tasks, select domain Workers, execute dependencies, and collect findings.

Reusable ideas are the planning notebook concept, explicit Worker descriptions, and separation between planning and execution. Browser, QA, arbitrary file tooling, mode switching, Alias session services, and memory hooks are deleted. The replacement will use `AnalysisPlan` and `AnalysisTask` schemas from task 3 and BizInsight orchestration from task 9.

### 4.2 `_react_worker.py` — rewrite

The Alias Worker is small, but it subclasses the incompatible `AliasAgentBase`, imports the removed memory abstraction, binds the former `structured_model` argument with `partial`, and manipulates former iteration attributes. BizInsight will construct or wrap the 2.0.7 `Agent`, pass `ReActConfig`, register only domain-approved tools, and validate the final `Finding` contract through `structured_schema`.

The reusable pattern is a common Worker factory/base that standardizes prompts, tool permissions, output validation, and one bounded correction attempt.

### 4.3 `_data_science_agent.py` — delete general agent, rewrite selected ideas

The 622-line implementation is a general data-science workflow tied to IPython execution, arbitrary file generation, scenario prompts, report generation, state hooks, a sandbox, and the Alias data-source manager. Those capabilities exceed the BizInsight MVP and weaken the deterministic-calculation boundary.

BizInsight retains the ideas of schema discovery, task-specific dataset context, deterministic computation before narrative synthesis, and structured results. They become `BusinessDataProvider`, safe read-only SQL, named metric functions, and domain Workers in tasks 4, 6, and 7. Arbitrary notebook/code execution is deleted.

### 4.4 `_deep_research_agent_v2.py` — delete general tree, rewrite evidence flow

The 968-line implementation manages a generic research tree, dynamically creates research Workers, generates multiple report formats, mutates plans, accesses a private timestamp helper, and assumes former structured-output and tool APIs. BizInsight does not need a second general planner inside external research.

The retained ideas are query refinement, source capture, bounded evidence gathering, and explicit synthesis. The replacement ExternalResearchAgent will call a narrow Tavily adapter, emit typed `WEB-*` evidence, prohibit external sources from proving internal causality, and fall back to local documents.

### 4.5 `data_source/` — rewrite

Alias supports files, images, relational databases and MCP endpoints; performs LLM-based profiling; and depends on SQLAlchemy, AgentScope Runtime sandboxes, Alias tool hooks and data skills. BizInsight has a known synthetic schema and requires stronger read-only guarantees.

The replacement `BusinessDataProvider` will expose `list_datasets`, `describe_schema`, `execute_readonly_query`, `get_metric_definition`, and `fetch_evidence_rows`. SQLite and deterministic metadata replace generic source detection, LLM profiling, image support and arbitrary file preparation.

### 4.6 `tools/` — migrate organization, rewrite implementations

Alias's centralized Toolkit organization and grouping by Worker responsibility are useful. Its concrete toolkit wraps sandbox tools, reaches into mutable toolkit internals, manages former MCP client types, adds broad filesystem/browser tools, and applies Alias-specific post-hooks.

BizInsight will use the public 2.0.7 Toolkit surface with explicit allowlists. Concrete tools will be read-only SQL, metrics, internal retrieval, external search, chart rendering, and controlled report output. No Alias sandbox or general filesystem tool is migrated into the MVP.

### 4.7 Runtime runner and excluded application layers — delete

Alias's runtime compatibility runner, frontend, authentication, users, Redis/Celery services, Alembic database, memory service, Browser Agent, Finance Agent, and QA Agent are outside scope. BizInsight will later expose its own workflow through the AgentScope 2.0.7 service interface and existing Web UI, with a CLI fallback.

## 5. Dependency boundary

Alias declares a broad application stack including AgentScope 1.0.11, AgentScope Runtime, Docker, Playwright, Redis, Celery, FastAPI, SQLModel, PostgreSQL drivers, Elasticsearch, Alembic and authentication packages. Importing Alias would make these transitive architectural commitments part of BizInsight.

BizInsight pins AgentScope 2.0.7 and keeps only domain runtime dependencies. Tavily is an optional research extra. Service dependencies and sandbox enhancements will be added only when their implementation tasks require them. This keeps offline unit and integration tests independent of external credentials.

## 6. Minimal 2.0.7 smoke design

`src/bizinsight/config.py` loads `DASHSCOPE_API_KEY` and `BIZINSIGHT_MODEL_NAME`. Neither has a secret or model-name default. Online construction fails with a message naming every missing variable.

`src/bizinsight/app.py` provides three seams:

1. `build_dashscope_model` validates settings and creates a `DashScopeChatModel`.
2. `build_smoke_agent` accepts any `ChatModelBase`, enabling deterministic tests.
3. `run_structured_smoke` calls `Agent.reply` with a Pydantic schema and validates `Msg.structured_output` again at the application boundary.

Default tests use a local mock model that returns the 2.0.7 built-in `GenerateStructuredOutput` tool call. The real DashScope test is marked `online`, skipped without both environment variables, and excluded by the default pytest marker expression.

## 7. Verification commands

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest

# Explicit opt-in; consumes a real model request.
.\.venv\Scripts\python.exe -m pytest -m online tests\integration\test_agent_smoke.py
```

The default test suite must pass without importing Alias and without reading a real API key. The online test is not part of default CI.

## 8. Risks carried forward

- Tool registration and permission isolation must be tested against the public 2.0.7 Toolkit API in task 6/7.
- Agent structured output can require correction rounds with real models; task 7 will enforce one application-level correction attempt.
- Agent Service APIs are intentionally deferred to task 12 so the domain workflow does not depend prematurely on deployment concerns.
- The fixed Alias commit remains the audit baseline even if the local reference repository later moves; audit reproduction must check out the pinned SHA first.
