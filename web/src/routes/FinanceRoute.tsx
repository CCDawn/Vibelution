import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { fetchSessionDetail } from "../api/chat";
import { createFinancialAssistant, type FinancialAssistant } from "../api/financialAssistant";
import { queryKeys } from "../api/queryKeys";
import { VButton, VRouteLinkButton, VStateSurface } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { useChatRouteSelection } from "./chat/useChatRouteSelection";
import { FinanceResearchFrame, FinanceResearchLoading } from "./finance/FinanceResearchFrame";
import { FinanceResearchWorkspace } from "./finance/FinanceResearchWorkspace";
import { planFinancialAssistantEntry } from "./finance/financialAssistantEntry";
import { isFinancialSession } from "./finance/financialResearchModel";
import { useFinancialAssistants } from "./finance/useFinancialAssistants";
import styles from "./FinanceRoute.styles";

export function FinanceRoute() {
  const { lang } = useShellI18n();
  const zh = lang === "zh";
  const location = useLocation();
  const route = useChatRouteSelection();
  const routeRef = useRef(route);
  routeRef.current = route;
  const sessionId = route.selection.kind === "session" ? route.selection.sessionId : "";
  const [failure, setFailure] = useState("");
  const [attempt, setAttempt] = useState(0);
  const queryClient = useQueryClient();
  const assistants = useFinancialAssistants();
  const creationRef = useRef<ReturnType<typeof createFinancialAssistant> | null>(null);
  const plan = assistants.data ? planFinancialAssistantEntry(assistants.data, lang) : null;
  const assistant = assistants.data?.find((row) => row.status === "active" && row.setupStatus === "ready" && row.directSessionId === sessionId)
    ?? assistants.data?.find((row) => row.status === "active" && row.setupStatus === "ready");
  const direct = Boolean(sessionId && assistant?.directSessionId === sessionId);
  const binding = useQuery({
    queryKey: ["finance", "session-binding", assistant?.agentId, sessionId],
    queryFn: ({ signal }) => fetchSessionDetail(sessionId, { transcriptScope: "none", includeSecondary: false, signal }),
    enabled: Boolean(sessionId && assistant && !direct),
    staleTime: 15_000, retry: false,
  });
  useEffect(() => {
    if (route.selection.kind !== "bare" || !assistants.isSuccess || new URLSearchParams(location.search).has("companion")) return;
    let active = true;
    const expected = route.selection;
    void (async () => {
      try {
        const entry = planFinancialAssistantEntry(assistants.data, lang);
        if (entry.kind === "blocked") { setFailure(entry.message); return; }
        let nextId = entry.kind === "open" ? entry.sessionId : "";
        if (entry.kind === "create") {
          creationRef.current ??= createFinancialAssistant().then((result) => {
            queryClient.setQueryData<FinancialAssistant[]>(queryKeys.financialAssistants(), (rows) => [
              ...(rows ?? []).filter((row) => row.agentId !== result.assistant.agentId), result.assistant,
            ]);
            return result;
          });
          nextId = (await creationRef.current).assistant.directSessionId;
        }
        if (!active) return;
        if (!nextId) { setFailure(zh ? "会话尚未准备好" : "Session not ready"); return; }
        routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: nextId });
      } catch (error) {
        creationRef.current = null;
        if (active) setFailure(error instanceof Error ? error.message : (zh ? "打开失败，请重试" : "Could not open research"));
      }
    })();
    return () => { active = false; };
  }, [assistants.data, assistants.isSuccess, attempt, lang, location.search, queryClient, route.selection, zh]);

  const invalidRoute = route.selection.kind !== "bare" && route.selection.kind !== "session"
    || new URLSearchParams(location.search).has("companion");
  const bindingMismatch = binding.isSuccess && (!binding.data || binding.data.id !== sessionId || !isFinancialSession(binding.data, assistant?.agentId ?? ""));
  const error = invalidRoute ? (zh ? "请选择金融助手的研究会话" : "Select an investment research session")
    : assistants.isError ? (zh ? "助手加载失败，请重试" : "Could not load assistant")
    : plan?.kind === "blocked" ? plan.message
    : sessionId && assistants.isSuccess && !assistant ? (zh ? "金融助手尚未就绪" : "Assistant not ready")
    : binding.isError ? (zh ? "会话验证失败，请重试" : "Could not verify session")
    : bindingMismatch ? (zh ? "当前会话不属于这个金融助手" : "This session belongs to another agent")
    : failure;
  if (!error && sessionId && assistant && (direct || binding.isSuccess)) {
    return <FinanceResearchWorkspace key={assistant.agentId} assistant={assistant} sessionId={sessionId} zh={zh} />;
  }
  if (!error) return <FinanceResearchLoading zh={zh} />;
  return <FinanceResearchFrame zh={zh} loading={!error}>
    <div className={styles.state} data-finance-entry-state={error ? "error" : "loading"}>
      <VStateSurface
        className={styles.stateSurface}
        title={error ? (zh ? "无法打开研究" : "Could not open research") : (zh ? "连接研究工作台" : "Opening research workspace")}
        tone={error ? "error" : "loading"}
        busy={!error}
        actions={error ? <div className={styles.actions}>
          <VButton onPress={() => {
            setFailure("");
            if (binding.isError) void binding.refetch();
            void assistants.refetch();
            setAttempt((current) => current + 1);
          }}>{zh ? "重试" : "Retry"}</VButton>
          {sessionId || invalidRoute ? <VRouteLinkButton to="/finance">{zh ? "打开助手" : "Open assistant"}</VRouteLinkButton> : null}
        </div> : undefined}
      >{error || undefined}</VStateSurface>
    </div>
  </FinanceResearchFrame>;
}
