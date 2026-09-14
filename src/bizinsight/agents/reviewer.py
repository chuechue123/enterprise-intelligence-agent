"""Evidence-first review with deterministic guardrails and AgentScope wiring."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.observability import aggregate_agent_usage
from bizinsight.schemas import (
    EvidenceType,
    Finding,
    ReviewResult,
    ReviewStatus,
    RevisionRequest,
    WorkerName,
)
from bizinsight.tools.metrics import calculate_metric

CAUSAL_WORDS = ("直接导致", "完全由", "证明", "唯一原因", "造成")


class EvidenceReviewerAgent:
    """Review facts before interpretation and allow at most one targeted repair."""

    def __init__(
        self,
        provider: BusinessDataProvider,
        model: ChatModelBase | None = None,
    ) -> None:
        self.provider = provider
        self.last_usage = None
        self.agent: Agent | None = None
        if model is not None:
            prompt = (
                Path(__file__).resolve().parents[1] / "prompts" / "reviewer.md"
            ).read_text(encoding="utf-8")
            self.agent = Agent(
                name="EvidenceReviewerAgent",
                system_prompt=prompt,
                model=model,
                react_config=ReActConfig(max_iters=3, structured_output_grace_iters=2),
                injection_config=InjectionConfig(inject_runtime_state=False),
            )

    def review(
        self,
        findings: Sequence[Finding],
        owners: Mapping[str, WorkerName] | None = None,
        *,
        allow_revision: bool = True,
    ) -> ReviewResult:
        """Apply reproducibility, evidence and causality checks."""

        owners = owners or {}
        accepted: list[str] = []
        rejected: list[str] = []
        revisions: list[RevisionRequest] = []
        conflicts: list[str] = []
        limitations: list[str] = []

        values: dict[tuple[str, str], list[tuple[str, Decimal]]] = defaultdict(list)
        for finding in findings:
            for metric in finding.metrics:
                values[(metric.metric_name, metric.period)].append(
                    (finding.finding_id, metric.value),
                )
        conflicted = {
            finding_id
            for (name, period), entries in values.items()
            if len({value for _, value in entries}) > 1
            for finding_id, _ in entries
            if not conflicts.append(f"{name} 在 {period} 出现互相冲突的数值")
        }

        for index, finding in enumerate(findings, start=1):
            issues: list[str] = []
            changes: list[str] = []
            if not finding.evidence:
                issues.append("结论没有可追溯证据")
                changes.append("补充数据库、文档或计算证据后再提交")
            if finding.finding_id in conflicted:
                issues.append("同一指标和期间存在数值冲突")
                changes.append("统一指标口径并重新计算冲突数值")

            for metric in finding.metrics:
                try:
                    expected = calculate_metric(
                        self.provider,
                        metric.metric_name,
                        metric.period,
                    ).metric.value
                except (KeyError, ValueError):
                    issues.append(
                        f"指标 {metric.metric_name}（{metric.period}）"
                        "无法按指标字典复算"
                    )
                    changes.append(
                        f"从 metrics 中删除未注册指标 {metric.metric_name}；"
                        "只保留系统提示列出的授权指标"
                    )
                    continue
                if metric.value != expected:
                    issues.append(
                        f"{metric.metric_name} {metric.period} 数值不可复现："
                        f"提交 {metric.value}，复算 {expected}",
                    )
                    changes.append(
                        f"使用注册指标口径重新计算 {metric.metric_name}",
                    )

            internal_evidence = any(
                item.evidence_type
                in {
                    EvidenceType.DATABASE,
                    EvidenceType.CALCULATION,
                }
                or (
                    item.evidence_type is EvidenceType.DOCUMENT
                    and "external" not in item.source.lower()
                    and "external" not in item.evidence_id.lower()
                )
                for item in finding.evidence
            )
            causal_text = finding.causal_assessment or ""
            if (
                causal_text
                and any(word in causal_text for word in CAUSAL_WORDS)
                and not internal_evidence
            ):
                issues.append("外部证据不能单独证明公司内部因果关系")
                changes.append("将内部因果改为待验证假设，或补充内部数据证据")

            if not issues:
                accepted.append(finding.finding_id)
                continue

            owner = owners.get(finding.finding_id)
            if allow_revision and owner is not None:
                suffix = re.sub(r"[^A-Za-z0-9_-]", "-", finding.finding_id[8:])
                revisions.append(
                    RevisionRequest(
                        request_id=f"REVISION-{index}-{suffix}",
                        finding_id=finding.finding_id,
                        target_agent=owner,
                        reason="；".join(issues),
                        required_changes=list(dict.fromkeys(changes)),
                    ),
                )
            else:
                rejected.append(finding.finding_id)
                limitations.extend(issues)

        if accepted and (rejected or revisions):
            status = ReviewStatus.PARTIAL
        elif revisions:
            status = ReviewStatus.REVISION_REQUIRED
        elif rejected:
            status = ReviewStatus.REJECTED
        else:
            status = ReviewStatus.ACCEPTED
        return ReviewResult(
            status=status,
            accepted_finding_ids=accepted,
            rejected_finding_ids=rejected,
            revision_requests=revisions,
            conflicts=list(dict.fromkeys(conflicts)),
            data_limitations=list(dict.fromkeys(limitations)),
            reviewer_notes="已完成指标复算、证据完整性、冲突与因果边界审查。",
        )

    async def review_with_semantics(
        self,
        findings: Sequence[Finding],
        owners: Mapping[str, WorkerName] | None = None,
        *,
        allow_revision: bool = True,
    ) -> ReviewResult:
        """Run deterministic guardrails first, then optional AgentScope judgment."""
        hard = self.review(findings, owners, allow_revision=allow_revision)
        if self.agent is None:
            return hard
        # 硬审查全部拒绝时语义审查没有意义；终审时硬审查未通过也直接保留。
        if (
            allow_revision
            and hard.status is ReviewStatus.REJECTED
            or not allow_revision
            and hard.status is not ReviewStatus.ACCEPTED
        ):
            return hard
        round_hint = (
            "当前是首轮审查：发现任何事实、解释与证据不一致的问题，"
            "都通过 revision_requests 提出具体返工要求，不要直接拒绝。"
            if allow_revision
            else "当前是终审，不再有返工机会，请直接给出结论。"
        )
        response = await self.agent.reply(
            UserMsg(
                name="BizInsightWorkflow",
                content=(
                    "请只审查解释是否谨慎、结论是否与证据一致；"
                    "不得改写指标。返回 ReviewResult。"
                    f"{round_hint}\n"
                    + "\n".join(item.model_dump_json() for item in findings)
                ),
            ),
            structured_schema=ReviewResult,
        )
        self.last_usage = response.usage or aggregate_agent_usage(self.agent)
        if response.structured_output is None:
            return hard.model_copy(
                update={
                    "reviewer_notes": hard.reviewer_notes
                    + " 语义审查无结构化输出，保留硬规则结果。"
                }
            )
        semantic = ReviewResult.model_validate(response.structured_output)
        known = {item.finding_id for item in findings}
        mentioned = (
            set(semantic.accepted_finding_ids)
            | set(semantic.rejected_finding_ids)
            | {item.finding_id for item in semantic.revision_requests}
        )
        if not mentioned <= known:
            return hard.model_copy(
                update={
                    "reviewer_notes": hard.reviewer_notes
                    + " 语义审查引用未知 Finding，已忽略。"
                }
            )
        owner_map = owners or {}
        semantic_requests = [
            request.model_copy(
                update={"target_agent": owner_map[request.finding_id]}
            )
            for request in semantic.revision_requests
            if request.finding_id in owner_map
        ]
        if not allow_revision:
            rejected = list(
                dict.fromkeys(
                    semantic.rejected_finding_ids
                    + [item.finding_id for item in semantic_requests]
                )
            )
            accepted = [
                item for item in semantic.accepted_finding_ids if item not in rejected
            ]
            status = ReviewStatus.PARTIAL if accepted else ReviewStatus.REJECTED
            return semantic.model_copy(
                update={
                    "status": status,
                    "accepted_finding_ids": accepted,
                    "rejected_finding_ids": rejected,
                    "revision_requests": [],
                    "data_limitations": semantic.data_limitations
                    + ["单轮返工结束后仍存在语义审查问题。"],
                }
            )

        # 首轮：语义审查拒绝的 Finding 同样获得一次修订机会，与硬规则
        # 修订请求按 finding 合并，避免同一 Finding 被重复返工覆盖。
        converted: list[RevisionRequest] = []
        kept_rejected: list[str] = []
        for finding_id in semantic.rejected_finding_ids:
            if finding_id not in owner_map:
                kept_rejected.append(finding_id)
                continue
            suffix = re.sub(r"[^A-Za-z0-9_-]", "-", finding_id[8:])
            converted.append(
                RevisionRequest(
                    request_id=f"REVISION-SEM-{suffix}",
                    finding_id=finding_id,
                    target_agent=owner_map[finding_id],
                    reason="语义审查认为事实、业务解释或因果表述与证据不一致",
                    required_changes=[
                        "收敛或删除无证据支撑的解释与归因表述，"
                        "与证据不一致的内容改写为待验证假设并写入 limitations",
                    ],
                )
            )
        merged: dict[str, RevisionRequest] = {}
        for request in [*hard.revision_requests, *semantic_requests, *converted]:
            existing = merged.get(request.finding_id)
            if existing is None:
                merged[request.finding_id] = request
            else:
                merged[request.finding_id] = existing.model_copy(
                    update={
                        "reason": f"{existing.reason}；{request.reason}",
                        "required_changes": list(
                            dict.fromkeys(
                                existing.required_changes + request.required_changes
                            )
                        ),
                    }
                )
        requests = list(merged.values())
        problem_ids = {
            item.finding_id for item in requests
        } | set(kept_rejected)
        accepted = [
            item for item in hard.accepted_finding_ids if item not in problem_ids
        ]
        rejected = list(
            dict.fromkeys(hard.rejected_finding_ids + kept_rejected)
        )
        if not (requests or rejected):
            status = ReviewStatus.ACCEPTED
        elif requests and not (accepted or rejected):
            status = ReviewStatus.REVISION_REQUIRED
        elif rejected and not accepted:
            status = ReviewStatus.REJECTED
        else:
            status = ReviewStatus.PARTIAL
        return ReviewResult(
            status=status,
            accepted_finding_ids=accepted,
            rejected_finding_ids=rejected,
            revision_requests=requests,
            conflicts=list(dict.fromkeys(hard.conflicts + semantic.conflicts)),
            data_limitations=list(
                dict.fromkeys(hard.data_limitations + semantic.data_limitations)
            ),
            reviewer_notes=hard.reviewer_notes + semantic.reviewer_notes,
        )
