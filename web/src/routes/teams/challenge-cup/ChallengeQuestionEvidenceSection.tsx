import { ExternalLink } from "lucide-react";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VStatusChip, VSurface } from "../../../components/vui";
import {
  ChallengeQuestionSectionHeading,
  ChallengeStringList,
} from "./ChallengeQuestionDetailPrimitives";
import css from "./ChallengeQuestionDetailPanel.styles";

type ChallengeQuestionEvidenceSectionProps = {
  detail: ChallengeQuestionRunDetailPayload;
  lang?: "zh" | "en";
};

const EVIDENCE_RELATION_LABELS: Record<string, string> = {
  supports: "支持",
  challenges: "质疑",
  context: "背景",
  method: "方法",
  boundary: "边界",
};

const EVIDENCE_RELATION_LABELS_EN: Record<string, string> = {
  supports: "Supports",
  challenges: "Challenges",
  context: "Context",
  method: "Method",
  boundary: "Boundary",
};

function evidenceRelationLabel(relation: string, lang: "zh" | "en"): string {
  return (lang === "en" ? EVIDENCE_RELATION_LABELS_EN : EVIDENCE_RELATION_LABELS)[relation] ?? relation;
}

export function ChallengeQuestionEvidenceSection({ detail, lang = "zh" }: ChallengeQuestionEvidenceSectionProps) {
  const isZh = lang === "zh";
  const { output, record } = detail;

  return (
    <>
      <section className={css.section} id="question-agent">
        <ChallengeQuestionSectionHeading index="01" title={isZh ? "题目与接单" : "Question & agent"} />
        <div className={css.factGrid}>
          <VSurface tone="inset"><span>{isZh ? "题号" : "Question"}</span><strong>{detail.questionId}</strong></VSurface>
          <VSurface tone="inset"><span>{isZh ? "运行" : "Run"}</span><strong>{detail.selectedRunId}</strong></VSurface>
          <VSurface tone="inset"><span>{isZh ? "登记执行者" : "Registered by"}</span><strong>{record.registeredBy || (isZh ? "未登记" : "Not registered")}</strong></VSurface>
          <VSurface tone="inset"><span>{isZh ? "模型" : "Model"}</span><strong>{output.run.model_id}</strong></VSurface>
        </div>
        <VSurface className={css.explanation} tone="card">
          <strong>{isZh ? "问题理解" : "Problem understanding"}</strong>
          <p>{output.problem_understanding.scope}</p>
          <dl>
            <div><dt>{isZh ? "子问题" : "Subquestions"}</dt><dd><ChallengeStringList values={output.problem_understanding.subquestions} lang={lang} /></dd></div>
            <div><dt>{isZh ? "假设前提" : "Assumptions"}</dt><dd><ChallengeStringList values={output.problem_understanding.assumptions} lang={lang} /></dd></div>
            <div><dt>{isZh ? "已知未知" : "Known unknowns"}</dt><dd><ChallengeStringList values={output.problem_understanding.known_unknowns} lang={lang} /></dd></div>
          </dl>
        </VSurface>
      </section>

      <section className={css.section} id="sources">
        <ChallengeQuestionSectionHeading index="02" title={isZh ? "来源与证据" : "Sources & evidence"} />
        <div className={css.cardList}>
          {output.evidence.map((evidence) => (
            <article className={css.evidenceCard} key={evidence.evidence_id}>
              <div className={css.cardTopline}>
                <strong>{evidence.evidence_id} · {evidence.title}</strong>
                <VStatusChip tone={evidence.relation === "challenges" ? "warning" : "neutral"}>
                  {evidenceRelationLabel(evidence.relation, lang)}
                </VStatusChip>
              </div>
              <div className={css.metadata}>
                <span>{evidence.source_type}</span>
                <span>{evidence.verification_status}</span>
                {evidence.doi ? <span>DOI {evidence.doi}</span> : null}
                <a href={evidence.source_url} target="_blank" rel="noreferrer noopener">
                  {isZh ? "打开来源" : "Open source"} <ExternalLink size={13} aria-hidden="true" />
                </a>
              </div>
              <div className={css.fact}>
                <span>{isZh ? "证据事实" : "Evidence fact"}</span>
                <p>{evidence.fact}</p>
              </div>
              {evidence.limitations?.length ? (
                <div><strong>{isZh ? "限制" : "Limitations"}</strong><ChallengeStringList values={evidence.limitations} lang={lang} /></div>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
