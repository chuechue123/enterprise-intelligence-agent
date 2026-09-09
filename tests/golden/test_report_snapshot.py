"""Stable snapshot of the eleven-section report contract."""

from bizinsight.tools.reports import REPORT_SECTIONS


def test_report_section_snapshot():
    expected = "\n".join(
        f"{index}. {name}" for index, name in enumerate(REPORT_SECTIONS, 1)
    )
    assert (
        expected
        == """1. 执行摘要
2. 核心指标概览
3. 主要异常排名
4. 财务与销售分析
5. 客户、产品与服务分析
6. 项目交付分析
7. 外部行业背景
8. 根因假设与置信度
9. 行动建议
10. 数据限制与待验证问题
11. 证据索引"""
    )
