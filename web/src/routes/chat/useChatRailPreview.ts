import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchFileContent } from "../../api/files";
import { queryKeys } from "../../api/queryKeys";
import { buildChatChangeRail } from "./chatChangeRailModel";
import { useProjectAwareRightRail } from "./useProjectAwareRightRail";
import {
  activeChatRightRailTab,
  EMPTY_CHAT_RIGHT_RAIL,
  noteReviewAutoOpen,
  type ChatRightRailModel,
} from "./chatRightRailModel";
import { useChatChangePreview } from "./useChatChangePreview";
import { useChatGitRail } from "./useChatGitRail";

export type ChatRailPreviewInput = {
  activeSessionId: string | null | undefined;
  /** Center workspace file tab target; empty when the agent tab is active. */
  activeFilePath: string | null;
  workspace: {
    openTabs: string[];
    activeTab: string;
  };
  changedFileList: string[];
  ordinaryChangeRail: boolean;
  companion: boolean;
  finance: boolean;
  group: boolean;
};

/**
 * Right-rail preview state: the per-session rail models, review selection,
 * change rail derivation, git rail and the auto-open effect. Extracted from
 * ChatCodingRouteWorkbench with identical behavior.
 */
export function useChatRailPreview({
  activeSessionId,
  activeFilePath,
  workspace,
  changedFileList,
  ordinaryChangeRail,
  companion,
  finance,
  group,
}: ChatRailPreviewInput) {
  const fileContentQuery = useQuery({
    queryKey: queryKeys.fileContent(activeFilePath ?? ""),
    enabled: Boolean(activeFilePath),
    queryFn: () => fetchFileContent(activeFilePath ?? ""),
  });

  const [changeRailOpened, setChangeRailOpened] = useState(false);
  const [reviewPick, setReviewPick] = useState<{ sessionId: string; source: "session" | "git"; path: string } | null>(null);
  // Project-aware rail state keeps the project utility tabs composed into the
  // per-session rail models (main-line behavior the extraction must preserve).
  const { railsBySession, setRailsBySession, railModel, updateRailModel, project } = useProjectAwareRightRail(activeSessionId ?? null);
  const activeRailTab = activeChatRightRailTab(railModel);
  const changeRail = useMemo(
    () => buildChatChangeRail({
      companion,
      finance,
      group,
      changedFiles: changedFileList,
      openTabs: workspace.openTabs,
      activeTab: workspace.activeTab,
    }),
    [
      companion,
      finance,
      group,
      changedFileList,
      workspace.openTabs,
      workspace.activeTab,
    ],
  );
  const gitRail = useChatGitRail(
    ordinaryChangeRail && activeRailTab?.kind === "review" && (changeRail.show || changeRailOpened),
  );
  const reviewPickForSession = reviewPick && reviewPick.sessionId === activeSessionId ? reviewPick : null;
  const reviewSource = reviewPickForSession?.source ?? "session";
  const sessionReviewPath = reviewSource === "session" && reviewPickForSession && changeRail.paths.includes(reviewPickForSession.path)
    ? reviewPickForSession.path
    : changeRail.selectedPath;
  const gitReviewPath = reviewSource === "git" && reviewPickForSession && gitRail.paths.includes(reviewPickForSession.path)
    ? reviewPickForSession.path
    : null;
  const changePreview = useChatChangePreview(
    activeRailTab?.kind === "review"
      ? (reviewSource === "git" ? gitReviewPath : sessionReviewPath)
      : null,
  );
  useEffect(() => {
    if (!ordinaryChangeRail || !activeSessionId || !changeRail.show) {
      return;
    }
    const sessionId = activeSessionId;
    setRailsBySession((current) => {
      const model = current[sessionId] ?? EMPTY_CHAT_RIGHT_RAIL;
      const noted = noteReviewAutoOpen(model, "审查");
      if (noted.model === model) {
        return current;
      }
      return { ...current, [sessionId]: noted.model };
    });
  }, [activeSessionId, changeRail.show, ordinaryChangeRail]);

  return {
    fileContentQuery,
    changeRail,
    changeRailOpened,
    setChangeRailOpened,
    railsBySession,
    setRailsBySession,
    railModel,
    activeRailTab,
    updateRailModel,
    project,
    gitRail,
    reviewSource,
    sessionReviewPath,
    gitReviewPath,
    setReviewPick,
    changePreview,
  };
}
