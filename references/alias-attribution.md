# Alias reference and attribution

## Pinned source

| Item | Value |
|---|---|
| Upstream repository | `https://github.com/agentscope-ai/agentscope-samples.git` |
| Local read-only reference | `G:\Agent\AgentScope\agentscope-samples\alias` |
| Pinned commit | `c7f3174cbbd32a96c796571d0fe930ac80ddd523` |
| Commit subject | `Add DeepFinance sample (#124)` |
| Upstream license | Apache License 2.0 |

The commit above is the reproducible reference baseline for compatibility review and selective migration. A moving branch name such as `main` is not used as evidence of the reviewed source version.

## Completed selective migration

No Alias source code was copied into BizInsight Agent at project initialization. Task 2 completed the compatibility audit; detailed evidence is recorded in `docs/alias-compatibility-audit.md`.

| Alias area | Audited treatment |
|---|---|
| `src/alias/agent/agents/_meta_planner.py` | Rewrite as bounded business planning and Worker dispatch |
| `src/alias/agent/agents/_react_worker.py` | Rewrite around AgentScope 2.0.7 `Agent` and `ReActConfig` |
| `src/alias/agent/agents/_data_science_agent.py` | Delete the general agent; rewrite selected deterministic analysis ideas |
| `src/alias/agent/agents/_deep_research_agent_v2.py` | Delete the generic research tree; rewrite a narrow evidence flow |
| Alias data-source utilities | Rewrite behind `BusinessDataProvider` and the scoped Business Data MCP server |
| `src/alias/agent/tools/` | Migrate organization only; replace implementations with AgentScope `Toolkit`/`FunctionTool` and `MCPClient` tools |
| `_deep_research_agent_v2.py` source aggregation | Rebuild as bounded BM25 + AgentScope KnowledgeBase/Qdrant retrieval with traceable evidence; no research tree copied |
| Runtime runner | Deleted Alias runner; integrated the BizInsight workflow with AgentScope 2.0.7 `create_app`, CLI and custom events |

## Explicitly excluded Alias scope

- Alias frontend and its multiple application modes
- Finance, Browser, and QA agents
- Memory service and long-term user profiling
- Full user, database, Alembic, Redis, Celery, and authentication backends
- Dependencies required only by those excluded components

## Original BizInsight scope

Unless a file contains a more specific attribution notice, the following are original BizInsight project work: the synthetic company and datasets, business schemas, deterministic metrics, read-only business data provider, scoped MCP contracts/server, BM25/RRF adapter, domain Agent prompts and permissions, evidence contracts, Reviewer workflow, report templates, evaluation cases, and delivery documentation.

## License handling

The project distributes an Apache License 2.0 `LICENSE` file and a `NOTICE` that preserves the upstream attribution. Any future file substantially adapted from Alias must retain relevant notices and state that it was modified. This document must be updated with the exact source path and treatment when selective migration occurs.
