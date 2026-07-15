import { ArrowRight, CheckCircle2 } from "lucide-react";

import { VNativeButton } from "../components/vui";
import {
  sourceCollectionPhaseCloseGateNextStage,
  type SourceCollectionPhaseCloseGate,
  type SourceCollectionStageModuleId,
} from "./teams/source-collection/stageProjection";
import styles from "./TeamSourceCollectionPhaseCloseGatePanel.styles";

type TeamSourceCollectionPhaseCloseGatePanelProps = {
  lang: "zh" | "en";
  selectedRunId: string;
  gate: SourceCollectionPhaseCloseGate | null;
  loading: boolean;
  onOpenStage: (stageId: SourceCollectionStageModuleId) => void;
};

function stageLabel(stageId: SourceCollectionStageModuleId, lang: "zh" | "en") {
  const labels: Record<SourceCollectionStageModuleId, [string, string]> = {
    finding: ["资料发现", "Finding"],
    extraction: ["内容提炼", "Extraction"],
    relations: ["关系整理", "Relations"],
    ingestion: ["入库审核", "Ingestion"],
  };
  return labels[stageId][lang === "zh" ? 0 : 1];
}

function gateStatusCopy(status: string | undefined, lang: "zh" | "en") {
  if (status === "closed_loop") {
    return lang === "zh" ? "第一阶段已闭环" : "Phase one closed";
  }
  if (status === "ready_to_close") {
    return lang === "zh" ? "等待状态收口" : "Waiting to close";
  }
  if (status === "needs_continue") {
    return lang === "zh" ? "待继续" : "Continue needed";
  }
  if (status === "idle") {
    return lang === "zh" ? "尚未开始" : "Not started";
  }
  return lang === "zh" ? "正在核验" : "Checking";
}

function gateSummaryCopy(gate: SourceCollectionPhaseCloseGate | null, loading: boolean, lang: "zh" | "en") {
  if (!gate) {
    if (loading) {
      return lang === "zh" ? "正在核验当前批次的第一阶段闭环状态。" : "Checking the selected run's phase-one close gate.";
    }
    return lang === "zh"
      ? "当前批次尚无可验证的闭环投影；不会用全局历史统计替代。"
      : "No verifiable close gate is available for this run; aggregate history is not used as a substitute.";
  }
  if (gate.status === "closed_loop") {
    return lang === "zh" ? "当前批次的四个阶段均已完成，阶段轮次也已收口。" : "All four stages and the stage round are closed for this run.";
  }
  if (gate.status === "ready_to_close") {
    return lang === "zh" ? "四个阶段已达到要求，等待阶段轮次状态收口。" : "All four stages are ready; the stage-round state still needs closing.";
  }
  if (gate.status === "needs_continue") {
    return lang === "zh" ? "当前批次尚未闭环；请先完成下方提示的阶段。" : "This run is not closed yet; continue the indicated stage below.";
  }
  return lang === "zh" ? "请先选择或启动资料搜集批次。" : "Select or start a source-collection run first.";
}

function gateTone(status: string | undefined) {
  if (status === "closed_loop") {
    return styles.phaseCloseGateTagSuccess;
  }
  if (status === "needs_continue" || status === "ready_to_close") {
    return styles.phaseCloseGateTagWarning;
  }
  return styles.phaseCloseGateTagNeutral;
}

export function TeamSourceCollectionPhaseCloseGatePanel({
  lang,
  selectedRunId,
  gate,
  loading,
  onOpenStage,
}: TeamSourceCollectionPhaseCloseGatePanelProps) {
  const isZh = lang === "zh";
  const nextStage = sourceCollectionPhaseCloseGateNextStage(gate);
  const stageCount = typeof gate?.stageCount === "number" && gate.stageCount > 0
    ? gate.stageCount
    : (gate?.stages?.length || 4);
  const closedLoopCount = typeof gate?.closedLoopCount === "number" ? gate.closedLoopCount : 0;
  const reasons = (gate?.blockingReasons ?? []).filter(Boolean).slice(0, 2);

  return (
    <section
      className={styles.phaseCloseGatePanel}
      data-vui-product="source-collection-phase-close-gate"
      aria-label={isZh ? "第一阶段闭环门" : "Phase-one close gate"}
    >
      <div className={styles.phaseCloseGateHeader}>
        <div>
          <strong>{isZh ? "第一阶段闭环门" : "Phase-one close gate"}</strong>
          <span>{gateSummaryCopy(gate, loading, lang)}</span>
        </div>
        <span className={`${styles.phaseCloseGateTag} ${gateTone(gate?.status)}`}>
          {gate?.passed ? <CheckCircle2 size={13} aria-hidden /> : null}
          {gateStatusCopy(gate?.status, lang)}
        </span>
      </div>
      <div className={styles.phaseCloseGateFacts}>
        <span>{isZh ? "当前批次" : "Run"} <strong>{selectedRunId || (isZh ? "未选择" : "not selected")}</strong></span>
        <span>{isZh ? "阶段闭环" : "Stages"} <strong>{gate ? `${closedLoopCount}/${stageCount}` : "—"}</strong></span>
        {gate?.stageRoundStatus ? (
          <span>{isZh ? "轮次状态" : "Round"} <strong>{gate.stageRoundStatus}</strong></span>
        ) : null}
      </div>
      {reasons.length ? (
        <div className={styles.phaseCloseGateReasons}>
          {reasons.map((reason) => <span key={reason}>{reason}</span>)}
        </div>
      ) : null}
      {nextStage && gate?.status === "needs_continue" ? (
        <VNativeButton
          type="button"
          className={styles.phaseCloseGateAction}
          title={isZh ? `切换到${stageLabel(nextStage, lang)}，再使用该阶段既有操作继续。` : `Open ${stageLabel(nextStage, lang)} and use its existing action.`}
          onClick={() => onOpenStage(nextStage)}
        >
          {isZh ? `定位到${stageLabel(nextStage, lang)}` : `Open ${stageLabel(nextStage, lang)}`}
          <ArrowRight size={13} aria-hidden />
        </VNativeButton>
      ) : null}
    </section>
  );
}
