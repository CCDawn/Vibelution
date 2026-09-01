"""Stage-specific structured writeback contracts for source-collection Agents."""

from __future__ import annotations


def _finding_writeback_budget_line() -> str:
    try:
        from .writeback_materialize import (
            finding_resolved_search_envelope,
        )

        envelope = finding_resolved_search_envelope()
    except Exception:  # pragma: no cover - contract lines must never break prompts
        envelope = {
            "totalAcceptedLeadBudget": 8,
            "maxWritebackBatches": 4,
            "maxLeadsPerWriteback": 4,
            "effectiveAcceptedLeadLimit": 8,
        }
    return (
        "- 写回预算：服务端已在任务创建时固化检索预算："
        f"总计最多接受 {envelope['totalAcceptedLeadBudget']} 条去重来源，"
        f"最多 {envelope['maxWritebackBatches']} 个写回批次，每批 `candidateLeads[]` 最多 "
        f"{envelope['maxLeadsPerWriteback']} 条；实际接受上限取小为 "
        f"{envelope['effectiveAcceptedLeadLimit']} 条。重复/复用来源不重复消耗总预算；"
        "达到任一上限后请立即以现有服务端检索回执与 `candidateLeads[]` 写回收口并结束任务。"
    )


def stage_writeback_prompt_lines(stage_id: str) -> list[str]:
    if stage_id == "finding":
        return [
            "- 调用 `source_collection_stage_writeback_tool` 时，结构化结果必须 JSON 序列化到参数 `result_json`；该工具没有 `payload_json` 参数，禁止使用 `payload_json`。",
            "- 本任务只负责资料寻找：新资料只写入 `candidateLeads[]`，无效来源只写入 `invalidSources[]`；不要把检索结果写成 `candidateExtractions[]`、`recordExtractions[]` 或 `candidateDecisions[]`。",
            "- 检索计划必须同时覆盖四类视角：`mechanism`（机制/支持）、`independent_baseline`（独立基线或复现）、`limitation_or_null`（限制、失败或零结果）和 `falsification`（反例或可证伪线索）；不得只检索支持当前设想的资料。",
            "- 每条 `candidateLeads[]` 至少包含 `title`、`locator`（可验证 DOI 或 https URL）、`sourceType`、`summary`、本条资料对应的 `query`，以及上述四类之一的 `perspective`；可额外填写 `doi`、`authors`、`year`、`container`、`relevance`。",
            "- 服务端会从真实检索执行事件生成 canonical searchTrace；你可以在结果中提交查询说明，但 Agent 自报 `result.searchTrace[]` 不作为审计权威，也不能替代真实 provider 调用。",
            "- 至少一条候选资料必须属于 `limitation_or_null` 或 `falsification`，并能作为后续反证候选；如果真实检索后仍未找到，保留完整 `searchTrace[]`、写 `status=needs_review`，不得伪造负面资料或把支持性背景冒充反证。",
            "- `locator` 必须是本条资料的 DOI 或 https URL；不要只写自然语言来源名，也不要把搜索结果的概述当作资料定位符。",
            "- 检索到的可用资料写入 `result.candidateLeads[]`，明确无效、跑题或不可获取的来源写入 `result.invalidSources[]`；自然语言总结不能替代这些结构化写回。",
            "- 滚动写回：每检索到一批可用资料就立即调用一次 `source_collection_stage_writeback_tool` 把这批 `candidateLeads[]`/`invalidSources[]` 写回并累计；禁止等全部候选或 locator 验证完成后再一次性写回。写回随检索持续进行，不是收尾动作；宁可多次小批写回，也不许长时间验证后集中写。",
            _finding_writeback_budget_line(),
            "- 单条来源的 locator 定位验证最多 1 次工具调用；失败即把该条写入 `result.invalidSources[]` 并附原因，立刻继续下一批检索，不得反复重试同一 URL/DOI 或其大小写、编码、URL 形状变体。",
            "- 绝不自行构造或猜测 DOI；需要 DOI 时只允许一次 `GET https://api.crossref.org/works?query.bibliographic=<标题+第一作者>`，返回 404/429 即放弃该条并写 `result.invalidSources[]`，禁止改用变体查询反复重试。",
        ]
    if stage_id == "extraction":
        return [
            "- 资料提炼阶段如果 `candidatePage.total=0`，输入就是原始 DataRecord：请用 `recordExtractions[]` 回写，并绑定完整 `recordId`；已有候选后优先用 `candidateExtractions[]` 绑定完整 `candidateId`，可直接在每项里写 `decision=keep/needs_more_info/exclude`。",
            "- 资料提炼阶段不需要额外提交一份 `candidateDecisions[]`；只有专门做资料审查/质检时才单独回写 `candidateDecisions[]`。",
            "- 资料提炼采用宽松保留：只要有可用内容或有价值线索，就写 `decision=keep` 或 `needs_more_info`，并填写 `valueSummary`、`defects`、`followUpSuggestion`；不要因为缺 DOI/缺全文直接丢弃。",
            "- 资料提炼必须区分来源定位与主张级证据：DOI/URL/论文 ID 只能写入 `sourceRefs[]`；它们只能说明资料在哪里，不能单独证明资料支持某个结论。",
            "- `evidenceRefs[]` 只写页码、PDF 页、段落、章节、引文或受控记录锚点；`claims[]` / `keyFindings[]` / `citations[]` 每项必须包含 `sourceRef`，并至少包含 `page/pageRange/citation/evidenceRef` 之一。",
            "- 要进入正式 `ClaimEvidenceStore` 的主张，`claims[]` 还必须提供来源中可复核的有界原文 `quote`，并且每条 `claims[]`/`keyFindings[]` 项都要自带显式事实字段 `fact`；`claim` 是归纳主张的别名，运行时只认 `fact`，不能用 `claim` 替代。",
            "- 正式 claim 路径的 completed 提炼回写被服务端强制校验：候选/记录有可引用原文块（上下文 `quotableSources[].blocks`）或存储 `summary` 非空时，每条非 `exclude` 条目必须至少带一个逐字 quote 锚——嵌套 `claims[]`/`keyFindings[]` 项含 `quote`，或 `evidenceRefs[]` 项含 `{id, quote}`；`quote` 必须是对应来源原文块/`candidates[].summary` 的逐字子串，从上下文原样复制，禁止改写、拼接或凭记忆重写。",
            "- 上下文 `quotableSources[]` 是唯一的 quote 来源：`quote` 只能从对应 `sourceId` 的 `blocks[].text` 逐字复制（来源优先级 fetched_body>abstract>stored_summary，截断块只引块内文本）；`sourceAccess.access=abstract_only` 的来源只有摘要级原文可引（写 `evidenceStatus=verified_abstract`）；`sourceAccess.access=no_quotable_text` 的来源没有可引用原文——跳过它的 quote 并声明 `evidenceStatus=missing_evidence_anchor`，不要为它产出 claim 或空 `quote`。",
            "- quote 不匹配的一次性修正：`quote` 首次不是原文块逐字子串时，completed 回写不拒绝，任务停靠 `needs_review` 并返回 `quoteAnchorRemediation`（含最近匹配块片段与相似度），按其 `findings[]` 逐条替换为逐字文本后重写；该修正机会只有一次，再次不匹配会被直接拒绝；空 `quote`/缺锚回写始终直接拒绝，不进入修正反馈。",
            "- 引述存储摘要时把条目证据状态写为 `evidenceStatus=verified_abstract`；证据状态字段名是 `evidenceStatus`，不是 `verification_status`（`verification_status` 只属于 Challenge v2 证据卡元数据，其取值不会被当作条目证据状态）；存储 `summary` 为空的来源必须声明 `evidenceStatus=missing_evidence_anchor` 诚实跳过（不物化），不得虚构页码、直接引语或全文结论。",
            "- 正式 Challenge v2 的每个 extraction/finding 必须显式回写 `title`、`source_type`、`source_url`、`retrieved_at`、`fact`、`relation`、`verification_status`。`fact` 必须写在每条嵌套 `claims[]`/`keyFindings[]` 项自己身上，不能只写在 extraction 父项；父项的 `fact` 只对没有任何嵌套 findings 的扁平 extraction 生效。`title`、`source_type`、`source_url`、`retrieved_at`、`relation`、`verification_status` 属于共享元数据，可以放在 extraction 父项，但最终每张 evidence card 必须完整展开。",
            "- `source_type` 必须是 `peer_reviewed_paper/preprint/dataset/standard/official_document/book/other` 之一，`relation` 必须是 `supports/challenges/context/method/boundary` 之一，`verification_status` 必须是 `unverified/metadata_checked/full_text_checked/human_verified` 之一；不要把 `sourceKind` 当作推断依据。",
            "- `source_url` 只能写真实的 `https://` 定位符，`retrieved_at` 必须是带时区的 RFC3339 时间；不得从 DOI、URL、摘要、标题或 `valueSummary` 猜造 `fact`、`relation` 或验证状态。",
            "- 每条 evidence card 必须同时保留 `sourceId` 与 `candidateId`（或 `recordId`）的正式来源联结；`sourceId` 必须等于该 candidate/record ID，不能用 URL 充当来源身份。可选字段为 `doi`、`date`、`limitations`（字符串数组，每项一条限制；不要写成单个字符串）。",
            "- 若正式字段缺失、来源联结不一致或没有真实 citation anchor，必须结构化回写 `needs_review`/`blocked` 及原因；不能用旧版宽松卡片冒充 Challenge v2 证据。",
        ]
    if stage_id == "relations":
        return [
            "- 证据关系阶段必须在 `missingLinks[]` 逐条写出证据缺口；每项包含稳定 `id`、`description`、`neededEvidence` 和 `blocksConclusion`。",
            "- 必须显式写 `counterEvidenceRefs[]`：只登记真实限制、反例或否定性证据，每项包含 `evidenceRef`、`claim` 和处置 `disposition`；支持性背景关系不得冒充反证。",
            "- 如果没有真实反证，`counterEvidenceRefs=[]` 并保持 `status=needs_review`；不得为了通过门禁伪造反证引用。",
            "- `candidateRelations[]` 的每条边必须绑定真实 `evidenceRefs[]`，关系图只表达候选事实，不得升级为正式结论。",
            "- 先用 `source_collection_context_tool` 读到本批候选与写回契约：边端点优先用契约 `endpointPolicy.allowedEndpointIds` 中的完整 `candidateId`（主题枢纽端点用已声明主题的主题 ID，物化为 `source-theme:<themeId>`）。",
            "- 端点记不住完整 ID 时可写候选标题或已声明主题的 label/裸主题 ID 作语义端点，服务端会确定性解析回注册表节点；解析不了的边按悬空处理计入 `missingLinks`（danglingEdgeCount），阻塞下游 knowledge_ingestion。",
            "- 语义枢纽必须先在同一轮回写的 `themeNodes[]` 中声明（themeId+label）再连边；禁止发明 `rh_claim` 之类未声明的逻辑端点或展示别名。",
        ]
    return []
