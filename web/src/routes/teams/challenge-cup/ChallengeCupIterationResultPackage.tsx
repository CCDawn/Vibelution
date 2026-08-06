import { VEmptyState, VStatusChip, VTooltip, type VStatusTone } from "../../../components/vui";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import css from "./ChallengeCupIterationResultPackage.module.css";

type ChallengeProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;
type ChallengeCaseRecord = ChallengeProjection["stage3DeepResearchDelivery"]["caseRecords"][number];

function resultStatus(record: ChallengeCaseRecord): { label: string; tone: VStatusTone } {
  if (record.internalStatus === "accepted_for_writeup") {
    return { label: "已收录", tone: "accent" };
  }
  if (record.internalStatus === "blocked" || record.projectCompletionStatus === "blocked") {
    return { label: "待处理", tone: "warning" };
  }
  if (record.projectCompletionStatus === "completed") {
    return { label: "已完成", tone: "accent" };
  }
  return { label: "进行中", tone: "neutral" };
}

export function ChallengeCupIterationResultPackage({
  cases,
}: {
  cases: ChallengeCaseRecord[];
}) {
  if (cases.length === 0) {
    return <VEmptyState align="start" className={css.empty} title="暂无研究结果" />;
  }

  return (
    <section className={css.package} aria-labelledby="challenge-iteration-results-title">
      <header className={css.header}>
        <h3 id="challenge-iteration-results-title">研究结果</h3>
      </header>
      <ol className={css.list}>
        {cases.map((record) => {
          const status = resultStatus(record);
          const detail = [record.bestValidatedResultId, record.claimBoundary].filter(Boolean).join(" · ") || "暂未登记结果";
          return (
            <VTooltip content={detail} key={record.caseId} width="wide">
              <li className={css.record}>
                <strong className={css.title}>{record.title}</strong>
                <VStatusChip tone={status.tone}>{status.label}</VStatusChip>
              </li>
            </VTooltip>
          );
        })}
      </ol>
    </section>
  );
}
