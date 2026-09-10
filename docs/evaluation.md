# 自动评测

评测集包含 15 个问题：5 个综合问题、5 个财务销售/客户产品专项问题、2 个交付问题、2 个外部研究问题和 1 个缺失时间范围问题。

| 维度 | 权重 | 判断方式 |
|---|---:|---|
| 指标准确性 | 35 | 比较结构化 Q2 `MetricValue` 与固定真值 |
| 异常覆盖率 | 25 | 检查目标异常是否进入通过审查的 Finding |
| 证据完整性 | 20 | 关键 Finding 有证据且指标引用全部可解析 |
| 稳健性 | 10 | 工作流错误隔离并成功生成报告 |
| 报告质量 | 10 | 十一节、证据跳转、行动建议和本地图表 |

2026-09-09 离线基线运行结果：15/15 用例通过，平均 99.93，最低 99.5（外部专项没有内部指标图表，因此报告质量扣 5 分，对总分影响 0.5）。通过门槛为 80，黄金综合案例识别 5/5 核心异常。

该分数证明的是确定性离线路径、数据契约和治理链路的可靠性，不等同于真实企业效果或模型泛化能力。在线模式应单独记录模型名、token、费用、延迟和随机性，多次运行后再与离线基线比较。
# BizInsight 1.0 评测

离线经营基线覆盖 15 个问题，固定种子结果为 99.93/100。离线 RAG 的 5 个可解释查询达到 Hit@3=1.0、MRR=1.0。完整回归当前为 120 项通过、1 项真实在线测试默认跳过（最终数字以最新验收输出为准）。

```powershell
python evaluations/run_evaluation.py --mode offline
python evaluations/run_rag_evaluation.py --mode offline
```

在线评测与离线评测分开。配置重新生成的本地 Key 后，先显式构建向量索引，再运行 5 次稳定性测试；门槛是结构化成功率不少于 80%。结果保存原始 telemetry，失败不会被吞掉或改写成通过。

```powershell
python scripts/build_knowledge_base.py --online-embedding
python evaluations/run_rag_evaluation.py --mode hybrid
python evaluations/run_online_stability.py --runs 5
```
