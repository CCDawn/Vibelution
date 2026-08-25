/**
 * Shared full-page workbench chrome for research stages.
 * No team left-rail — only overview board mounts TeamShellRail.
 */
import type { ReactNode } from "react";
import { ArrowLeft, RefreshCw, Users } from "lucide-react";
import { Link } from "react-router-dom";

import { VButton, VNativeButton, VStatusChip } from "../../components/vui";
import { RESEARCH_STAGE_TERMS } from "./research-workflow/researchTerminology";
import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import type { ResearchStageUnlock } from "./researchPrimaryActionModel";
import {
  researchSourceCollectionRoute,
  researchWorkspaceStageRoute,
  teamWorkspaceRoute,
  type ResearchStageWorkspaceView,
  type ResearchWorkspaceView,
} from "./researchWorkspaceModel";
import { ResearchStageNav } from "./ResearchStageNav";
import { teamChatRoomRoute } from "./researchStageAgentPresentation";
import researchStyles from "../TeamsRoute.research.styles";
import shellStyles from "../TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

export type ResearchStageWorkbenchShellProps = {
  lang: "zh" | "en";
  current: ResearchStageWorkspaceView;
  title: ReactNode;
  statusBadge?: ReactNode;
  statusBadgeClassName?: string;
  unlock: ResearchStageUnlock;
  onSelectStage: (view: ResearchStageWorkspaceView) => void;
  onOverview: () => void;
  teamId?: string;
  linkedChatRoomId?: string;
  onSyncChat?: () => void;
  chatSyncPending?: boolean;
  chatSyncDisabled?: boolean;
  backHref?: string;
  backLabel?: string;
  chatBackLabel?: string;
  onRefresh?: () => void;
  refreshDisabled?: boolean;
  extraActions?: ReactNode;
  children: ReactNode;
  testId?: string;
  className?: string;
  dataAttrs?: Record<string, string | undefined>;
};

export function ResearchStageWorkbenchShell({
  lang,
  current,
  title,
  statusBadge,
  statusBadgeClassName,
  unlock,
  onSelectStage,
  onOverview,
  teamId,
  linkedChatRoomId,
  onSyncChat,
  chatSyncPending = false,
  chatSyncDisabled = false,
  backHref,
  backLabel,
  chatBackLabel,
  onRefresh,
  refreshDisabled = false,
  extraActions,
  children,
  testId = "research-stage-workbench",
  className = "",
  dataAttrs,
}: ResearchStageWorkbenchShellProps) {
  const effectiveTeamId = teamId || RESEARCH_TEAM_ID;
  // Same destination as initial team home (flow + canvas), never board kanban wall.
  const overviewHref = backHref || teamWorkspaceRoute(effectiveTeamId);
  const resolvedBackLabel = backLabel ?? (lang === "zh" ? "返回团队首页" : "Back to team home");
  const stageChatReturn =
    current === "knowledge_collection"
      ? researchSourceCollectionRoute(effectiveTeamId)
      : researchWorkspaceStageRoute(effectiveTeamId, current);
  const resolvedChatBack =
    chatBackLabel
    ?? (current === "knowledge_collection"
      ? (lang === "zh" ? `返回${RESEARCH_STAGE_TERMS.knowledge_collection.zh}` : "Back to knowledge collection")
      : (lang === "zh" ? "返回阶段页" : "Back to stage"));

  const dataAttrProps = Object.fromEntries(
    Object.entries(dataAttrs || {})
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k.startsWith("data-") ? k : `data-${k}`, v]),
  );

  return (
    <section
      className={[styles.route, styles.sourceCollectionPage, className].filter(Boolean).join(" ")}
      data-testid={testId}
      data-product-workbench="true"
      data-research-stage-view={current}
      data-team-rail="hidden"
      {...dataAttrProps}
    >
      <header className={`${styles.header} ${styles.sourceCollectionPageHeader}`}>
        <div className={styles.sourceCollectionPageTitleBlock}>
          <div className={styles.sourceCollectionPageTitleLine}>
            <h1>{title}</h1>
            {statusBadge != null && statusBadge !== "" ? (
              <VStatusChip tone="neutral" className={statusBadgeClassName || styles.sourceCollectionRunBadge}>
                {statusBadge}
              </VStatusChip>
            ) : null}
          </div>
          <ResearchStageNav
            lang={lang}
            current={current}
            unlock={unlock}
            onSelect={onSelectStage}
            onOverview={onOverview}
          />
        </div>
        <div className={styles.sourceCollectionPageActions}>
          {linkedChatRoomId ? (
            <Link to={teamChatRoomRoute(linkedChatRoomId, stageChatReturn, resolvedChatBack)}>
              <Users size={14} />
              {lang === "zh" ? "团队讨论" : "Team discussion"}
            </Link>
          ) : onSyncChat ? (
            <VButton
              type="button"
              density="compact"
              variant="secondary"
              icon={<Users size={14} />}
              onPress={onSyncChat}
              isDisabled={chatSyncDisabled || chatSyncPending}
            >
              {chatSyncPending
                ? (lang === "zh" ? "同步中" : "Syncing")
                : (lang === "zh" ? "同步讨论" : "Sync chat")}
            </VButton>
          ) : null}
          <Link to={overviewHref}>
            <ArrowLeft size={14} />
            {resolvedBackLabel}
          </Link>
          {onRefresh ? (
            <VNativeButton type="button" onClick={onRefresh} disabled={refreshDisabled}>
              <RefreshCw size={14} />
              {lang === "zh" ? "刷新" : "Refresh"}
            </VNativeButton>
          ) : null}
          {extraActions}
        </div>
      </header>
      {children}
    </section>
  );
}

export type { ResearchWorkspaceView };
