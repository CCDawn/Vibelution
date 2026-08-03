import {
  useCallback,
  useRef,
  type Dispatch,
  type MouseEvent as ReactMouseEvent,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import type { NavigateFunction } from "react-router-dom";

import type { SessionSummary } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import {
  isChildSession,
} from "../DirectSessionIndexItem";
import { isTempSessionId } from "../sessionOptimisticIds";

/** Placeholder titles for brand-new empty chats (create → optional rename UX). */
export function isDefaultNewSessionTitle(title: string | null | undefined): boolean {
  const normalized = String(title || "").trim();
  return normalized === "新会话" || normalized === "New session";
}

export type SessionContextMenuState = {
  sessionId: string;
  session: SessionSummary;
  x: number;
  y: number;
};

export type UseChatSessionRenameMenuOptions = {
  t: (key: TranslationKey) => string;
  navigate: NavigateFunction;
  editingSessionTitle: string;
  setEditingSessionId: Dispatch<SetStateAction<string | null>>;
  setEditingSessionTitle: Dispatch<SetStateAction<string>>;
  setSessionContextMenu: Dispatch<SetStateAction<SessionContextMenuState | null>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  renameSession: (variables: { sessionId: string; title: string }) => void;
  /** Optional shared ref so create can suppress blur-submit during temp→real id remap. */
  suppressRenameBlurUntilRef?: MutableRefObject<number>;
};

export type SubmitRenameSessionOptions = {
  /** Blur-driven submits are ignored briefly after optimistic create remounts the tab. */
  reason?: "blur" | "explicit";
};

export type UseChatSessionRenameMenuResult = {
  beginRenameSession: (session: SessionSummary) => void;
  openSessionAgentConfig: (session: SessionSummary) => void;
  cancelRenameSession: () => void;
  openSessionContextMenu: (event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => void;
  submitRenameSession: (session: SessionSummary, options?: SubmitRenameSessionOptions) => void;
  suppressRenameBlurUntilRef: MutableRefObject<number>;
};

/**
 * Session rename + context-menu open/config handlers for the conversation index.
 */
export function useChatSessionRenameMenu({
  t,
  navigate,
  editingSessionTitle,
  setEditingSessionId,
  setEditingSessionTitle,
  setSessionContextMenu,
  setSessionComposerErrors,
  renameSession,
  suppressRenameBlurUntilRef: suppressRenameBlurUntilRefOption,
}: UseChatSessionRenameMenuOptions): UseChatSessionRenameMenuResult {
  const localSuppressRenameBlurUntilRef = useRef(0);
  const suppressRenameBlurUntilRef = suppressRenameBlurUntilRefOption ?? localSuppressRenameBlurUntilRef;

  const beginRenameSession = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    setEditingSessionId(session.id);
    // Session tab rename always edits the session/task title — Agent rename is a separate action.
    setEditingSessionTitle(
      isChildSession(session)
        ? (session.taskTitle || session.resultCard?.title || session.title || t("newSession"))
        : (session.title || t("newSession")),
    );
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
  }, [setEditingSessionId, setEditingSessionTitle, setSessionComposerErrors, setSessionContextMenu, t]);

  const openSessionAgentConfig = useCallback((session: SessionSummary) => {
    const agentId = String(session.agentId || "").trim();
    if (!agentId) {
      setSessionContextMenu(null);
      return;
    }
    setSessionContextMenu(null);
    navigate(agentCenterConfigRoute({
      agentId,
      pane: "config",
      returnLabel: "chat",
      returnTo: `/chat?session=${encodeURIComponent(session.id)}`,
    }));
  }, [navigate, setSessionContextMenu]);

  const cancelRenameSession = useCallback(() => {
    setSessionContextMenu(null);
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }, [setEditingSessionId, setEditingSessionTitle, setSessionContextMenu]);

  const openSessionContextMenu = useCallback((event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu({
      sessionId: session.id,
      session,
      x: event.clientX,
      y: event.clientY,
    });
  }, [setSessionContextMenu]);

  const submitRenameSession = useCallback((session: SessionSummary, options?: SubmitRenameSessionOptions) => {
    const reason = options?.reason || "explicit";
    // Optimistic create remounts the tab (temp id → server id); ignore blur from that remount.
    if (reason === "blur" && Date.now() < suppressRenameBlurUntilRef.current) {
      return;
    }
    // Temp shells are not server-addressable yet.
    if (isTempSessionId(session.id)) {
      return;
    }
    const title = editingSessionTitle.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t(isChildSession(session) ? "renameTaskEmpty" : "renameSessionEmpty"),
      }));
      return;
    }
    const currentTitle = isChildSession(session)
      ? String(session.taskTitle || session.resultCard?.title || session.title || "").trim()
      : String(session.title || "").trim();
    // Leaving the default placeholder is not a real rename — keep "新会话" without a PATCH.
    if (isDefaultNewSessionTitle(title) && (!currentTitle || isDefaultNewSessionTitle(currentTitle))) {
      cancelRenameSession();
      return;
    }
    if (title === currentTitle) {
      cancelRenameSession();
      return;
    }
    renameSession({ sessionId: session.id, title });
  }, [cancelRenameSession, editingSessionTitle, renameSession, setSessionComposerErrors, suppressRenameBlurUntilRef, t]);

  return {
    beginRenameSession,
    openSessionAgentConfig,
    cancelRenameSession,
    openSessionContextMenu,
    submitRenameSession,
    suppressRenameBlurUntilRef,
  };
}
