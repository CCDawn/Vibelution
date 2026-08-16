import { useCallback, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type { UseMutationResult } from "@tanstack/react-query";

import type { AgentDirectSessionResetResponse } from "../../api/agents";
import type {
  ChatRoomDetail,
  SessionSummary,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  type ChatWorkbenchConfirmRequest,
  sessionConfirmTitle,
} from "./chatWorkbenchConfirmModel";

export type ChatWorkbenchConfirmPresentation = {
  title: string;
  confirmLabel: string;
  confirmPending: boolean;
};

export type UseChatWorkbenchConfirmDialogInput = {
  activeGroupRoom: ChatRoomDetail | null | undefined;
  deleteSessionMutation: UseMutationResult<unknown, Error, { sessionId: string }, unknown>;
  clearSessionHistoryMutation: UseMutationResult<
    AgentDirectSessionResetResponse,
    Error,
    { sessionId: string; agentId: string },
    unknown
  >;
  deleteGroupRoomMutation: UseMutationResult<unknown, Error, { roomId: string }, unknown>;
  resetGroupRoomMutation: UseMutationResult<unknown, Error, { roomId: string }, unknown>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
};

export type UseChatWorkbenchConfirmDialogResult = {
  pendingConfirm: ChatWorkbenchConfirmRequest | null;
  pendingConfirmPresentation: ChatWorkbenchConfirmPresentation | null;
  openDeleteSessionConfirm: (session: SessionSummary) => void;
  openClearSessionHistoryConfirm: (session: SessionSummary) => void;
  openDeleteGroupConfirm: () => void;
  openResetGroupConfirm: () => void;
  confirmPendingWorkbenchAction: () => void;
  dismissPendingConfirm: () => void;
};

export function useChatWorkbenchConfirmDialog({
  activeGroupRoom,
  deleteSessionMutation,
  clearSessionHistoryMutation,
  deleteGroupRoomMutation,
  resetGroupRoomMutation,
  setSessionComposerErrors,
  lang,
  t,
}: UseChatWorkbenchConfirmDialogInput): UseChatWorkbenchConfirmDialogResult {
  const [pendingConfirm, setPendingConfirm] = useState<ChatWorkbenchConfirmRequest | null>(null);

  const openDeleteSessionConfirm = useCallback((session: SessionSummary) => {
    setPendingConfirm({ kind: "delete-session", session });
  }, []);

  const openClearSessionHistoryConfirm = useCallback((session: SessionSummary) => {
    setPendingConfirm({ kind: "clear-history", session });
  }, []);

  const openDeleteGroupConfirm = useCallback(() => {
    setPendingConfirm({ kind: "delete-group" });
  }, []);

  const openResetGroupConfirm = useCallback(() => {
    setPendingConfirm({ kind: "reset-group" });
  }, []);

  const dismissPendingConfirm = useCallback(() => {
    setPendingConfirm(null);
  }, []);

  const confirmPendingWorkbenchAction = useCallback(() => {
    if (!pendingConfirm) {
      return;
    }
    if (pendingConfirm.kind === "delete-session") {
      const sessionId = pendingConfirm.session.id;
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: "",
        __sessions__: "",
      }));
      setPendingConfirm(null);
      deleteSessionMutation.mutate({ sessionId });
      return;
    }
    if (pendingConfirm.kind === "clear-history") {
      const { session } = pendingConfirm;
      const agentId = String(session.agentId || "").trim();
      if (!agentId) {
        setPendingConfirm(null);
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: "",
        __sessions__: "",
      }));
      setPendingConfirm(null);
      clearSessionHistoryMutation.mutate({ sessionId: session.id, agentId });
      return;
    }
    if (pendingConfirm.kind === "delete-group") {
      const roomId = activeGroupRoom?.roomId;
      setPendingConfirm(null);
      if (roomId) {
        deleteGroupRoomMutation.mutate({ roomId });
      }
      return;
    }
    if (pendingConfirm.kind === "reset-group") {
      const roomId = activeGroupRoom?.roomId;
      setPendingConfirm(null);
      if (roomId) {
        resetGroupRoomMutation.mutate({ roomId });
      }
    }
  }, [
    activeGroupRoom?.roomId,
    clearSessionHistoryMutation,
    deleteGroupRoomMutation,
    deleteSessionMutation,
    pendingConfirm,
    resetGroupRoomMutation,
    setSessionComposerErrors,
  ]);

  const pendingConfirmPresentation = useMemo((): ChatWorkbenchConfirmPresentation | null => {
    if (!pendingConfirm) {
      return null;
    }
    if (pendingConfirm.kind === "delete-session") {
      const title = sessionConfirmTitle(pendingConfirm.session);
      return {
        confirmLabel: t("deleteSession"),
        confirmPending: deleteSessionMutation.isPending
          && deleteSessionMutation.variables?.sessionId === pendingConfirm.session.id,
        title: t("deleteSessionConfirm").replace("{title}", title),
      };
    }
    if (pendingConfirm.kind === "clear-history") {
      const title = sessionConfirmTitle(pendingConfirm.session);
      return {
        confirmLabel: t("clearSessionHistory"),
        confirmPending: clearSessionHistoryMutation.isPending
          && clearSessionHistoryMutation.variables?.sessionId === pendingConfirm.session.id,
        title: t("clearSessionHistoryConfirm").replace("{title}", title),
      };
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoom?.roomId || "").trim();
    if (pendingConfirm.kind === "delete-group") {
      return {
        confirmLabel: lang === "zh" ? "删除群聊" : "Delete group",
        confirmPending: deleteGroupRoomMutation.isPending
          && deleteGroupRoomMutation.variables?.roomId === activeGroupRoom?.roomId,
        title: t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoom?.roomId || ""),
      };
    }
    return {
      confirmLabel: lang === "zh" ? "重置群聊" : "Reset group",
      confirmPending: resetGroupRoomMutation.isPending
        && resetGroupRoomMutation.variables?.roomId === activeGroupRoom?.roomId,
      title: t("resetGroupConfirm").replace("{title}", roomTitle || activeGroupRoom?.roomId || ""),
    };
  }, [
    activeGroupRoom?.roomId,
    activeGroupRoom?.title,
    clearSessionHistoryMutation.isPending,
    clearSessionHistoryMutation.variables?.sessionId,
    deleteGroupRoomMutation.isPending,
    deleteGroupRoomMutation.variables?.roomId,
    deleteSessionMutation.isPending,
    deleteSessionMutation.variables?.sessionId,
    lang,
    pendingConfirm,
    resetGroupRoomMutation.isPending,
    resetGroupRoomMutation.variables?.roomId,
    t,
  ]);

  return {
    pendingConfirm,
    pendingConfirmPresentation,
    openDeleteSessionConfirm,
    openClearSessionHistoryConfirm,
    openDeleteGroupConfirm,
    openResetGroupConfirm,
    confirmPendingWorkbenchAction,
    dismissPendingConfirm,
  };
}
