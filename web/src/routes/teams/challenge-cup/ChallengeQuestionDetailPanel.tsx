import { AlertTriangle, ArrowLeft, ExternalLink, FileCheck2 } from "lucide-react";

import type {
  ChallengeQuestionDimensionReview,
  ChallengeQuestionRunDetailPayload,
} from "../../../api/types";
import {
  VEmptyState,
  VNativeButton,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import css from "./ChallengeQuestionDetailPanel.module.css";

export type ChallengeQuestionDetailPanelProps = {
  requestedQuestionId: string;
  detail?: ChallengeQuestionRunDetailPayload;
  isLoading: boolean;
  errorMessage?: string;
  onClose: () => void;
};

const DIMENSION_LABELS: Record<string, string> = {
  evidence_support: "证据支持",
  factual_accuracy: "事实准确",
  novelty: "新颖性",
  falsifiability: "可证伪性",
  plan_feasibility: "计划可行性",
  risk_and_ethics: "风险与伦理",
  counterexample_coverage: "反例覆盖",
};

function gateLabel(decision: string) {
  if (decision === "approved") return "已批准";
  if (decision === "revision_requested") return "需修订";
  if (decision === "rejected") return "已拒绝";
  return "待审核";
}

function ratingLabel(rating: ChallengeQuestionDimensionReview["rating"]) {
  return {
    insufficient: "不足",
    weak: "较弱",
    mixed: "混合",
    adequate: "充分",
    strong: "强",
  }[rating];
}

function StringList({ values }: { values: string[] }) {
  if (!values.length) {
    return <span className={css.missing}>未登记</span>;
  }
  return (
    <ul className={css.compactList}>
      {values.map((value) => <li key={value}>{value}</li>)}
    </ul>
  );
}

export function ChallengeQuestionDetailPanel({
  requestedQuestionId,
  detail,
  isLoading,
  errorMessage = "",
  onClose,
}: ChallengeQuestionDetailPanelProps) {
  if (isLoading) {
    return (
      <VSurface className={css.state} tone="workspace">
        <strong>正在读取 {requestedQuestionId} 的不可变审核工件…</strong>
        <span>数据来自团队级 Challenge Program 账本，不读取当前研究项目。</span>
      </VSurface>
    );
  }
  if (errorMessage || !detail) {
    return (
      <VSurface className={css.state} tone="workspace">
        <VEmptyState title={`${requestedQuestionId || "该题"} 的审核工件不可用`}>
          系统已停止，不会回退到当前研究项目或其他题目的资料。
        </VEmptyState>
        {errorMessage ? <code>{errorMessage}</code> : null}
        <VNativeButton className={css.secondaryButton} type="button" onClick={onClose}>
          返回题目列表
        </VNativeButton>
      </VSurface>
    );
  }

  const { output, record, artifact } = detail;
  const selectedHypothesis = output.hypotheses.find(
    (hypothesis) => hypothesis.hypothesis_id === output.selection.selected_hypothesis_id,
  );
  const reviewsByHypothesis = new Map<string, ChallengeQuestionDimensionReview[]>();
  output.dimension_reviews.forEach((review) => {
    const reviews = reviewsByHypothesis.get(review.hypothesis_id) ?? [];
    reviews.push(review);
    reviewsByHypothesis.set(review.hypothesis_id, reviews);
  });

  return (
    <main className={css.workspace} aria-label={`${detail.questionId} 单题白盒验收`}>
      <header className={css.header}>
        <div>
          <span className={css.eyebrow}>MVP 可信性验收 · 单题白盒</span>
          <h2>{detail.questionId}: {output.question_en}</h2>
          {output.question_zh ? <p>{output.question_zh}</p> : null}
        </div>
        <div className={css.headerActions}>
          <VStatusChip tone={record.status === "approved" ? "success" : "warning"}>
            {record.status === "approved" ? "正式批准" : record.status}
          </VStatusChip>
          <VNativeButton className={css.secondaryButton} type="button" onClick={onClose}>
            <ArrowLeft size={15} aria-hidden="true" />
            返回题目列表
          </VNativeButton>
        </div>
      </header>

      <nav className={css.anchorNav} aria-label="白盒验收步骤">
        {[
          ["question-agent", "题目与接单"],
          ["sources", "来源与证据"],
          ["hypotheses", "两个假设"],
          ["reviews", "七维评价"],
          ["selection", "选择理由"],
          ["plan", "研究计划"],
          ["feedback", "人工修改"],
          ["artifact", "最终工件"],
        ].map(([id, label], index) => (
          <a href={`#${id}`} key={id}><span>{index + 1}</span>{label}</a>
        ))}
      </nav>

      <section className={css.section} id="question-agent">
        <div className={css.sectionHeading}>
          <span>01</span>
          <div><h3>题目与接单</h3><p>先确认处理的是哪一题、哪次运行，以及谁实际接单。</p></div>
        </div>
        <div className={css.factGrid}>
          <VSurface tone="inset"><span>题号</span><strong>{detail.questionId}</strong></VSurface>
          <VSurface tone="inset"><span>运行</span><strong>{detail.selectedRunId}</strong></VSurface>
          <VSurface tone="inset"><span>登记执行者</span><strong>{record.registeredBy || "未登记"}</strong></VSurface>
          <VSurface tone="inset"><span>模型</span><strong>{output.run.model_id}</strong></VSurface>
        </div>
        <div className={css.warning}>
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <strong>题目级“接单 Agent”身份尚未写入正式工件</strong>
            <p>当前只能确认登记执行者与模型调用，不能据此推断具体 Agent。此处作为白盒验收缺口保留。</p>
          </div>
        </div>
        <VSurface className={css.explanation} tone="card">
          <strong>问题理解</strong>
          <p>{output.problem_understanding.scope}</p>
          <dl>
            <div><dt>子问题</dt><dd><StringList values={output.problem_understanding.subquestions} /></dd></div>
            <div><dt>假设前提</dt><dd><StringList values={output.problem_understanding.assumptions} /></dd></div>
            <div><dt>已知未知</dt><dd><StringList values={output.problem_understanding.known_unknowns} /></dd></div>
          </dl>
        </VSurface>
      </section>

      <section className={css.section} id="sources">
        <div className={css.sectionHeading}>
          <span>02</span>
          <div><h3>使用了哪些来源，提炼了什么证据</h3><p>来源元数据与登记的证据事实分开展示。</p></div>
        </div>
        <div className={css.cardList}>
          {output.evidence.map((evidence) => (
            <article className={css.evidenceCard} key={evidence.evidence_id}>
              <div className={css.cardTopline}>
                <strong>{evidence.evidence_id} · {evidence.title}</strong>
                <VStatusChip tone={evidence.relation === "challenges" ? "warning" : "neutral"}>
                  {evidence.relation}
                </VStatusChip>
              </div>
              <div className={css.metadata}>
                <span>{evidence.source_type}</span>
                <span>{evidence.verification_status}</span>
                {evidence.doi ? <span>DOI {evidence.doi}</span> : null}
                <a href={evidence.source_url} target="_blank" rel="noreferrer noopener">
                  打开来源 <ExternalLink size={13} aria-hidden="true" />
                </a>
              </div>
              <div className={css.fact}>
                <span>登记的证据事实（非原文摘录）</span>
                <p>{evidence.fact}</p>
              </div>
              <div className={css.missingLine}>原文逐字摘录与页码/段落锚点未登记</div>
              {evidence.limitations?.length ? (
                <div><strong>限制</strong><StringList values={evidence.limitations} /></div>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="hypotheses">
        <div className={css.sectionHeading}>
          <span>03</span>
          <div><h3>如何形成两个可证伪假设</h3><p>每个假设都展示机制、预测、证据引用与边界。</p></div>
        </div>
        <div className={css.twoColumn}>
          {output.hypotheses.map((hypothesis) => (
            <article className={css.hypothesisCard} key={hypothesis.hypothesis_id}>
              <div className={css.cardTopline}>
                <strong>{hypothesis.hypothesis_id}</strong>
                {hypothesis.hypothesis_id === output.selection.selected_hypothesis_id
                  ? <VStatusChip tone="success">最终选择</VStatusChip>
                  : <VStatusChip tone="neutral">备选</VStatusChip>}
              </div>
              <h4>{hypothesis.statement}</h4>
              <dl>
                <div><dt>机制</dt><dd>{hypothesis.mechanism}</dd></div>
                <div><dt>新颖性依据</dt><dd>{hypothesis.novelty_basis}</dd></div>
                <div><dt>如何证伪</dt><dd>{hypothesis.falsifiability}</dd></div>
                <div><dt>预测</dt><dd><StringList values={hypothesis.predictions} /></dd></div>
                <div><dt>支持证据</dt><dd>{hypothesis.supporting_evidence_refs.join(" · ")}</dd></div>
                <div><dt>挑战证据</dt><dd>{hypothesis.challenging_evidence_refs.join(" · ") || "无"}</dd></div>
                <div><dt>适用边界</dt><dd><StringList values={hypothesis.boundary_conditions} /></dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="reviews">
        <div className={css.sectionHeading}>
          <span>04</span>
          <div><h3>七维评价依据</h3><p>各维度独立呈现，不汇总成单一总分。</p></div>
        </div>
        <div className={css.reviewGroups}>
          {output.hypotheses.map((hypothesis) => (
            <article key={hypothesis.hypothesis_id}>
              <h4>{hypothesis.hypothesis_id}</h4>
              <div className={css.reviewGrid}>
                {(reviewsByHypothesis.get(hypothesis.hypothesis_id) ?? []).map((review) => (
                  <div key={`${review.hypothesis_id}-${review.dimension}`}>
                    <span>{DIMENSION_LABELS[review.dimension] || review.dimension}</span>
                    <strong>{ratingLabel(review.rating)}</strong>
                    <p>{review.rationale}</p>
                    <small>依据 {review.evidence_refs.join(" · ") || "未登记"} · {review.reviewer}</small>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="selection">
        <div className={css.sectionHeading}>
          <span>05</span>
          <div><h3>为什么选择其中一个</h3><p>机器比较方法与人工门禁的理由必须同时可见。</p></div>
        </div>
        <VSurface className={css.selection} tone="card">
          <div>
            <span>被选假设</span>
            <strong>{output.selection.selected_hypothesis_id}</strong>
            <p>{selectedHypothesis?.statement || "未找到对应假设"}</p>
          </div>
          <div>
            <span>比较方法</span>
            <strong>{output.selection.comparison_method}</strong>
            <StringList values={output.selection.tradeoffs} />
          </div>
          <div>
            <span>人工门禁</span>
            <strong>{gateLabel(output.selection.human_gate.decision)}</strong>
            <p>{output.selection.human_gate.rationale}</p>
          </div>
          <div>
            <span>未选择项</span>
            {output.selection.rejected_hypotheses.map((item) => (
              <p key={item.hypothesis_id}><strong>{item.hypothesis_id}</strong> · {item.reason}</p>
            ))}
          </div>
        </VSurface>
      </section>

      <section className={css.section} id="plan">
        <div className={css.sectionHeading}>
          <span>06</span>
          <div><h3>研究计划如何生成</h3><p>展示目标、方法、控制与可执行工作包。</p></div>
        </div>
        <VSurface className={css.plan} tone="card">
          <h4>{output.research_plan.objective}</h4>
          <p>{output.research_plan.method}</p>
          <div className={css.planGrid}>
            <div><strong>变量</strong><StringList values={output.research_plan.variables} /></div>
            <div><strong>控制</strong><StringList values={output.research_plan.controls} /></div>
            <div><strong>成功门槛</strong><StringList values={output.research_plan.success_criteria} /></div>
            <div><strong>失败门槛</strong><StringList values={output.research_plan.failure_criteria} /></div>
          </div>
          {output.research_plan.work_packages.map((workPackage) => (
            <article className={css.workPackage} key={workPackage.work_package_id}>
              <strong>{workPackage.work_package_id} · {workPackage.goal}</strong>
              <StringList values={workPackage.procedure} />
              <small>产出：{workPackage.outputs.join(" · ") || "未登记"}</small>
            </article>
          ))}
        </VSurface>
      </section>

      <section className={css.section} id="feedback">
        <div className={css.sectionHeading}>
          <span>07</span>
          <div><h3>人工审核修改了什么</h3><p>按反馈轮次保留触发原因、修改与未解决问题。</p></div>
        </div>
        <div className={css.timeline}>
          {output.feedback_iterations.map((iteration) => (
            <article key={iteration.round}>
              <span>第 {iteration.round} 轮</span>
              <div>
                <strong>{iteration.trigger}</strong>
                <p>{iteration.human_feedback}</p>
                <StringList values={iteration.changes} />
                {iteration.unresolved_issues.length ? (
                  <small>未解决：{iteration.unresolved_issues.join(" · ")}</small>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="artifact">
        <div className={css.sectionHeading}>
          <span>08</span>
          <div><h3>最终工件存在哪里</h3><p>路径、哈希和不可变属性来自正式团队级账本。</p></div>
        </div>
        <VSurface className={css.artifact} tone="inset">
          <FileCheck2 size={20} aria-hidden="true" />
          <div>
            <strong>{artifact.immutable ? "不可变审核工件" : "可变工件"}</strong>
            <code>{artifact.path}</code>
            <code>SHA256 {artifact.sha256}</code>
          </div>
        </VSurface>
      </section>
    </main>
  );
}
