/**
 * Knowledge-collection full-page composer (no team rail).
 */
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import type { ResearchStageUnlock } from "./researchPrimaryActionModel";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import { teamWorkspaceRoute } from "./researchWorkspaceModel";
import { ResearchStageWorkbenchShell } from "./ResearchStageWorkbenchShell";
import {
  TeamSourceCollectionStandaloneStagePanel,
  type TeamSourceCollectionStandaloneStageModule,
} from "./source-collection/ui/TeamSourceCollectionStandaloneStagePanel";
import shellStyles from "../TeamsRoute.styles";
import researchStyles from "../TeamsRoute.research.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

export type SourceCollectionComposerProps = {
  lang: "zh" | "en";
  unlock: ResearchStageUnlock;
  onSelectStage: (view: ResearchWorkspaceView) => void;
  onOverview: () => void;
  teamId?: string;
  linkedChatRoomId?: string;
  onSyncChat?: () => void;
  chatSyncPending?: boolean;
  chatSyncDisabled?: boolean;
  onRefresh: () => void;
  refreshDisabled?: boolean;
  statusBadge: ReactNode;
  statusBadgeClassName?: string;
  ready: boolean;
  loadingTitle?: ReactNode;
  loadingMessage?: ReactNode;
  unavailableTitle?: ReactNode;
  unavailableDetail?: ReactNode;
  commandAriaLabel: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  commandTone: any;
  commandTitle: ReactNode;
  commandSubtitle: ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  commandStats: any[];
  searchBrief: ReactNode;
  runSwitcher: ReactNode;
  runHistoryLabel: string;
  phaseCloseGate: ReactNode;
  modules: TeamSourceCollectionStandaloneStageModule[];
  activePanel: ReactNode;
  compactActivePanel?: boolean;
  /** Default command-bar: stage progress only top-right (no left 01–04 stack). */
  progressPlacement?: "command-bar" | "left-rail";
};

export function SourceCollectionComposer(props: SourceCollectionComposerProps) {
  const {
    lang,
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
    statusBadge,
    statusBadgeClassName,
    ready,
    loadingTitle,
    loadingMessage,
    unavailableTitle,
    unavailableDetail,
    commandAriaLabel,
    commandTone,
    commandTitle,
    commandSubtitle,
    commandStats,
    searchBrief,
    runSwitcher,
    runHistoryLabel,
    phaseCloseGate,
    modules,
    activePanel,
    compactActivePanel,
    progressPlacement = "command-bar",
  } = props;

  const effectiveTeamId = teamId || RESEARCH_TEAM_ID;

  return (
    <ResearchStageWorkbenchShell
      lang={lang}
      current="knowledge_collection"
      title={lang === "zh" ? "知识搜集工作台" : "Knowledge collection workspace"}
      statusBadge={statusBadge}
      statusBadgeClassName={statusBadgeClassName}
      unlock={unlock}
      onSelectStage={onSelectStage}
      onOverview={onOverview}
      teamId={effectiveTeamId}
      linkedChatRoomId={linkedChatRoomId}
      onSyncChat={onSyncChat}
      chatSyncPending={chatSyncPending}
      chatSyncDisabled={chatSyncDisabled}
      onRefresh={onRefresh}
      refreshDisabled={refreshDisabled}
      backHref={teamWorkspaceRoute(effectiveTeamId)}
      backLabel={lang === "zh" ? "返回团队页面" : "Back to team"}
      testId="source-collection-composer"
      dataAttrs={{ composer: "source-collection" }}
    >
      {ready ? (
        <TeamSourceCollectionStandaloneStagePanel
          commandAriaLabel={commandAriaLabel}
          commandTone={commandTone}
          commandTitle={commandTitle}
          commandSubtitle={commandSubtitle}
          commandStats={commandStats}
          searchBrief={searchBrief}
          runSwitcher={runSwitcher}
          runHistoryLabel={runHistoryLabel}
          phaseCloseGate={phaseCloseGate}
          stagePipelineId="source-collection-stage-status"
          stagePipelineAriaLabel={lang === "zh" ? "知识搜集内部模块" : "Knowledge collection modules"}
          modules={modules}
          activePanel={activePanel}
          compactActivePanel={compactActivePanel}
          progressPlacement={progressPlacement}
        />
      ) : (
        <main className={styles.sourceCollectionPageBody}>
          <section className={styles.sourceCollectionUnavailable}>
            <strong>{unavailableTitle || loadingTitle}</strong>
            <span>{unavailableDetail || loadingMessage}</span>
            <Link to={teamWorkspaceRoute(RESEARCH_TEAM_ID)}>
              <ArrowLeft size={14} />
              {lang === "zh" ? "返回团队页面" : "Back to team"}
            </Link>
          </section>
        </main>
      )}
    </ResearchStageWorkbenchShell>
  );
}
