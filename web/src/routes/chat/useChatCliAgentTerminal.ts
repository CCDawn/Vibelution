import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../../api/client";
import type { ConversationMessage } from "../../api/types";
import {
  buildCliAgentRunViews,
  cliAgentRunCloseToken,
  isCliAgentRunActiveForClose,
  type CliAgentRunView,
  type CliAgentTerminalSession,
} from "./cliAgentRunModel";

export type UseChatCliAgentTerminalOptions = {
  activeSessionId: string | null | undefined;
  activeCliAgentRunId: string | null | undefined;
  groupPanelActive: boolean;
  detailMessages: ConversationMessage[] | undefined;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  setActiveTab: (sessionId: string, tabId: string) => void;
  refetchSessionDetail: () => Promise<unknown> | unknown;
};

export type UseChatCliAgentTerminalResult = {
  cliAgentRunTabs: CliAgentRunView[];
  activeCliAgentRun: CliAgentRunView | undefined;
  mountedCliAgentRuns: CliAgentRunView[];
  cliAgentTerminalSessions: Record<string, CliAgentTerminalSession>;
  handleCliAgentTerminalSessionChange: (runId: string, session: CliAgentTerminalSession) => void;
  closeCliAgentRun: (run: CliAgentRunView) => Promise<void>;
};

/**
 * CLI agent terminal tabs/session lifecycle for the chat workspace.
 * Does not open the main session EventSource.
 */
export function useChatCliAgentTerminal({
  activeSessionId,
  activeCliAgentRunId,
  groupPanelActive,
  detailMessages,
  lang,
  describeError,
  setActiveTab,
  refetchSessionDetail,
}: UseChatCliAgentTerminalOptions): UseChatCliAgentTerminalResult {
  const [closedCliAgentRunTokensBySession, setClosedCliAgentRunTokensBySession] = useState<Record<string, string[]>>({});
  const [cliAgentTerminalSessions, setCliAgentTerminalSessions] = useState<Record<string, CliAgentTerminalSession>>({});
  const [mountedCliAgentRunIdsBySession, setMountedCliAgentRunIdsBySession] = useState<Record<string, string[]>>({});

  const closedCliAgentRunTokens = activeSessionId ? (closedCliAgentRunTokensBySession[activeSessionId] ?? []) : [];
  const closedCliAgentRunTokenSet = useMemo(() => new Set(closedCliAgentRunTokens), [closedCliAgentRunTokens]);
  const cliAgentRunTabs = useMemo(
    () => buildCliAgentRunViews(detailMessages ?? [], activeSessionId ?? "").filter((run) => !closedCliAgentRunTokenSet.has(cliAgentRunCloseToken(run))),
    [activeSessionId, closedCliAgentRunTokenSet, detailMessages],
  );
  const activeCliAgentRun = useMemo(
    () => activeCliAgentRunId ? cliAgentRunTabs.find((run) => run.id === activeCliAgentRunId) : undefined,
    [activeCliAgentRunId, cliAgentRunTabs],
  );
  const mountedCliAgentRunIds = activeSessionId ? (mountedCliAgentRunIdsBySession[activeSessionId] ?? []) : [];
  const mountedCliAgentRunIdSet = useMemo(() => {
    const ids = new Set(mountedCliAgentRunIds);
    if (activeCliAgentRun && !groupPanelActive) {
      ids.add(activeCliAgentRun.id);
    }
    return ids;
  }, [activeCliAgentRun, groupPanelActive, mountedCliAgentRunIds]);
  const mountedCliAgentRuns = useMemo(
    () => cliAgentRunTabs.filter((run) => mountedCliAgentRunIdSet.has(run.id)),
    [cliAgentRunTabs, mountedCliAgentRunIdSet],
  );

  useEffect(() => {
    if (!activeSessionId || !activeCliAgentRun || groupPanelActive) {
      return;
    }
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.includes(activeCliAgentRun.id)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, activeCliAgentRun.id],
      };
    });
  }, [activeCliAgentRun, activeSessionId, groupPanelActive]);

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const availableRunIds = new Set(cliAgentRunTabs.map((run) => run.id));
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((runId) => availableRunIds.has(runId));
      if (next.length === existing.length) {
        return current;
      }
      if (next.length === 0) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }, [activeSessionId, cliAgentRunTabs]);

  useEffect(() => {
    if (!activeSessionId || !activeCliAgentRunId) {
      return;
    }
    if (!cliAgentRunTabs.some((run) => run.id === activeCliAgentRunId)) {
      setActiveTab(activeSessionId, "agent");
    }
  }, [activeCliAgentRunId, activeSessionId, cliAgentRunTabs, setActiveTab]);

  const handleCliAgentTerminalSessionChange = useCallback((runId: string, session: CliAgentTerminalSession) => {
    setCliAgentTerminalSessions((current) => {
      const previous = current[runId];
      if (
        previous?.terminalSessionId === session.terminalSessionId
        && previous?.status === session.status
        && previous?.alive === session.alive
        && previous?.cliSessionId === session.cliSessionId
      ) {
        return current;
      }
      return {
        ...current,
        [runId]: session,
      };
    });
  }, []);

  const closeCliAgentRun = useCallback(async (run: CliAgentRunView) => {
    if (!activeSessionId) {
      return;
    }
    const terminalSession = cliAgentTerminalSessions[run.id];
    const terminalSessionId = String(terminalSession?.terminalSessionId || run.terminalSessionId || run.result?.terminalSessionId || "").trim();
    const shouldStopTerminal = isCliAgentRunActiveForClose(run, terminalSession);
    if (shouldStopTerminal && typeof window !== "undefined") {
      const confirmed = window.confirm(
        lang === "zh"
          ? `关闭后将结束当前 ${run.title} 终端会话，是否关闭？`
          : `Closing will end the current ${run.title} terminal session. Close it?`,
      );
      if (!confirmed) {
        return;
      }
    }
    if (shouldStopTerminal && terminalSessionId) {
      try {
        await fetchJson<CliAgentTerminalSession>(
          `/api/cli-agents/terminal-sessions/${encodeURIComponent(terminalSessionId)}/stop`,
          { method: "POST" },
        );
        void refetchSessionDetail();
      } catch (error) {
        if (typeof window !== "undefined") {
          window.alert(
            lang === "zh"
              ? `关闭 ${run.title} 终端失败：${describeError(error, "请求失败")}`
              : `Failed to close ${run.title}: ${describeError(error, "Request failed")}`,
          );
        }
        return;
      }
    }
    setClosedCliAgentRunTokensBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      const closeToken = cliAgentRunCloseToken(run);
      if (existing.includes(closeToken)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, closeToken],
      };
    });
    setCliAgentTerminalSessions((current) => {
      const { [run.id]: _removed, ...remaining } = current;
      return remaining;
    });
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      if (!existing.includes(run.id)) {
        return current;
      }
      const next = existing.filter((runId) => runId !== run.id);
      if (next.length === 0) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
    if (activeCliAgentRunId === run.id) {
      setActiveTab(activeSessionId, "agent");
    }
  }, [
    activeCliAgentRunId,
    activeSessionId,
    cliAgentTerminalSessions,
    describeError,
    lang,
    refetchSessionDetail,
    setActiveTab,
  ]);

  return {
    cliAgentRunTabs,
    activeCliAgentRun,
    mountedCliAgentRuns,
    cliAgentTerminalSessions,
    handleCliAgentTerminalSessionChange,
    closeCliAgentRun,
  };
}
