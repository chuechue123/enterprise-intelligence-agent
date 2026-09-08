# BizInsight Agent

BizInsight Agent 是一个面向 ToB 科技企业的经营异常诊断与决策协同智能体。项目基于 AgentScope 2.0，使用 Leader–Worker 多智能体协作、确定性指标计算和证据审查，将销售、合同、订阅、产品使用、项目交付、客服与回款数据整理为可追溯的经营分析报告。

## 项目状态

当前处于 MVP 实施阶段。实施以固定版本的 AgentScope Samples / Alias 为参考，但 BizInsight Agent 是独立仓库，不直接继承 Alias 的完整应用、前端、用户系统或记忆服务。

## 数据与使用边界

- 项目中的“云衡数科有限公司”及其业务数据完全虚构并由程序合成。
- 项目不使用浩云科技股份有限公司的内部数据。
- 项目未在浩云科技或其他真实企业的生产环境部署。
- 外部行业资料仅用于背景说明或假设佐证，不能直接证明虚构企业的内部经营原因。

## 设计文档

- [设计规格](docs/2026-09-08-bizinsight-agent-design.md)
- [实施计划](docs/2026-09-08-bizinsight-agent-implementation-plan.md)
- [Alias 来源与归因](references/alias-attribution.md)

## 计划技术栈

- Python 3.11～3.13
- AgentScope 2.0.7
- Pydantic、SQLite、Pandas、Matplotlib、Jinja2
- 阿里云百炼 Qwen（默认模型提供商）
- Tavily（可离线降级的外部行业检索）

## 开发

任务 2 将补充最小 AgentScope 冒烟测试和本地安装步骤。在任何情况下都不要把真实密钥提交到仓库；本地配置从 `.env` 或环境变量读取。

## 许可证

本项目采用 Apache License 2.0。参考来源和计划迁移范围见 [references/alias-attribution.md](references/alias-attribution.md)。
