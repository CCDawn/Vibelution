import { LoaderCircle, Play } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./EvolutionRoute.styles";

export type EvolutionSupervisedRunPlanPanelProps = {
  lang: "zh" | "en";
  sourceLabel: string;
  plannedCasesText: string;
  memberCountText: string;
  startDisabled: boolean;
  startDisabledReason?: string;
  startPendingVisual: boolean;
  startLabel: string;
  startTooltip: string;
  onStart: () => void;
};

/**
 * Idle live-IO body: supervised run plan before a worktree run starts.
 */
export function EvolutionSupervisedRunPlanPanel({
  lang,
  sourceLabel,
  plannedCasesText,
  memberCountText,
  startDisabled,
  startDisabledReason,
  startPendingVisual,
  startLabel,
  startTooltip,
  onStart,
}: EvolutionSupervisedRunPlanPanelProps) {
  return (
    <div className={styles.supervisedRunPlan} role="status" data-vui-region="evolution-supervised-run-plan">
      <div className={styles.supervisedRunPlanLead}>
        <span className={styles.secondaryPill}>{lang === "zh" ? "运行前计划" : "Run plan"}</span>
        <h3>{lang === "zh" ? "准备开始监督进化" : "Ready to start supervised evolution"}</h3>
        <p>
          {lang === "zh"
            ? "开始后依次执行：基线运行、Judge 首评、原基线会话自改、新会话独立复跑、原 Judge 会话复评；用户审批后由 Judge 触发受控合入。"
            : "The baseline runs, the Judge scores it, the same baseline session self-improves, a fresh session reruns independently, and the same Judge session scores again before user-approved controlled merge."}
        </p>
      </div>
      <div className={styles.supervisedRunPlanGrid}>
        <article>
          <span>{lang === "zh" ? "评测来源" : "Evaluation source"}</span>
          <strong>{sourceLabel}</strong>
        </article>
        <article>
          <span>{lang === "zh" ? "计划样本" : "Planned cases"}</span>
          <strong>{plannedCasesText}</strong>
        </article>
        <article>
          <span>{lang === "zh" ? "监督成员" : "Supervised members"}</span>
          <strong>{memberCountText}</strong>
        </article>
        <article>
          <span>{lang === "zh" ? "生效方式" : "Runtime effect"}</span>
          <strong>{lang === "zh" ? "用户审批后决定" : "Decided after approval"}</strong>
        </article>
      </div>
      <div className={styles.supervisedRunPlanActions}>
        <VButton
          type="button"
          variant="primary"
          className={`${styles.inlineAction} ${styles.supervisedPrimaryAction}`}
          isDisabled={startDisabled}
          onClick={onStart}
          tooltip={startTooltip}
          disabledReason={startDisabledReason}
          icon={
            startPendingVisual
              ? <LoaderCircle size={15} />
              : <Play size={15} />
          }
        >
          {startLabel}
        </VButton>
        <span>{lang === "zh" ? "运行参数可在左侧调整。" : "Adjust run parameters in the left rail."}</span>
      </div>
      <p className={styles.supervisedRunPlanHint}>
        {lang === "zh"
          ? "运行启动后，这里会切换为当前 Agent 的真实会话轨迹。"
          : "After launch, this area switches to the active Agent's real conversation trace."}
      </p>
    </div>
  );
}
