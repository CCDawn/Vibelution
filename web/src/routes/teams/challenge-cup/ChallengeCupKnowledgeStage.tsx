import { VRouteLinkButton, VStatusChip } from "../../../components/vui";
import type { ChallengeCupQuestion } from "./challengeCupStageModel";
import css from "./ChallengeCupKnowledgeStage.module.css";

type ChallengeCupKnowledgeStageProps = {
  citationGate: boolean;
  humanGate: boolean;
  humanStatusLabel: (status: ChallengeCupQuestion["humanStatus"]) => string;
  machineCompleted: number;
  modelLabel: string;
  officialCallCount: number;
  programTitle: string;
  questions: ChallengeCupQuestion[];
  researchTopic: string;
  revisionRequired: number;
  sourceQuestionId: string;
  onOpenQuestion: (questionId: string) => string;
};

export function ChallengeCupKnowledgeStage({
  citationGate,
  humanGate,
  humanStatusLabel,
  machineCompleted,
  modelLabel,
  officialCallCount,
  programTitle,
  questions,
  researchTopic,
  revisionRequired,
  sourceQuestionId,
  onOpenQuestion,
}: ChallengeCupKnowledgeStageProps) {
  const steps = [
    { label: "资料发现", complete: machineCompleted > 0 },
    { label: "内容提炼", complete: officialCallCount > 0 },
    { label: "关系整理", complete: citationGate },
    { label: "入库审核", complete: humanGate },
  ];

  return (
    <div className={css.stage}>
      <ol className={css.steps} aria-label="知识搜集步骤">
        {steps.map((step, index) => (
          <li className={css.step} data-complete={step.complete ? "true" : undefined} key={step.label}>
            <span className={css.stepIndex}>{step.complete ? "✓" : index + 1}</span>
            {step.label}
          </li>
        ))}
      </ol>

      <section className={css.focusCard} aria-label="当前研究主题">
        <strong className={css.focusTitle}>{researchTopic.trim() || programTitle}</strong>
        <span className={css.focusMeta}>{sourceQuestionId || "未登记"}</span>
      </section>

      <section className={css.dataSurface} aria-labelledby="challenge-knowledge-title">
        <header className={css.dataHeader}>
          <h3 id="challenge-knowledge-title">资料与证据</h3>
          <span className={css.evidenceCount}>{officialCallCount}</span>
        </header>
        <div className={css.tableWrap}>
          <table className={css.table}>
            <thead>
              <tr><th>对象</th><th>模型</th><th>机器</th><th>人工</th><th>证据</th></tr>
            </thead>
            <tbody>
              {questions.map((question) => (
                <tr key={question.id}>
                  <td>
                    <VRouteLinkButton
                      className={css.questionLink}
                      to={onOpenQuestion(question.id)}
                      variant="ghost"
                    >
                      {question.id}
                    </VRouteLinkButton>
                  </td>
                  <td>{modelLabel}</td>
                  <td>
                    <VStatusChip tone={question.machinePassed ? "accent" : "neutral"}>
                      {question.machinePassed ? "通过" : "待验证"}
                    </VStatusChip>
                  </td>
                  <td>
                    <VStatusChip tone={question.humanApproved ? "accent" : "warning"}>
                      {humanStatusLabel(question.humanStatus)}
                    </VStatusChip>
                  </td>
                  <td>{question.machinePassed ? revisionRequired > 0 ? "待修订" : "已追溯" : "待生成"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
