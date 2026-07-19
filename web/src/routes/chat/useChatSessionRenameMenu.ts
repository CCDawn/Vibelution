import { useCallback, type Dispatch, type MouseEvent as ReactMouseEvent, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";

import type { SessionSummary } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import {
  isAgentRootSession,
  isChildSession,
} from "../DirectSessionIndexItem";

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
};

export type UseChatSessionRenameMenuResult = {
  beginRenameSession: (session: SessionSummary) => void;
  openSessionAgentConfig: (session: SessionSummary) => void;
  cancelRenameSession: () => void;
  openSessionContextMenu: (event: ReactMouseEvent<HTMLElement>, session: SessionSummary) => void;
  submitRenameSession: (session: SessionSummary) => void;
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
}: UseChatSessionRenameMenuOptions): UseChatSessionRenameMenuResult {
  const beginRenameSession = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    setEditingSessionId(session.id);
    setEditingSessionTitle(
      isAgentRootSession(session)
        ? (session.agentDisplayName || session.title)
        : isChildSession(session)
          ? (session.taskTitle || session.resultCard?.title || session.title)
          : session.title,
    );
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
  }, [setEditingSessionId, setEditingSessionTitle, setSessionComposerErrors, setSessionContextMenu]);

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

  const submitRenameSession = useCallback((session: SessionSummary) => {
    const title = editingSessionTitle.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t(isAgentRootSession(session) ? "renameAgentEmpty" : isChildSession(session) ? "renameTaskEmpty" : "renameSessionEmpty"),
      }));
      return;
    }
    const currentTitle = isAgentRootSession(session)
      ? (session.agentDisplayName || session.title)
      : isChildSession(session)
        ? (session.taskTitle || session.resultCard?.title || session.title)
        : session.title;
    if (title === currentTitle) {
      cancelRenameSession();
      return;
    }
    renameSession({ sessionId: session.id, title });
  }, [cancelRenameSession, editingSessionTitle, renameSession, setSessionComposerErrors, t]);

  return {
    beginRenameSession,
    openSessionAgentConfig,
    cancelRenameSession,
    openSessionContextMenu,
    submitRenameSession,
  };
}
