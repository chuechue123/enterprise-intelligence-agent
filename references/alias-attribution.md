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

## Planned selective migration

No Alias source code has been copied into BizInsight Agent at project initialization. The following areas are candidates for review; the task 2 compatibility audit will record whether each area is migrated, rewritten, or removed.

| Alias area | BizInsight intention |
|---|---|
| `src/alias/agent/agents/_meta_planner.py` | Adapt planning responsibilities into business-task planning and Worker dispatch |
| `src/alias/agent/agents/_react_worker.py` | Reuse the ReAct Worker design ideas in a restricted business Worker base |
| `src/alias/agent/agents/_data_science_agent.py` | Extract data-source understanding and deterministic tool-use patterns |
| `src/alias/agent/agents/_deep_research_agent_v2.py` | Extract retrieval, evidence synthesis, and citation patterns |
| Alias data-source utilities | Redesign behind `BusinessDataProvider` |
| `src/alias/agent/tools/` | Keep the Toolkit organization idea while replacing tools with domain-specific tools |
| Runtime runner | Reintegrate against AgentScope 2.0.7 after compatibility review |

## Explicitly excluded Alias scope

- Alias frontend and its multiple application modes
- Finance, Browser, and QA agents
- Memory service and long-term user profiling
- Full user, database, Alembic, Redis, Celery, and authentication backends
- Dependencies required only by those excluded components

## Original BizInsight scope

Unless a file contains a more specific attribution notice, the following are original BizInsight project work: the synthetic company and datasets, business schemas, deterministic metrics, read-only business data provider, domain Agent prompts and permissions, evidence contracts, Reviewer workflow, report templates, evaluation cases, and delivery documentation.

## License handling

The project distributes an Apache License 2.0 `LICENSE` file and a `NOTICE` that preserves the upstream attribution. Any future file substantially adapted from Alias must retain relevant notices and state that it was modified. This document must be updated with the exact source path and treatment when selective migration occurs.
