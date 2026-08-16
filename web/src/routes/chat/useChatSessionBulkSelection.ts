import { useCallback, useMemo, useState } from "react";
import type { UseMutationResult } from "@tanstack/react-query";

import type { ConversationSummary, SessionBulkDeleteResponse, SessionSummary } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  collectDirectSessionIdsFromConversations,
  sessionBulkActionItemNote,
  sessionBulkActionSummary,
  sessionBulkDeletable,
} from "./chatSessionBulkModel";

export type SessionBulkNotice = { tone: "error" | "success"; text: string };

export type UseChatSessionBulkSelectionInput = {
  filteredConversations: readonly ConversationSummary[];
  sessionsById: Map<string, SessionSummary>;
  bulkDeleteSessionsMutation: UseMutationResult<
    SessionBulkDeleteResponse,
    Error,
    { sessionIds: string[] },
    unknown
  >;
  isBusyPhase: (value: string | null | undefined) => boolean;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
};

export type UseChatSessionBulkSelectionResult = {
  selectedBulkSessionIds: Set<string>;
  selectedBulkSessions: string[];
  allVisibleSessionsSelected: boolean;
  bulkSessionPending: boolean;
  sessionBulkNotice: SessionBulkNotice | null;
  sessionBulkCopy: {
    bulkSelected: string;
    bulkClear: string;
    bulkSelectVisible: string;
    bulkRemove: string;
    bulkWorking: string;
    bulkRemoveConfirm: string;
    cancelCreate: string;
  };
  clearBulkSessions: () => void;
  selectVisibleBulkSessions: () => void;
  toggleBulkSession: (sessionId: string, selected: boolean, extendRange?: boolean) => void;
  bulkRemoveSessions: () => Promise<void>;
  visibleDirectSessionIds: string[];
};

export function useChatSessionBulkSelection({
  filteredConversations,
  sessionsById,
  bulkDeleteSessionsMutation,
  isBusyPhase,
  lang,
  t,
}: UseChatSessionBulkSelectionInput): UseChatSessionBulkSelectionResult {
  const [selectedBulkSessionIds, setSelectedBulkSessionIds] = useState<Set<string>>(() => new Set());
  const [bulkSessionSelectionAnchorId, setBulkSessionSelectionAnchorId] = useState("");
  const [sessionBulkNotice, setSessionBulkNotice] = useState<SessionBulkNotice | null>(null);

  const visibleDirectSessionIds = useMemo(
    () => collectDirectSessionIdsFromConversations(filteredConversations, sessionsById),
    [filteredConversations, sessionsById],
  );
  const selectedBulkSessions = useMemo(
    () => visibleDirectSessionIds.filter((sessionId) => selectedBulkSessionIds.has(sessionId)),
    [selectedBulkSessionIds, visibleDirectSessionIds],
  );
  const allVisibleSessionsSelected = visibleDirectSessionIds.length > 0
    && selectedBulkSessions.length === visibleDirectSessionIds.length;
  const bulkSessionPending = bulkDeleteSessionsMutation.isPending;
  const sessionBulkCopy = useMemo(() => ({
    bulkSelected: t("bulkSelectedSessions"),
    bulkClear: t("bulkClearSessionSelection"),
    bulkSelectVisible: t("bulkSelectVisibleSessions"),
    bulkRemove: t("bulkRemoveSessions"),
    bulkWorking: t("bulkSessionWorking"),
    bulkRemoveConfirm: t("bulkRemoveSessionsConfirm"),
    cancelCreate: lang === "zh" ? "取消" : "Cancel",
  }), [lang, t]);

  const clearBulkSessions = useCallback(() => {
    setSelectedBulkSessionIds(new Set());
    setBulkSessionSelectionAnchorId("");
  }, []);

  const selectVisibleBulkSessions = useCallback(() => {
    setSelectedBulkSessionIds(new Set(visibleDirectSessionIds));
    setBulkSessionSelectionAnchorId(visibleDirectSessionIds[0] ?? "");
  }, [visibleDirectSessionIds]);

  const toggleBulkSession = useCallback((
    sessionId: string,
    selected: boolean,
    extendRange = false,
  ) => {
    setSelectedBulkSessionIds((current) => {
      const next = new Set(current);
      if (extendRange && bulkSessionSelectionAnchorId) {
        const anchorIndex = visibleDirectSessionIds.indexOf(bulkSessionSelectionAnchorId);
        const targetIndex = visibleDirectSessionIds.indexOf(sessionId);
        if (anchorIndex >= 0 && targetIndex >= 0) {
          const [start, end] = anchorIndex < targetIndex
            ? [anchorIndex, targetIndex]
            : [targetIndex, anchorIndex];
          visibleDirectSessionIds.slice(start, end + 1).forEach((id) => next.add(id));
          return next;
        }
      }
      if (selected) {
        next.add(sessionId);
      } else {
        next.delete(sessionId);
      }
      return next;
    });
    setBulkSessionSelectionAnchorId(sessionId);
  }, [bulkSessionSelectionAnchorId, visibleDirectSessionIds]);

  const bulkRemoveSessions = useCallback(async () => {
    if (bulkSessionPending) {
      return;
    }
    if (!selectedBulkSessions.length) {
      setSessionBulkNotice({ tone: "error", text: t("bulkNoSessionSelection") });
      return;
    }
    const busySessions = selectedBulkSessions.filter((sessionId) => {
      const session = sessionsById.get(sessionId);
      return session ? !sessionBulkDeletable(session, isBusyPhase) : false;
    });
    const removableSessions = selectedBulkSessions.filter((sessionId) => {
      const session = sessionsById.get(sessionId);
      return session ? sessionBulkDeletable(session, isBusyPhase) : true;
    });
    const notes: string[] = [];
    busySessions.forEach((sessionId) => {
      const session = sessionsById.get(sessionId);
      const title = String(session?.title || session?.agentDisplayName || sessionId).trim();
      notes.push(`${title}: ${t("deleteSessionBusy")}`);
    });
    let success = 0;
    let skipped = busySessions.length;
    let failed = 0;
    if (removableSessions.length) {
      try {
        const response = await bulkDeleteSessionsMutation.mutateAsync({ sessionIds: removableSessions });
        response.skipped.forEach((item) => {
          notes.push(sessionBulkActionItemNote(item, sessionsById, t("deleteSessionBusy")));
        });
        response.failed.forEach((item) => {
          notes.push(sessionBulkActionItemNote(item, sessionsById, ""));
        });
        success += response.summary.successCount;
        skipped += response.summary.skippedCount;
        failed += response.summary.failedCount;
      } catch (error) {
        failed += removableSessions.length;
        notes.push(error instanceof Error ? error.message : String(error));
      }
    }
    setSessionBulkNotice({
      tone: failed > 0 ? "error" : "success",
      text: sessionBulkActionSummary(
        t("bulkRemoveSessionsResult"),
        success,
        skipped,
        failed,
        notes,
        lang,
      ),
    });
    clearBulkSessions();
  }, [
    bulkDeleteSessionsMutation,
    bulkSessionPending,
    clearBulkSessions,
    isBusyPhase,
    lang,
    selectedBulkSessions,
    sessionsById,
    t,
  ]);

  return {
    selectedBulkSessionIds,
    selectedBulkSessions,
    allVisibleSessionsSelected,
    bulkSessionPending,
    sessionBulkNotice,
    sessionBulkCopy,
    clearBulkSessions,
    selectVisibleBulkSessions,
    toggleBulkSession,
    bulkRemoveSessions,
    visibleDirectSessionIds,
  };
}
