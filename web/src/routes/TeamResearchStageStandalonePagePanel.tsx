/**
 * Research stage standalone page (experiment / iteration workspaces).
 * Product shell: stage nav + workbench body only (no team rail, no dump walls).
 */
import type { ReactNode } from "react";
import { ArrowLeft, RefreshCw, Users } from "lucide-react";
import { Link } from "react-router-dom";

import type { Team } from "../api/types";
import { VButton, VNativeButton } from "../components/vui";
import {
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
} from "./teams/experimentLoopModel";
import { RESEARCH_TEAM_ID } from "./TeamsRoute.canvasData";
import {
  researchWorkspaceStageRoute,
  teamWorkspaceRoute,
  type ResearchStageWorkspaceView,
} from "./teams/researchWorkspaceModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageType,
} from "./teams/source-collection/stageProjection";
import type { ResearchStageUnlock } from "./teams/researchPrimaryActionModel";
import { ResearchStageNav } from "./teams/ResearchStageNav";
import { teamChatRoomRoute } from "./teams/researchStageAgentPresentation";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

type Lang = "zh" | "en";
type StageView = Exclude<ResearchStageWorkspaceView, "knowledge_collection">;

export type TeamResearchStageStandalonePagePanelProps = {
  stageView: StageView;
  lang: Lang;
  researchStagePhases: ResearchStagePhaseStatus[];
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  experimentPlanningStatusQuery: { isPending: boolean; isFetching: boolean };
  selectedTeam: Team | null | undefined;
  selectedTeamStartResearchStagePending: boolean;
  linkedChatRoomId: string;
  syncTeamChatRoomMutation: { mutate: (teamId: string) => void };
  activeTeamMemberCount: number;
  selectedTeamSyncPending: boolean;
  researchStageRoundStatusQuery: { isFetching: boolean; refetch: () => unknown };
  refreshStageWorkspace: () => void;
  renderResearchStageAgentPanel: (stageType: ResearchStageType, variant?: "compact" | "page") => ReactNode;
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
  selectedTeamStartResearchStageError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamStartResearchStageResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  researchStageStartFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
  renderExperimentPlanningLedgerPanel: () => ReactNode;
  renderResearchLoopPanel: (activePlan: ExperimentPlanRecord | null, variant?: "experiment" | "iteration") => ReactNode;
  researchStageUnlock?: ResearchStageUnlock;
  onSelectResearchStage?: (view: ResearchStageWorkspaceView) => void;
  onBackToOverview?: () => void;
  /**
   * When true, page is embedded in Teams board shell.
   * Product path uses standalone full page (false) so left team rail is gone.
   */
  embeddedInBoard?: boolean;
};

export function TeamResearchStageStandalonePagePanel(props: TeamResearchStageStandalonePagePanelProps) {
  const {
    stageView,
    lang,
    experimentPlanningStatus,
    experimentPlanningStatusQuery,
    selectedTeam,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    researchStageRoundStatusQuery,
    refreshStageWorkspace,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
    researchStageUnlock,
    onSelectResearchStage,
    onBackToOverview,
    embeddedInBoard = false,
  } = props;

  const title = stageView === "experiment"
    ? (lang === "zh" ? "实验规划工作台" : "Experiment planning workspace")
    : (lang === "zh" ? "迭代优化工作台" : "Iteration workspace");
  const statusLoading = !experimentPlanningStatus && experimentPlanningStatusQuery.isPending;
  const statusText = statusLoading
    ? (lang === "zh" ? "读取中" : "Loading")
    : (experimentPlanningStatus?.activePlan
      ? (lang === "zh" ? "有计划" : "Plan ready")
      : (lang === "zh" ? "待配置" : "Not set up"));

  return (
    <section
      className={[
        styles.researchStagePage,
        styles.route,
        styles.sourceCollectionPage,
        embeddedInBoard ? styles.researchStagePageEmbedded : "",
      ].filter(Boolean).join(" ")}
      data-fill={embeddedInBoard ? "true" : undefined}
      data-research-stage-view={stageView}
      data-testid="research-stage-standalone-page"
      data-product-workbench="true"
    >
      <header className={`${styles.header} ${styles.sourceCollectionPageHeader}`}>
        <div className={styles.sourceCollectionPageTitleBlock}>
          <div className={styles.sourceCollectionPageTitleLine}>
            <h1>{title}</h1>
            <span className={styles.sourceCollectionRunBadge} data-research-stage-detail-status={statusText}>
              {statusText}
            </span>
          </div>
          {researchStageUnlock && onSelectResearchStage ? (
            <ResearchStageNav
              lang={lang}
              current={stageView}
              unlock={researchStageUnlock}
              onSelect={onSelectResearchStage}
              onOverview={onBackToOverview}
            />
          ) : null}
        </div>
        <div className={styles.sourceCollectionPageActions}>
          {linkedChatRoomId ? (
            <Link
              to={teamChatRoomRoute(
                linkedChatRoomId,
                researchWorkspaceStageRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID, stageView),
                lang === "zh" ? "返回阶段页" : "Back to stage",
              )}
            >
              <Users size={14} />
              {lang === "zh" ? "团队讨论" : "Team discussion"}
            </Link>
          ) : (
            <VButton
              type="button"
              density="compact"
              variant="secondary"
              icon={<Users size={14} />}
              onPress={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
              isDisabled={!selectedTeam || activeTeamMemberCount === 0 || selectedTeamSyncPending}
            >
              {selectedTeamSyncPending
                ? (lang === "zh" ? "同步中" : "Syncing")
                : (lang === "zh" ? "同步讨论" : "Sync chat")}
            </VButton>
          )}
          <Link
            to={
              onBackToOverview
                ? `/teams?team=${encodeURIComponent(selectedTeam?.teamId || RESEARCH_TEAM_ID)}&researchView=overview&teamMode=board`
                : teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)
            }
          >
            <ArrowLeft size={14} />
            {lang === "zh" ? "返回科研总览" : "Back to overview"}
          </Link>
          <VNativeButton
            type="button"
            onClick={refreshStageWorkspace}
            disabled={researchStageRoundStatusQuery.isFetching || experimentPlanningStatusQuery.isFetching}
          >
            <RefreshCw size={14} />
            {lang === "zh" ? "刷新" : "Refresh"}
          </VNativeButton>
        </div>
      </header>
      <main
        className={styles.researchStagePageBody}
        data-testid="research-stage-workbench-body"
      >
        {stageView === "experiment" ? renderExperimentPlanningLedgerPanel() : null}
        {stageView === "iteration"
          ? renderResearchLoopPanel(experimentPlanningStatus?.activePlan ?? null, "iteration")
          : null}
      </main>
    </section>
  );
}
