/**
 * Experiment / iteration full-page composer (no team rail).
 */
import type { ReactNode } from "react";

import type { ExperimentPlanningStatusPayload } from "./experimentLoopModel";
import type { ResearchStageUnlock } from "./researchPrimaryActionModel";
import type { ResearchStageWorkspaceView } from "./researchWorkspaceModel";
import { ResearchStageWorkbenchShell } from "./ResearchStageWorkbenchShell";
import researchStyles from "../TeamsRoute.research.styles";
import shellStyles from "../TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

export type ExperimentStageComposerProps = {
  lang: "zh" | "en";
  stageView: "experiment" | "iteration";
  unlock: ResearchStageUnlock;
  onSelectStage: (view: ResearchStageWorkspaceView) => void;
  onOverview: () => void;
  teamId?: string;
  linkedChatRoomId?: string;
  onSyncChat?: () => void;
  chatSyncPending?: boolean;
  chatSyncDisabled?: boolean;
  onRefresh: () => void;
  refreshDisabled?: boolean;
  experimentPlanningStatus?: ExperimentPlanningStatusPayload | null;
  statusLoading?: boolean;
  body: ReactNode;
  embeddedInBoard?: boolean;
};

export function ExperimentStageComposer(props: ExperimentStageComposerProps) {
  const {
    lang,
    stageView,
    unlock,
    onSelectStage,
    onOverview,
    teamId,
    linkedChatRoomId,
    onSyncChat,
    chatSyncPending,
    chatSyncDisabled,
    onRefresh,
    refreshDisabled,
    experimentPlanningStatus,
    statusLoading = false,
    body,
    embeddedInBoard = false,
  } = props;

  const title = stageView === "experiment"
    ? (lang === "zh" ? "实验规划工作台" : "Experiment planning workspace")
    : (lang === "zh" ? "迭代优化工作台" : "Iteration workspace");

  const statusText = statusLoading
    ? (lang === "zh" ? "读取中" : "Loading")
    : (experimentPlanningStatus?.activePlan
      ? (lang === "zh" ? "有计划" : "Plan ready")
      : (lang === "zh" ? "待配置" : "Not set up"));

  return (
    <ResearchStageWorkbenchShell
      lang={lang}
      current={stageView}
      title={title}
      statusBadge={statusText}
      unlock={unlock}
      onSelectStage={onSelectStage}
      onOverview={onOverview}
      teamId={teamId}
      linkedChatRoomId={linkedChatRoomId}
      onSyncChat={onSyncChat}
      chatSyncPending={chatSyncPending}
      chatSyncDisabled={chatSyncDisabled}
      onRefresh={onRefresh}
      refreshDisabled={refreshDisabled}
      testId="research-stage-standalone-page"
      className={[
        styles.researchStagePage,
        embeddedInBoard ? styles.researchStagePageEmbedded : "",
      ].filter(Boolean).join(" ")}
      dataAttrs={{
        fill: embeddedInBoard ? "true" : undefined,
        composer: stageView,
        "research-stage-detail-status": statusText,
      }}
    >
      <main className={styles.researchStagePageBody} data-testid="research-stage-workbench-body">
        {body}
      </main>
    </ResearchStageWorkbenchShell>
  );
}

export function IterationStageComposer(
  props: Omit<ExperimentStageComposerProps, "stageView">,
) {
  return <ExperimentStageComposer {...props} stageView="iteration" />;
}
