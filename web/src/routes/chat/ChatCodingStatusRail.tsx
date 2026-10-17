import type { Dispatch, SetStateAction } from "react";

import type { SessionDetail, VirtualHumanCompanion } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { FinancialAssistantChatNote } from "../finance/FinancialAssistantChatNote";
import { CompanionLifeRail } from "../companions/CompanionLifeRail";
import type { CompanionRailState } from "../companions/CompanionPersonRail";
import { ChatRightRail, type ChatRightRailPaneDock } from "./ChatRightRail";
import type { ChatRightRailModel } from "./chatRightRailModel";
import type { ChatChangeRailModel } from "./chatChangeRailModel";
import type { CliAgentRunView, CliAgentTerminalSession } from "./cliAgentRunModel";
import type { ChatRouteNavigateOptions } from "./useChatRouteSelection";
import { useChatChangePreview } from "./useChatChangePreview";
import { useChatGitRail } from "./useChatGitRail";

type ReviewPick = { sessionId: string; source: "session" | "git"; path: string };

/**
 * Right column of the coding workbench: companion life rail, or the ordinary
 * change/review rail. Extracted without changing which surface is shown.
 */
export function ChatCodingStatusRail({
  activeCliAgentRun,
  activeCompanion,
  activeGroupRoomId,
  activeSessionId,
  changePreview,
  changeRail,
  changeRailOpened,
  changedPathSet,
  cliAgentRunTabs,
  companionRailError,
  companionRailState,
  describeError,
  detail,
  gitRail,
  gitReviewPath,
  groupPanelActive,
  handleCliAgentTerminalSessionChange,
  lang,
  openPreviewTab,
  openSession,
  ordinaryChangeRail,
  railModel,
  reviewSource,
  sessionReviewPath,
  setReviewPick,
  statusRailClassName,
  statusRailCollapsed,
  statusRailOverlayOpen,
  onCollapseStatusRail,
  t,
  toggleChangeRail,
  updateRailModel,
  verifiedCompanionMode,
  paneDock,
  hideTabList = false,
}: {
  activeCliAgentRun: CliAgentRunView | undefined;
  activeCompanion: VirtualHumanCompanion | null;
  activeGroupRoomId: string;
  activeSessionId: string | null;
  changePreview: ReturnType<typeof useChatChangePreview>;
  changeRail: ChatChangeRailModel;
  changeRailOpened: boolean;
  changedPathSet: ReadonlySet<string>;
  cliAgentRunTabs: CliAgentRunView[];
  companionRailError: string;
  companionRailState: CompanionRailState;
  describeError: (error: unknown, fallback: string) => string;
  detail: SessionDetail | null | undefined;
  gitRail: ReturnType<typeof useChatGitRail>;
  gitReviewPath: string | null;
  groupPanelActive: boolean;
  handleCliAgentTerminalSessionChange: (runId: string, session: CliAgentTerminalSession) => void;
  lang: "zh" | "en";
  openPreviewTab: (sessionId: string, path: string) => void;
  openSession: (sessionId: string, options?: ChatRouteNavigateOptions) => void;
  ordinaryChangeRail: boolean;
  railModel: ChatRightRailModel;
  reviewSource: "session" | "git";
  sessionReviewPath: string | null;
  setReviewPick: Dispatch<SetStateAction<ReviewPick | null>>;
  statusRailClassName: string;
  statusRailCollapsed: boolean;
  statusRailOverlayOpen: boolean;
  onCollapseStatusRail: () => void;
  t: (key: TranslationKey) => string;
  toggleChangeRail: () => void;
  updateRailModel: (update: ChatRightRailModel | ((current: ChatRightRailModel) => ChatRightRailModel)) => void;
  verifiedCompanionMode: boolean;
  paneDock?: ChatRightRailPaneDock;
  hideTabList?: boolean;
}) {
  if (verifiedCompanionMode) {
    return (
      <CompanionLifeRail
        className={statusRailClassName}
        collapsed={statusRailCollapsed}
        overlayOpen={statusRailOverlayOpen}
        companion={activeCompanion}
        state={companionRailState}
        errorMessage={companionRailError}
        lang={lang}
        onCollapse={onCollapseStatusRail}
        onOpenLifeSteward={(stewardSessionId) => {
          openSession(stewardSessionId, {
            replace: false,
            telemetrySource: "virtual_human_life_steward",
          });
        }}
      />
    );
  }
  if (!(ordinaryChangeRail && (changeRail.show || changeRailOpened))) {
    return null;
  }
  return (
      <ChatRightRail
        className={statusRailClassName}
        lang={lang}
        sessionId={groupPanelActive ? "" : (activeSessionId ?? "")}
        sessionKind={groupPanelActive ? "group" : detail?.sessionKind}
        model={railModel}
        onModelChange={updateRailModel}
        paneDock={paneDock}
        hideTabList={hideTabList}
        onOpenSession={(id) => openSession(id, { telemetrySource: "right_rail_project" })}
        onCollapse={toggleChangeRail}
        devtools={detail ? {
          phase: detail.currentPhase,
          status: detail.status,
          messages: detail.messages,
        } : null}
        terminalRun={activeCliAgentRun ?? cliAgentRunTabs[0] ?? null}
        terminalMountedInCenter={Boolean(activeCliAgentRun)}
        onTerminalSessionChange={handleCliAgentTerminalSessionChange}
        onOpenFile={(path) => {
          if (activeSessionId) {
            openPreviewTab(activeSessionId, path);
          }
        }}
        preface={groupPanelActive ? null : <FinancialAssistantChatNote sessionId={activeSessionId} lang={lang} />}
        review={{
          sessionTitle: lang === "zh" ? "这次对话" : "This chat",
          sessionEmptyLabel: lang === "zh" ? "这次对话还没有改动文件" : "This chat has no changed files yet",
          sessionPaths: changeRail.paths,
          sessionSelectedPath: reviewSource === "git" ? null : sessionReviewPath,
          sessionChangedPaths: changedPathSet,
          gitTitle: gitRail.branch
            ? (lang === "zh" ? `仓库 · ${gitRail.branch}` : `Repository · ${gitRail.branch}`)
            : (lang === "zh" ? "仓库" : "Repository"),
          gitEmptyLabel: lang === "zh" ? "工作区是干净的" : "The worktree is clean",
          gitPending: gitRail.pending,
          gitPendingLabel: lang === "zh" ? "正在读取仓库" : "Reading the repository",
          gitUnavailableLabel: gitRail.unavailable
            ? (gitRail.errorText || describeError(gitRail.error, t("loadFailed")))
            : "",
          gitPaths: gitRail.paths,
          gitSelectedPath: gitReviewPath,
          gitDetailByPath: gitRail.detailByPath,
          diff: changePreview.diff,
          diffLoading: changePreview.diffLoading,
          hasDiff: changePreview.hasDiff,
          file: changePreview.file,
          fileLoading: changePreview.fileLoading,
          fileError: changePreview.fileError ? describeError(changePreview.fileError, t("loadFailed")) : "",
          sourceLabel: detail?.title ?? t("currentSession"),
          onSelectSessionFile: (path) => {
            if (!activeSessionId) {
              return;
            }
            setReviewPick({ sessionId: activeSessionId, source: "session", path });
            openPreviewTab(activeSessionId, path);
          },
          onSelectGitFile: (path) => {
            const reviewKey = groupPanelActive ? `group:${activeGroupRoomId}` : activeSessionId;
            if (!reviewKey) {
              return;
            }
            gitRail.selectPath(path);
            setReviewPick({ sessionId: reviewKey, source: "git", path });
          },
        }}
      />
  );
}
