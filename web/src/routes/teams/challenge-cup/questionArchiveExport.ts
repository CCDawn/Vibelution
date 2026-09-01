/**
 * Challenge-cup question archive export: single-file HTML artifact page.
 *
 * Turns the challenge question run detail payload (plus, optionally, the
 * team-level hypothesis review rounds) into one self-contained HTML document:
 * inline <style> block, no external resources, no script, no backend round
 * trip — the judges can open the downloaded file directly in any browser or
 * print it to PDF.
 *
 * Security posture: every LLM/human-authored string passes through
 * `escapeHtml` (including quotes so attribute contexts stay safe);
 * `evidence.source_url` only becomes a real href behind an http/https
 * whitelist, otherwise it renders as plain text. The document never embeds
 * scripts or event handlers.
 *
 * Evidence-faithfulness posture: the seven review dimensions and the
 * hypothesis-round score axes are rendered as independent values only — this
 * module never sums, averages or ranks them into a total score. The snapshot
 * footer records the audit hashes and the export timestamp so the page stays
 * an explicit "as-of export click" view.
 */
import type {
  ChallengeQuestionDimensionReview,
  ChallengeQuestionEvidence,
  ChallengeQuestionHypothesis,
  ChallengeQuestionOutput,
  ChallengeQuestionRunDetailPayload,
} from "../../../api/types";
import type {
  HypothesisRoundCandidate,
  HypothesisRoundListResponse,
  HypothesisRoundRecord,
} from "../../../api/types/hypothesisFirst";
import {
  challengeDimensionLabel,
  challengeEvidenceSourceTypeLabel,
  challengeEvidenceVerificationStatusLabel,
  challengeGateLabel,
  challengeRatingLabel,
  challengeRecordStatusLabel,
} from "./ChallengeQuestionDetailPrimitives";

export type QuestionArchiveLang = "zh" | "en";

export type QuestionArchiveExportOptions = {
  lang?: QuestionArchiveLang;
  /** Export snapshot time; defaults to `new Date()`. */
  generatedAt?: Date;
  maxEvidence?: number;
  maxHypotheses?: number;
  maxReviewRounds?: number;
  maxCandidatesPerRound?: number;
};

const DEFAULT_MAX_EVIDENCE = 12;
const DEFAULT_MAX_HYPOTHESES = 8;
const DEFAULT_MAX_REVIEW_ROUNDS = 6;
const DEFAULT_MAX_CANDIDATES_PER_ROUND = 8;
const DEFAULT_MAX_LIST_ITEMS = 12;
/** Text at or below this length renders inline; longer text folds into <details>. */
const FOLD_LIMIT = 320;

// Hypothesis-round score axes (the executor's 5+2 set). Kept aligned with the
// research-workflow leaderboard surface; presentation order is fixed and each
// axis stays an independent value.
const ROUND_SCORE_AXES: Array<{ key: string; zh: string; en: string }> = [
  { key: "novelty", zh: "新颖性", en: "Novelty" },
  { key: "competitionFit", zh: "竞赛契合", en: "Competition fit" },
  { key: "falsifiability", zh: "可证伪性", en: "Falsifiability" },
  { key: "evidenceSupport", zh: "证据支撑", en: "Evidence support" },
  { key: "feasibility", zh: "可行性", en: "Feasibility" },
];

const ROUND_DIAGNOSTIC_AXES: Array<{ key: string; zh: string; en: string }> = [
  { key: "replicability", zh: "可复现性（辅助）", en: "Replicability (aux)" },
  { key: "scopeAlignment", zh: "范围对齐（辅助）", en: "Scope alignment (aux)" },
];

const EVIDENCE_RELATION_LABELS: Record<string, { zh: string; en: string }> = {
  supports: { zh: "支持", en: "Supports" },
  challenges: { zh: "质疑", en: "Challenges" },
  context: { zh: "背景", en: "Context" },
  method: { zh: "方法", en: "Method" },
  boundary: { zh: "边界", en: "Boundary" },
};

// ---------------------------------------------------------------------------
// Escaping + small HTML helpers (the only gateway for payload-derived text)
// ---------------------------------------------------------------------------

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Only http(s) URLs may become real hrefs; anything else stays plain text. */
function safeHref(url: string): string | null {
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed) ? escapeHtml(trimmed) : null;
}

function bilingual(lang: QuestionArchiveLang, zh: string, en: string): string {
  return lang === "en" ? en : zh;
}

function missing(lang: QuestionArchiveLang): string {
  return `<span class="missing">${bilingual(lang, "未登记", "Not provided")}</span>`;
}

function truncationNote(total: number, shown: number, lang: QuestionArchiveLang): string {
  return `<p class="truncation-note">${bilingual(
    lang,
    `已截断：共 ${total} 条，仅展示前 ${shown} 条；完整数据以源 JSON 工件为准。`,
    `Truncated: ${total} items total, showing the first ${shown}.`,
  )}</p>`;
}

/**
 * Long LLM-authored text renders as a preview plus a folded full copy so the
 * page stays scannable without dropping any content.
 */
function foldableText(text: string, lang: QuestionArchiveLang): string {
  const full = String(text ?? "").trim();
  if (!full) return missing(lang);
  const escaped = escapeHtml(full);
  if (full.length <= FOLD_LIMIT) return `<p>${escaped}</p>`;
  const preview = escapeHtml(`${full.slice(0, FOLD_LIMIT)}…`);
  return `<p>${preview}</p><details><summary>${bilingual(
    lang,
    `展开全文（共 ${full.length} 字）`,
    `Show full text (${full.length} chars)`,
  )}</summary><p>${escaped}</p></details>`;
}

function stringList(
  values: readonly string[] | undefined,
  lang: QuestionArchiveLang,
  limit = DEFAULT_MAX_LIST_ITEMS,
): string {
  const items = Array.isArray(values) ? values : [];
  if (!items.length) return missing(lang);
  const shown = items.slice(0, limit);
  const rendered = shown.map((value) => `<li>${escapeHtml(value)}</li>`).join("");
  const overflow = items.length > shown.length
    ? `<li class="more-note">${bilingual(
        lang,
        `…另有 ${items.length - shown.length} 项（已截断）`,
        `…${items.length - shown.length} more (truncated)`,
      )}</li>`
    : "";
  return `<ul class="compact">${rendered}${overflow}</ul>`;
}

function formatScore(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function sectionHeading(id: string, index: string, title: string): string {
  return `<section id="${escapeHtml(id)}"><h2><span class="idx">${escapeHtml(index)}</span>${escapeHtml(title)}</h2>`;
}

function gateBlock(
  gate: { decision: string; rationale: string; reviewer?: string; decided_at?: string },
  lang: QuestionArchiveLang,
): string {
  const meta = [
    gate.reviewer ? bilingual(lang, `审核人：${gate.reviewer}`, `Reviewer: ${gate.reviewer}`) : "",
    gate.decided_at ? bilingual(lang, `决定时间：${gate.decided_at}`, `Decided at: ${gate.decided_at}`) : "",
  ].filter(Boolean).map((line) => `<span>${escapeHtml(line)}</span>`).join("");
  return `<div class="gate"><span class="gate-chip">${escapeHtml(challengeGateLabel(gate.decision, lang))}</span>${meta ? `<span class="gate-meta">${meta}</span>` : ""}${gate.rationale ? `<p>${escapeHtml(gate.rationale)}</p>` : ""}</div>`;
}

function localStamp(at: Date): string {
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

function formattedExportTime(at: Date, lang: QuestionArchiveLang): string {
  return `${escapeHtml(localStamp(at))}（${bilingual(lang, "本地时间", "local")} / ${escapeHtml(at.toISOString())}）`;
}

type ArchiveRating = ChallengeQuestionDimensionReview["rating"];

/** Tolerates the round-ledger extension ratings; unknown values pass through. */
function archiveRatingLabel(rating: string, lang: QuestionArchiveLang): string {
  return challengeRatingLabel(rating as ArchiveRating, lang) ?? rating;
}

// ---------------------------------------------------------------------------
// Section builders
// ---------------------------------------------------------------------------

function pageHeader(detail: ChallengeQuestionRunDetailPayload, lang: QuestionArchiveLang, at: Date): string {
  const { output, record } = detail;
  const meta = [
    bilingual(lang, `题号：${detail.questionId}`, `Question: ${detail.questionId}`),
    bilingual(lang, `状态：${challengeRecordStatusLabel(record.status, lang)}`, `Status: ${challengeRecordStatusLabel(record.status, lang)}`),
    bilingual(lang, `目录：${output.catalog_id}（schema v${output.schema_version}）`, `Catalog: ${output.catalog_id} (schema v${output.schema_version})`),
    bilingual(lang, `运行：${output.run.run_id}`, `Run: ${output.run.run_id}`),
    `${output.run.model_provider}/${output.run.model_id} · ${output.run.platform}`,
    bilingual(lang, `导出时间：${formattedExportTime(at, lang)}`, `Exported at: ${formattedExportTime(at, lang)}`),
  ].map((line) => `<span>${escapeHtml(line)}</span>`).join("");
  return `<header class="page-header"><p class="eyebrow">${bilingual(
    lang,
    "挑战杯题目档案 · 科研链路产物快照",
    "Challenge Cup question archive · research-chain artifact snapshot",
  )}</p><h1>${escapeHtml(output.question_en)}</h1>${output.question_zh ? `<p class="question-zh">${escapeHtml(output.question_zh)}</p>` : ""}<div class="meta">${meta}</div></header>`;
}

function tableOfContents(lang: QuestionArchiveLang): string {
  const entries: Array<[string, string]> = [
    ["understanding", bilingual(lang, "问题理解", "Problem understanding")],
    ["evidence", bilingual(lang, "证据清单", "Evidence register")],
    ["hypotheses", bilingual(lang, "候选假设", "Candidate hypotheses")],
    ["reviews", bilingual(lang, "七维评价", "Seven-dimension review")],
    ["selection", bilingual(lang, "假说选择", "Hypothesis selection")],
    ["plan", bilingual(lang, "研究计划", "Research plan")],
    ["feedback", bilingual(lang, "反馈修正", "Feedback iterations")],
    ["summary", bilingual(lang, "最终总结", "Final summary")],
    ["rounds", bilingual(lang, "评审历程", "Review history")],
  ];
  const items = entries.map(([id, label]) => `<a href="#${id}">${label}</a>`).join("");
  return `<nav class="toc" aria-label="${bilingual(lang, "章节目录", "Sections")}">${items}</nav>`;
}

function understandingSection(output: ChallengeQuestionOutput, lang: QuestionArchiveLang): string {
  const pu = output.problem_understanding;
  return `${sectionHeading("understanding", "01", bilingual(lang, "问题理解", "Problem understanding"))}
<div class="card">${foldableText(pu.scope, lang)}
<dl class="pairs">
<div><dt>${bilingual(lang, "子问题", "Subquestions")}</dt><dd>${stringList(pu.subquestions, lang)}</dd></div>
<div><dt>${bilingual(lang, "假设前提", "Assumptions")}</dt><dd>${stringList(pu.assumptions, lang)}</dd></div>
<div><dt>${bilingual(lang, "已知未知", "Known unknowns")}</dt><dd>${stringList(pu.known_unknowns, lang)}</dd></div>
</dl>
<div class="gate-line"><strong>${bilingual(lang, "人工闸门", "Human gate")}</strong>${gateBlock(pu.human_gate, lang)}</div>
</div></section>`;
}

function evidenceSection(output: ChallengeQuestionOutput, options: QuestionArchiveExportOptions, lang: QuestionArchiveLang): string {
  const evidence = Array.isArray(output.evidence) ? output.evidence : [];
  const max = options.maxEvidence ?? DEFAULT_MAX_EVIDENCE;
  const shown = evidence.slice(0, max);
  const rows = shown.map((item: ChallengeQuestionEvidence) => {
    const href = safeHref(item.source_url || "");
    const link = href
      ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a>`
      : (item.source_url ? `<span class="plain-url">${escapeHtml(item.source_url)}</span>` : missing(lang));
    const limitations = Array.isArray(item.limitations) && item.limitations.length
      ? `<details><summary>${bilingual(lang, `局限（${item.limitations.length}）`, `Limitations (${item.limitations.length})`)}</summary>${stringList(item.limitations, lang)}</details>`
      : "";
    return `<tr>
<td><code>${escapeHtml(item.evidence_id)}</code></td>
<td><strong>${escapeHtml(item.title)}</strong><div class="sub">${escapeHtml(challengeEvidenceSourceTypeLabel(item.source_type, lang))}${item.doi ? ` · DOI ${escapeHtml(item.doi)}` : ""} · ${bilingual(lang, `检索于 ${item.retrieved_at}`, `retrieved ${item.retrieved_at}`)}</div>${link}${limitations}</td>
<td>${escapeHtml(EVIDENCE_RELATION_LABELS[item.relation]?.[lang] ?? item.relation)}</td>
<td>${foldableText(item.fact, lang)}</td>
<td><span class="chip">${escapeHtml(challengeEvidenceVerificationStatusLabel(item.verification_status, lang))}</span></td>
</tr>`;
  }).join("");
  return `${sectionHeading("evidence", "02", bilingual(lang, "证据清单", "Evidence register"))}
<p class="hint">${bilingual(lang, "来源链接仅保留 http/https 白名单内的可点击地址，其余按文本展示。", "Only http/https source URLs render as links; everything else stays plain text.")}</p>
<table><thead><tr><th>ID</th><th>${bilingual(lang, "题目 / 来源", "Title / source")}</th><th>${bilingual(lang, "关系", "Relation")}</th><th>${bilingual(lang, "证据事实", "Fact")}</th><th>${bilingual(lang, "核验", "Verification")}</th></tr></thead>
<tbody>${rows || `<tr><td colspan="5">${bilingual(lang, "无证据记录", "No evidence records")}</td></tr>`}</tbody></table>
${evidence.length > shown.length ? truncationNote(evidence.length, shown.length, lang) : ""}</section>`;
}

function hypothesisCard(hypothesis: ChallengeQuestionHypothesis, selectedId: string, lang: QuestionArchiveLang): string {
  const refs = (label: string, values: readonly string[]) =>
    `<div class="refs"><span class="refs-label">${label}</span>${values.length
      ? values.map((ref) => `<code>${escapeHtml(ref)}</code>`).join(" ")
      : missing(lang)}</div>`;
  return `<article class="card hypothesis${hypothesis.hypothesis_id === selectedId ? " selected" : ""}">
<h3><code>${escapeHtml(hypothesis.hypothesis_id)}</code>${hypothesis.hypothesis_id === selectedId ? `<span class="chip accent">${bilingual(lang, "已选用", "Selected")}</span>` : ""}</h3>
<p class="statement">${escapeHtml(hypothesis.statement)}</p>
<dl class="pairs">
<div><dt>${bilingual(lang, "机制", "Mechanism")}</dt><dd>${foldableText(hypothesis.mechanism, lang)}</dd></div>
<div><dt>${bilingual(lang, "新颖性依据", "Novelty basis")}</dt><dd>${foldableText(hypothesis.novelty_basis, lang)}</dd></div>
<div><dt>${bilingual(lang, "可证伪性", "Falsifiability")}</dt><dd>${foldableText(hypothesis.falsifiability, lang)}</dd></div>
<div><dt>${bilingual(lang, "预测", "Predictions")}</dt><dd>${stringList(hypothesis.predictions, lang)}</dd></div>
<div><dt>${bilingual(lang, "边界条件", "Boundary conditions")}</dt><dd>${stringList(hypothesis.boundary_conditions, lang)}</dd></div>
</dl>
${refs(bilingual(lang, "支持证据", "Supporting evidence"), hypothesis.supporting_evidence_refs)}
${refs(bilingual(lang, "质疑证据", "Challenging evidence"), hypothesis.challenging_evidence_refs)}
</article>`;
}

function hypothesesSection(output: ChallengeQuestionOutput, options: QuestionArchiveExportOptions, lang: QuestionArchiveLang): string {
  const hypotheses = Array.isArray(output.hypotheses) ? output.hypotheses : [];
  const max = options.maxHypotheses ?? DEFAULT_MAX_HYPOTHESES;
  const shown = hypotheses.slice(0, max);
  return `${sectionHeading("hypotheses", "03", bilingual(lang, "候选假设", "Candidate hypotheses"))}
${shown.map((hypothesis) => hypothesisCard(hypothesis, output.selection.selected_hypothesis_id, lang)).join("")}
${hypotheses.length > shown.length ? truncationNote(hypotheses.length, shown.length, lang) : ""}</section>`;
}

function reviewsSection(output: ChallengeQuestionOutput, lang: QuestionArchiveLang): string {
  const reviews = Array.isArray(output.dimension_reviews) ? output.dimension_reviews : [];
  if (!reviews.length) {
    return `${sectionHeading("reviews", "04", bilingual(lang, "七维评价", "Seven-dimension review"))}
<p class="hint">${bilingual(lang, "暂无七维评价记录。", "No seven-dimension review records.")}</p></section>`;
  }
  const grouped = new Map<string, ChallengeQuestionDimensionReview[]>();
  for (const review of reviews) {
    const bucket = grouped.get(review.hypothesis_id) ?? [];
    bucket.push(review);
    grouped.set(review.hypothesis_id, bucket);
  }
  const blocks = [...grouped.entries()].map(([hypothesisId, rows]) => {
    const body = rows.map((row) => `<tr>
<td>${escapeHtml(challengeDimensionLabel(row.dimension, lang))}</td>
<td><span class="chip rating-${escapeHtml(row.rating)}">${escapeHtml(archiveRatingLabel(row.rating, lang))}</span></td>
<td>${foldableText(row.rationale, lang)}</td>
<td>${row.evidence_refs.length ? row.evidence_refs.map((ref) => `<code>${escapeHtml(ref)}</code>`).join(" ") : missing(lang)}</td>
<td>${escapeHtml(row.reviewer)}</td>
</tr>`).join("");
    return `<div class="card"><h3><code>${escapeHtml(hypothesisId)}</code></h3>
<table><thead><tr><th>${bilingual(lang, "维度", "Dimension")}</th><th>${bilingual(lang, "评级", "Rating")}</th><th>${bilingual(lang, "评价依据", "Rationale")}</th><th>${bilingual(lang, "证据引用", "Evidence refs")}</th><th>${bilingual(lang, "评审人", "Reviewer")}</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }).join("");
  return `${sectionHeading("reviews", "04", bilingual(lang, "七维评价", "Seven-dimension review"))}
<p class="hint">${bilingual(lang, "各维度独立评级，不汇总为总分。", "Dimensions are reported independently; no aggregate score is derived.")}</p>
${blocks}</section>`;
}

function selectionSection(output: ChallengeQuestionOutput, lang: QuestionArchiveLang): string {
  const selection = output.selection;
  const rejected = Array.isArray(selection.rejected_hypotheses) ? selection.rejected_hypotheses : [];
  const rejectedRows = rejected.map((item) => `<tr><td><code>${escapeHtml(item.hypothesis_id)}</code></td><td>${foldableText(item.reason, lang)}</td></tr>`).join("");
  return `${sectionHeading("selection", "05", bilingual(lang, "假说选择", "Hypothesis selection"))}
<div class="card">
<p><strong>${bilingual(lang, "选用假说", "Selected hypothesis")}</strong> <code>${escapeHtml(selection.selected_hypothesis_id)}</code></p>
<p><strong>${bilingual(lang, "比较方法", "Comparison method")}</strong> ${escapeHtml(selection.comparison_method)}</p>
<dl class="pairs"><div><dt>${bilingual(lang, "权衡", "Tradeoffs")}</dt><dd>${stringList(selection.tradeoffs, lang)}</dd></div></dl>
${rejected.length ? `<table><thead><tr><th>${bilingual(lang, "落选假说", "Rejected hypothesis")}</th><th>${bilingual(lang, "落选原因", "Reason")}</th></tr></thead><tbody>${rejectedRows}</tbody></table>` : ""}
<div class="gate-line"><strong>${bilingual(lang, "人工闸门", "Human gate")}</strong>${gateBlock(selection.human_gate, lang)}</div>
</div></section>`;
}

function planSection(output: ChallengeQuestionOutput, lang: QuestionArchiveLang): string {
  const plan = output.research_plan;
  const packages = (Array.isArray(plan.work_packages) ? plan.work_packages : []).map((wp) => `<article class="card">
<h3><code>${escapeHtml(wp.work_package_id)}</code> ${escapeHtml(wp.goal)}</h3>
<dl class="pairs">
<div><dt>${bilingual(lang, "输入", "Inputs")}</dt><dd>${stringList(wp.inputs, lang)}</dd></div>
<div><dt>${bilingual(lang, "步骤", "Procedure")}</dt><dd>${stringList(wp.procedure, lang)}</dd></div>
<div><dt>${bilingual(lang, "产出", "Outputs")}</dt><dd>${stringList(wp.outputs, lang)}</dd></div>
<div><dt>${bilingual(lang, "依赖", "Dependencies")}</dt><dd>${stringList(wp.dependencies, lang)}</dd></div>
</dl>
</article>`).join("");
  const pairRow = (label: string, values: readonly string[] | undefined) =>
    `<div><dt>${label}</dt><dd>${stringList(values, lang)}</dd></div>`;
  return `${sectionHeading("plan", "06", bilingual(lang, "研究计划", "Research plan"))}
<div class="card">
<dl class="pairs">
<div><dt>${bilingual(lang, "目标", "Objective")}</dt><dd>${foldableText(plan.objective, lang)}</dd></div>
<div><dt>${bilingual(lang, "方法", "Method")}</dt><dd>${foldableText(plan.method, lang)}</dd></div>
${pairRow(bilingual(lang, "变量", "Variables"), plan.variables)}
${pairRow(bilingual(lang, "对照", "Controls"), plan.controls)}
${pairRow(bilingual(lang, "数据与材料", "Data & materials"), plan.data_and_materials)}
${pairRow(bilingual(lang, "分析", "Analysis"), plan.analysis)}
${pairRow(bilingual(lang, "成功判据", "Success criteria"), plan.success_criteria)}
${pairRow(bilingual(lang, "失败判据", "Failure criteria"), plan.failure_criteria)}
${pairRow(bilingual(lang, "停止条件", "Stop conditions"), plan.stop_conditions)}
${pairRow(bilingual(lang, "资源", "Resources"), plan.resources)}
${pairRow(bilingual(lang, "时间线", "Timeline"), plan.timeline)}
${pairRow(bilingual(lang, "风险", "Risks"), plan.risks)}
</dl>
<div class="gate-line"><strong>${bilingual(lang, "人工闸门", "Human gate")}</strong>${gateBlock(plan.human_gate, lang)}</div>
</div>
<h3 class="sub-heading">${bilingual(lang, "工作包", "Work packages")}</h3>
${packages || `<p class="hint">${bilingual(lang, "未登记工作包。", "No work packages.")}</p>`}</section>`;
}

function feedbackSection(output: ChallengeQuestionOutput, lang: QuestionArchiveLang): string {
  const iterations = Array.isArray(output.feedback_iterations) ? output.feedback_iterations : [];
  if (!iterations.length) {
    return `${sectionHeading("feedback", "07", bilingual(lang, "反馈修正", "Feedback iterations"))}
<p class="hint">${bilingual(lang, "暂无反馈修正记录。", "No feedback iteration records.")}</p></section>`;
  }
  const blocks = iterations.map((iteration) => `<article class="card">
<h3>${bilingual(lang, `第 ${iteration.round} 轮`, `Round ${iteration.round}`)} · ${escapeHtml(iteration.trigger)}</h3>
<dl class="pairs">
<div><dt>${bilingual(lang, "人工反馈", "Human feedback")}</dt><dd>${foldableText(iteration.human_feedback, lang)}</dd></div>
<div><dt>${bilingual(lang, "修改内容", "Changes")}</dt><dd>${stringList(iteration.changes, lang)}</dd></div>
<div><dt>${bilingual(lang, "未决问题", "Unresolved issues")}</dt><dd>${stringList(iteration.unresolved_issues, lang)}</dd></div>
<div><dt>${bilingual(lang, "输入引用", "Input refs")}</dt><dd>${stringList(iteration.input_refs, lang)}</dd></div>
</dl>
</article>`).join("");
  return `${sectionHeading("feedback", "07", bilingual(lang, "反馈修正", "Feedback iterations"))}${blocks}</section>`;
}

function summarySection(output: ChallengeQuestionOutput, lang: QuestionArchiveLang): string {
  const summary = output.final_summary;
  const refs = (label: string, values: readonly string[]) =>
    `<div><dt>${label}</dt><dd>${values.length ? values.map((ref) => `<code>${escapeHtml(ref)}</code>`).join(" ") : missing(lang)}</dd></div>`;
  return `${sectionHeading("summary", "08", bilingual(lang, "最终总结", "Final summary"))}
<div class="card"><dl class="pairs">
<div><dt>${bilingual(lang, "答案边界", "Answer boundary")}</dt><dd>${foldableText(summary.answer_boundary, lang)}</dd></div>
<div><dt>${bilingual(lang, "选用假说", "Selected hypothesis")}</dt><dd>${foldableText(summary.selected_hypothesis, lang)}</dd></div>
<div><dt>${bilingual(lang, "研究计划摘要", "Research plan summary")}</dt><dd>${foldableText(summary.research_plan_summary, lang)}</dd></div>
${refs(bilingual(lang, "关键证据", "Key evidence"), summary.key_evidence_refs)}
${refs(bilingual(lang, "反例证据", "Counterevidence"), summary.counterevidence_refs)}
<div><dt>${bilingual(lang, "局限", "Limitations")}</dt><dd>${stringList(summary.limitations, lang)}</dd></div>
<div><dt>${bilingual(lang, "下一步验证", "Next validation step")}</dt><dd>${foldableText(summary.next_validation_step, lang)}</dd></div>
</dl></div></section>`;
}

function roundsScope(
  rounds: HypothesisRoundListResponse | null | undefined,
  questionId: string,
): { visible: HypothesisRoundRecord[]; scopeFallback: boolean } {
  const ledger = rounds && Array.isArray(rounds.rounds) ? rounds.rounds : [];
  const normalized = questionId.trim().toUpperCase();
  if (!normalized) return { visible: ledger, scopeFallback: false };
  const matching = ledger.filter(
    (round) => String(round?.question ?? "").trim().toUpperCase() === normalized,
  );
  if (matching.length > 0) return { visible: matching, scopeFallback: false };
  const scoped = ledger.filter((round) => String(round?.question ?? "").trim().length > 0);
  // The wire carries no question scope at all: fall back to the team ledger
  // with an explicit annotation instead of an empty section.
  if (scoped.length === 0) return { visible: ledger, scopeFallback: true };
  return { visible: [], scopeFallback: false };
}

function candidateBlock(round: HypothesisRoundRecord, lang: QuestionArchiveLang, max: number): string {
  const candidates = Array.isArray(round.candidates) ? round.candidates : [];
  const shown = candidates.slice(0, max);
  const recommendedId = String(round.metaReview?.recommendationCandidateId ?? "").trim();
  const rows = shown.map((candidate: HypothesisRoundCandidate) => {
    const scores = ROUND_SCORE_AXES.map((axis) =>
      `<span class="score"><i>${bilingual(lang, axis.zh, axis.en)}</i>${formatScore(candidate.scores?.[axis.key])}</span>`).join("");
    const diagnostics = ROUND_DIAGNOSTIC_AXES.map((axis) =>
      `<span class="score aux"><i>${bilingual(lang, axis.zh, axis.en)}</i>${formatScore(candidate.diagnostics?.[axis.key])}</span>`).join("");
    const reviewRows = Array.isArray(candidate.dimensionReviews) && candidate.dimensionReviews.length
      ? `<details><summary>${bilingual(lang, `七维评审（${candidate.dimensionReviews.length}）`, `Dimension reviews (${candidate.dimensionReviews.length})`)}</summary><table><thead><tr><th>${bilingual(lang, "维度", "Dimension")}</th><th>${bilingual(lang, "评级", "Rating")}</th><th>${bilingual(lang, "评价依据", "Rationale")}</th></tr></thead><tbody>${candidate.dimensionReviews.map((review) => `<tr><td>${escapeHtml(challengeDimensionLabel(review.dimension, lang))}</td><td><span class="chip rating-${escapeHtml(review.rating)}">${escapeHtml(archiveRatingLabel(review.rating, lang))}</span></td><td>${foldableText(review.rationale, lang)}</td></tr>`).join("")}</tbody></table></details>`
      : "";
    return `<tr>
<td><code>${escapeHtml(candidate.candidateId)}</code>${candidate.candidateId === recommendedId && recommendedId ? `<div class="sub">${bilingual(lang, "MetaReview 推荐", "MetaReview pick")}</div>` : ""}</td>
<td>${foldableText(candidate.claim, lang)}${reviewRows}</td>
<td class="scores">${scores}${diagnostics}</td>
<td><span class="chip">${escapeHtml(candidate.status)}</span></td>
<td>${escapeHtml(candidate.reviewedBy)}</td>
</tr>`;
  }).join("");
  const table = `<table><thead><tr><th>${bilingual(lang, "候选", "Candidate")}</th><th>${bilingual(lang, "论断", "Claim")}</th><th>${bilingual(lang, "各维得分", "Per-dimension scores")}</th><th>${bilingual(lang, "状态", "Status")}</th><th>${bilingual(lang, "评审执行者", "Reviewed by")}</th></tr></thead><tbody>${rows || `<tr><td colspan="5">${bilingual(lang, "无候选记录", "No candidates")}</td></tr>`}</tbody></table>`;
  const overflow = candidates.length > shown.length ? truncationNote(candidates.length, shown.length, lang) : "";
  return `${table}
<p class="hint">${bilingual(lang, "评审执行器不产出总分；以上为各独立维度得分。", "The review executor produces no total score; each axis is independent.")}</p>${overflow}`;
}

function roundCard(round: HypothesisRoundRecord, lang: QuestionArchiveLang, maxCandidates: number): string {
  const parts: string[] = [];
  parts.push(`<h3>${escapeHtml(round.roundId)} <span class="chip">${escapeHtml(round.status)}</span></h3>`);
  parts.push(`<p class="sub">${escapeHtml(bilingual(lang, `创建于 ${round.createdAt}`, `Created ${round.createdAt}`))}${round.closedAt ? ` · ${escapeHtml(bilingual(lang, `关闭于 ${round.closedAt}`, `closed ${round.closedAt}`))}` : ""}</p>`);
  parts.push(`<h4>${bilingual(lang, "候选与得分", "Candidates & scores")}</h4>`);
  parts.push(candidateBlock(round, lang, maxCandidates));

  const pareto = round.pareto;
  const front = Array.isArray(pareto?.paretoFrontCandidateIds) ? pareto.paretoFrontCandidateIds : [];
  const dominated = Array.isArray(pareto?.dominatedCandidateIds) ? pareto.dominatedCandidateIds : [];
  if (front.length) {
    const dominatedNote = dominated.length
      ? ` <span class="sub">${escapeHtml(bilingual(lang, `（受支配 ${dominated.length} 个）`, `(${dominated.length} dominated)`))}</span>`
      : "";
    parts.push(`<p><strong>${bilingual(lang, "Pareto 前沿", "Pareto front")}</strong> ${front.map((id) => `<code>${escapeHtml(id)}</code>`).join(" ")}${dominatedNote}</p>`);
    if (pareto?.notes) {
      parts.push(`<div class="refs"><span class="refs-label">${bilingual(lang, "Pareto 分析备注", "Pareto analyst notes")}</span></div>${foldableText(pareto.notes, lang)}`);
    }
  }

  const comparisons = Array.isArray(round.pairwiseComparisons) ? round.pairwiseComparisons : [];
  if (comparisons.length) {
    const lines = comparisons.map((comparison) =>
      `<li><code>${escapeHtml(comparison.leftCandidateId)}</code> vs <code>${escapeHtml(comparison.rightCandidateId)}</code> → ${escapeHtml(comparison.outcome)}${comparison.justification ? ` — ${escapeHtml(comparison.justification)}` : ""}</li>`).join("");
    parts.push(`<details><summary>${bilingual(lang, `两两对比（${comparisons.length} 组）`, `Pairwise comparisons (${comparisons.length})`)}</summary><ul class="compact">${lines}</ul></details>`);
  }

  const metaReview = round.metaReview;
  const recommendedId = String(metaReview?.recommendationCandidateId ?? "").trim();
  if (recommendedId) {
    const accepted = metaReview?.accepted
      ? ` <span class="chip accent">${bilingual(lang, "已采纳", "Accepted")}</span>`
      : "";
    parts.push(`<p><strong>MetaReview</strong> → <code>${escapeHtml(recommendedId)}</code>${accepted}</p>`);
    if (metaReview?.rationale) parts.push(foldableText(metaReview.rationale, lang));
    if (metaReview?.riskNotes) {
      parts.push(`<div class="refs"><span class="refs-label">${bilingual(lang, "风险备注", "Risk notes")}</span></div>${foldableText(metaReview.riskNotes, lang)}`);
    }
  }
  return `<article class="card round">${parts.join("\n")}</article>`;
}

function reviewRoundsSection(
  rounds: HypothesisRoundListResponse | null | undefined,
  questionId: string,
  options: QuestionArchiveExportOptions,
  lang: QuestionArchiveLang,
): string {
  const heading = sectionHeading("rounds", "09", bilingual(lang, "评审历程", "Review history"));
  if (rounds === null || rounds === undefined) {
    return `${heading}<p class="hint">${bilingual(lang, "评审历程不可用：导出时未能读取评审轮次台账（只读端点），其余章节不受影响。", "Review history unavailable: the review-round ledger (read-only endpoint) could not be read at export time. Other sections are unaffected.")}</p></section>`;
  }
  const { visible, scopeFallback } = roundsScope(rounds, questionId);
  if (!visible.length) {
    return `${heading}<p class="hint">${bilingual(lang, "未找到与本题关联的评审轮次记录。", "No review rounds are associated with this question.")}</p></section>`;
  }
  const max = options.maxReviewRounds ?? DEFAULT_MAX_REVIEW_ROUNDS;
  const maxCandidates = options.maxCandidatesPerRound ?? DEFAULT_MAX_CANDIDATES_PER_ROUND;
  const shown = visible.slice(0, max);
  const blocks = shown.map((round) => roundCard(round, lang, maxCandidates)).join("\n");
  const annotation = scopeFallback
    ? `<p class="hint">${bilingual(lang, "轮次台账未携带题目归属字段，以下展示本团队全部轮次。", "The ledger carries no question scope; showing the full team ledger below.")}</p>`
    : "";
  const overflow = visible.length > shown.length ? truncationNote(visible.length, shown.length, lang) : "";
  return `${heading}
${annotation}${blocks}
${overflow}</section>`;
}

function integrityFooter(
  detail: ChallengeQuestionRunDetailPayload,
  at: Date,
  lang: QuestionArchiveLang,
): string {
  const { output, record, artifact } = detail;
  const code = (label: string, value: string) =>
    value ? `<div class="integrity-line"><span>${escapeHtml(label)}</span><code>${escapeHtml(value)}</code></div>` : "";
  return `<footer class="integrity">
<h2>${bilingual(lang, "完整性信息（导出时刻快照）", "Integrity (snapshot as of export)")}</h2>
${code(bilingual(lang, "产出 SHA-256", "Output SHA-256"), output.audit.output_sha256)}
${code(bilingual(lang, "来源目录 SHA-256", "Source catalog SHA-256"), output.audit.source_catalog_sha256)}
${code(bilingual(lang, "工件 SHA-256", "Artifact SHA-256"), artifact?.sha256 || record.outputSha256 || "")}
${code(bilingual(lang, "工件路径", "Artifact path"), artifact?.path || record.artifactPath || "")}
${code(bilingual(lang, "选中运行", "Selected run"), detail.selectedRunId || record.runId)}
${code(bilingual(lang, "Schema 校验", "Schema validation"), output.audit.schema_validation)}
${code(bilingual(lang, "引用校验", "Citation validation"), output.audit.citation_validation)}
${code(bilingual(lang, "人工评审状态", "Human review status"), output.audit.human_review_status)}
${code(bilingual(lang, "导出时间", "Exported at"), `${localStamp(at)}（${bilingual(lang, "本地时间", "local")}）/ ${at.toISOString()}`)}
<p class="hint">${bilingual(
    lang,
    "本页面为「点击导出」时刻的只读快照，不随后端数据更新；工件不可变标记为 " + (artifact?.immutable ? "是" : "否") + "。",
    "This page is a read-only snapshot captured at export time and does not track later backend changes; artifact immutability: " + (artifact?.immutable ? "yes" : "no") + ".",
  )}</p>
</footer>`;
}

// ---------------------------------------------------------------------------
// Document assembly
// ---------------------------------------------------------------------------

const ARCHIVE_CSS = `
:root { color-scheme: light; --ink: #1c2430; --muted: #5b6675; --line: #d8dee7; --soft: #f4f6f9; --accent: #0f5ea8; }
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 32px 20px 48px; max-width: 1080px; color: var(--ink); background: #fff;
  font: 15px/1.65 "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif; }
h1 { font-size: 26px; line-height: 1.3; margin: 6px 0 4px; }
h2 { font-size: 19px; margin: 34px 0 12px; padding-bottom: 6px; border-bottom: 2px solid var(--line); }
h3 { font-size: 16px; margin: 14px 0 6px; }
h4 { font-size: 14px; margin: 14px 0 6px; color: var(--muted); }
a { color: var(--accent); word-break: break-all; }
code { font-family: Consolas, "JetBrains Mono", monospace; font-size: 12.5px; background: var(--soft); padding: 1px 5px; border-radius: 4px; word-break: break-all; }
.eyebrow { color: var(--muted); letter-spacing: .08em; font-size: 12px; text-transform: uppercase; margin: 0; }
.question-zh { color: var(--muted); font-size: 16px; margin: 2px 0 8px; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 18px; color: var(--muted); font-size: 12.5px; margin-top: 8px; }
.toc { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 18px 0 6px; padding: 10px 14px; background: var(--soft); border-radius: 8px; font-size: 13px; }
.toc a { text-decoration: none; }
.card { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin: 10px 0; break-inside: avoid; }
.card.selected { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.card.hypothesis h3 { display: flex; align-items: center; gap: 8px; }
.statement { font-weight: 600; }
.pairs { display: grid; grid-template-columns: 1fr; gap: 6px; margin: 8px 0 0; }
.pairs > div { display: grid; grid-template-columns: 130px 1fr; gap: 10px; }
.pairs dt { color: var(--muted); font-size: 13px; padding-top: 2px; }
.pairs dd { margin: 0; }
.pairs p, .card > p { margin: 6px 0; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13.5px; }
th, td { border: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: var(--soft); font-size: 12.5px; color: var(--muted); }
tr { break-inside: avoid; }
.sub { color: var(--muted); font-size: 12.5px; margin-top: 4px; }
.sub-heading { margin-top: 20px; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 999px; background: var(--soft); border: 1px solid var(--line); font-size: 12px; }
.chip.accent { background: #e8f1fb; border-color: #b6d4f0; color: var(--accent); }
.chip.rating-strong { background: #e7f5ec; border-color: #bfe3cd; }
.chip.rating-adequate { background: #eef4e7; border-color: #d3e3bf; }
.chip.rating-mixed { background: #fdf3e0; border-color: #f0d9ae; }
.chip.rating-weak, .chip.rating-insufficient { background: #fbecea; border-color: #eecdc7; }
.score { display: inline-flex; gap: 5px; align-items: baseline; margin: 2px 10px 2px 0; font-variant-numeric: tabular-nums; }
.score i { color: var(--muted); font-size: 12px; font-style: normal; }
.score.aux { opacity: .75; }
.refs { margin: 8px 0 0; font-size: 13px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.refs-label { color: var(--muted); }
.compact { margin: 4px 0; padding-left: 20px; }
.gate-line { margin-top: 12px; display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.gate { display: inline-flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.gate-chip { display: inline-block; padding: 1px 8px; border-radius: 999px; background: #e8f1fb; border: 1px solid #b6d4f0; color: var(--accent); font-size: 12px; }
.gate-meta { display: inline-flex; gap: 12px; color: var(--muted); font-size: 12.5px; }
.gate p { flex-basis: 100%; margin: 4px 0 0; }
.missing { color: var(--muted); font-style: italic; }
.hint { color: var(--muted); font-size: 12.5px; margin: 6px 0; }
.truncation-note { color: #8a5a00; background: #fdf3e0; border: 1px solid #f0d9ae; border-radius: 6px; padding: 4px 10px; font-size: 12.5px; }
.plain-url { color: var(--muted); word-break: break-all; font-size: 12.5px; }
details { margin: 6px 0; }
summary { cursor: pointer; color: var(--accent); font-size: 13px; }
.integrity { margin-top: 40px; border-top: 2px solid var(--line); padding-top: 12px; }
.integrity-line { display: grid; grid-template-columns: 200px 1fr; gap: 10px; margin: 4px 0; font-size: 13px; }
.integrity-line span { color: var(--muted); }
.integrity-line code { justify-self: start; }
@media print {
  body { padding: 0; max-width: none; font-size: 12px; }
  .toc { display: none; }
  h2 { page-break-after: avoid; }
  .card, table, tr { page-break-inside: avoid; }
}
`.trim();

/**
 * Build the complete standalone HTML document for one challenge question.
 * `rounds` is the optional team hypothesis-round ledger; pass `undefined`
 * when it could not be read (the review-history section degrades visibly)
 * and an empty/filtered response when it was read successfully.
 */
export function buildQuestionArchiveHtml(
  detail: ChallengeQuestionRunDetailPayload,
  rounds?: HypothesisRoundListResponse | null,
  options: QuestionArchiveExportOptions = {},
): string {
  const lang: QuestionArchiveLang = options.lang ?? "zh";
  const at = options.generatedAt ?? new Date();
  const { output } = detail;
  const title = `挑战杯题目档案 ${detail.questionId}`;
  const sections = [
    understandingSection(output, lang),
    evidenceSection(output, options, lang),
    hypothesesSection(output, options, lang),
    reviewsSection(output, lang),
    selectionSection(output, lang),
    planSection(output, lang),
    feedbackSection(output, lang),
    summarySection(output, lang),
    reviewRoundsSection(rounds, detail.questionId, options, lang),
  ].join("\n");
  return `<!doctype html>
<html lang="${lang === "en" ? "en" : "zh-CN"}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
${ARCHIVE_CSS}
</style>
</head>
<body>
${pageHeader(detail, lang, at)}
${tableOfContents(lang)}
<main>
${sections}
</main>
${integrityFooter(detail, at, lang)}
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// File name + browser download + orchestration
// ---------------------------------------------------------------------------

/** `challenge-<questionId>-<yyyyMMdd-HHmm>.html`; unsafe id chars become `-`. */
export function questionArchiveFileName(questionId: string, at: Date = new Date()): string {
  const safeId = questionId.trim().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "question";
  const pad = (input: number) => String(input).padStart(2, "0");
  const stamp = `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}`;
  return `challenge-${safeId}-${stamp}.html`;
}

/** Browser download via a transient object URL; revokes it after the click. */
export function downloadQuestionArchiveHtml(filename: string, html: string): void {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export type QuestionArchiveExportDeps = {
  detail: ChallengeQuestionRunDetailPayload;
  /** Team used for the lazy round-ledger fetch; defaults to detail.teamId. */
  teamId?: string;
  lang?: QuestionArchiveLang;
  /** Injectable for tests; defaults to the read-only hypothesis-rounds API. */
  fetchRounds?: (teamId: string) => Promise<HypothesisRoundListResponse>;
  /** Injectable for tests; defaults to the browser download helper. */
  download?: (filename: string, html: string) => void;
  now?: () => Date;
};

export type QuestionArchiveExportResult = {
  filename: string;
  /** Whether the round ledger was read (false → history section says so). */
  roundsAvailable: boolean;
};

/**
 * The panel's export flow: lazily fetch the review-round ledger (failure is
 * non-blocking — the exported page simply marks that section unavailable),
 * assemble the document and trigger the download.
 */
export async function exportQuestionArchivePage(
  deps: QuestionArchiveExportDeps,
): Promise<QuestionArchiveExportResult> {
  const { detail } = deps;
  const now = deps.now ?? (() => new Date());
  const generatedAt = now();
  const teamId = (deps.teamId ?? detail.teamId).trim();
  let rounds: HypothesisRoundListResponse | undefined;
  let roundsAvailable = false;
  if (teamId && deps.fetchRounds) {
    try {
      rounds = await deps.fetchRounds(teamId);
      roundsAvailable = true;
    } catch {
      rounds = undefined;
    }
  }
  const html = buildQuestionArchiveHtml(detail, rounds, {
    lang: deps.lang ?? "zh",
    generatedAt,
  });
  const filename = questionArchiveFileName(detail.questionId, generatedAt);
  (deps.download ?? downloadQuestionArchiveHtml)(filename, html);
  return { filename, roundsAvailable };
}
