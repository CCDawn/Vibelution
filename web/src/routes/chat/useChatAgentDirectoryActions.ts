/**
 * Chat agent-directory context-menu actions.
 */
import {
  useCallback,
  useState,
  type Dispatch,
  type MouseEvent as ReactMouseEvent,
  type SetStateAction,
} from "react";
import type { NavigateFunction } from "react-router-dom";

import type { AgentInstance, SessionSummary } from "../../api/types";
import type { AgentContextMenuState } from "../AgentContextMenu";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import type { SessionContextMenuState } from "./useChatSessionRenameMenu";

export type AgentRenameDraft = {
  agentId: string;
  currentName: string;
  draftName: string;
};

export type UseChatAgentDirectoryActionsOptions = {
  lang: "zh" | "en";
  navigate: NavigateFunction;
  createSessionPending: boolean;
  renameAgentPending: boolean;
  archiveAgentPending: boolean;
  createSession: (variables: { agentId: string }) => void;
  renameAgent: (variables: { agentId: string; displayName: string }) => void;
  archiveAgent: (variables: { agentId: string }) => void;
  openDirectSession: (sessionId: string) => void;
  openAgent: (agent: AgentInstance) => void;
  setAgentContextMenu: Dispatch<SetStateAction<AgentContextMenuState | null>>;
  setSessionContextMenu: Dispatch<SetStateAction<SessionContextMenuState | null>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setAgentCreateWizardOpen: (open: boolean) => void;
  renameAgentEmptyMessage: string;
  /** Optional archive confirm (defaults to window.confirm). */
  confirmArchive?: (message: string) => boolean;
};

/**
 * Open agent rename in an in-app dialog. Electron/desktop shells block native browser
 * prompts, so context-menu rename must not rely on that API.
 */
export function useChatAgentDirectoryActions(options: UseChatAgentDirectoryActionsOptions) {
  const {
    lang,
    navigate,
    createSessionPending,
    renameAgentPending,
    archiveAgentPending,
    createSession,
    renameAgent,
    archiveAgent,
    openDirectSession,
    openAgent,
    setAgentContextMenu,
    setSessionContextMenu,
    setSessionComposerErrors,
    setAgentCreateWizardOpen,
    renameAgentEmptyMessage,
    confirmArchive = (message) => window.confirm(message),
  } = options;

  const [agentRenameDraft, setAgentRenameDraft] = useState<AgentRenameDraft | null>(null);

  const handleCreateAgent = useCallback(() => {
    setAgentCreateWizardOpen(true);
  }, [setAgentCreateWizardOpen]);

  const openAgentContextMenu = useCallback((
    event: ReactMouseEvent<HTMLElement>,
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu(null);
    setAgentContextMenu({
      agent,
      latestSession,
      x: event.clientX,
      y: event.clientY,
    });
  }, [setAgentContextMenu, setSessionContextMenu]);

  const handleOpenAgentLatestSession = useCallback((
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => {
    setAgentContextMenu(null);
    if (latestSession?.id) {
      openDirectSession(latestSession.id);
      return;
    }
    openAgent(agent);
  }, [openAgent, openDirectSession, setAgentContextMenu]);

  const handleCreateAgentSession = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    setAgentContextMenu(null);
    if (!agentId || createSessionPending) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSession({ agentId });
  }, [createSession, createSessionPending, setAgentContextMenu, setSessionComposerErrors]);

  const handleOpenAgentConfig = useCallback((
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => {
    const agentId = String(agent.agentId || "").trim();
    setAgentContextMenu(null);
    if (!agentId) {
      return;
    }
    navigate(agentCenterConfigRoute({
      agentId,
      pane: "config",
      returnLabel: "chat",
      returnTo: latestSession?.id
        ? `/chat?session=${encodeURIComponent(latestSession.id)}`
        : "/chat",
    }));
  }, [navigate, setAgentContextMenu]);

  const handleRenameAgent = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    setAgentContextMenu(null);
    if (!agentId || renameAgentPending) {
      return;
    }
    const currentName = String(agent.displayName || agent.agentCode || agentId).trim();
    // Defer past Radix menu unmount/focus restore so the dialog can take focus.
    queueMicrotask(() => {
      setAgentRenameDraft({
        agentId,
        currentName,
        draftName: currentName,
      });
    });
  }, [renameAgentPending, setAgentContextMenu]);

  const setAgentRenameDraftName = useCallback((draftName: string) => {
    setAgentRenameDraft((current) => (current ? { ...current, draftName } : current));
  }, []);

  const cancelAgentRename = useCallback(() => {
    setAgentRenameDraft(null);
  }, []);

  const submitAgentRename = useCallback(() => {
    if (!agentRenameDraft || renameAgentPending) {
      return;
    }
    const title = agentRenameDraft.draftName.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: renameAgentEmptyMessage,
      }));
      return;
    }
    if (title === agentRenameDraft.currentName) {
      setAgentRenameDraft(null);
      return;
    }
    renameAgent({ agentId: agentRenameDraft.agentId, displayName: title });
    setAgentRenameDraft(null);
  }, [
    agentRenameDraft,
    renameAgent,
    renameAgentEmptyMessage,
    renameAgentPending,
    setSessionComposerErrors,
  ]);

  const handleArchiveAgent = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    if (!agentId || archiveAgentPending) {
      return;
    }
    const agentName = String(agent.displayName || agent.agentCode || agentId).trim();
    const confirmed = confirmArchive(
      lang === "zh"
        ? `确认安全归档 ${agentName}？这会将 Agent 移出可用列表及相关绑定，但保留会话、记忆、日志和工作区。`
        : `Archive ${agentName}? This removes the Agent from active lists and bindings while keeping sessions, memory, logs, and workspace data.`,
    );
    if (!confirmed) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    archiveAgent({ agentId });
  }, [archiveAgent, archiveAgentPending, confirmArchive, lang, setSessionComposerErrors]);

  return {
    handleCreateAgent,
    openAgentContextMenu,
    handleOpenAgentLatestSession,
    handleCreateAgentSession,
    handleOpenAgentConfig,
    handleRenameAgent,
    handleArchiveAgent,
    agentRenameDraft,
    setAgentRenameDraftName,
    cancelAgentRename,
    submitAgentRename,
  };
}
