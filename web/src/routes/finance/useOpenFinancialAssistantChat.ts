import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { useLocation } from "react-router-dom";

import { createFinancialAssistant, listFinancialAssistants } from "../../api/financialAssistant";
import { queryKeys } from "../../api/queryKeys";
import { useShellI18n } from "../../i18n/useShellI18n";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import { planFinancialAssistantEntry } from "./financialAssistantEntry";

export type OpenFinancialAssistantResult =
  | { ok: true }
  | { ok: false; cancelled: true }
  | { ok: false; message: string };

export function useOpenFinancialAssistantChat() {
  const { lang } = useShellI18n();
  const { openSession } = useChatRouteSelection();
  const location = useLocation();
  const cache = useQueryClient();
  const locationKey = useRef(location.key);
  const langRef = useRef(lang);
  const openSessionRef = useRef(openSession);
  const runId = useRef(0);
  locationKey.current = location.key;
  langRef.current = lang;
  openSessionRef.current = openSession;

  const cancel = useCallback(() => {
    runId.current += 1;
  }, []);

  const open = useCallback(async (options?: { replace?: boolean }): Promise<OpenFinancialAssistantResult> => {
    const id = ++runId.current;
    const startedKey = locationKey.current;
    const alive = () => id === runId.current && locationKey.current === startedKey;
    const fail = (message: string): OpenFinancialAssistantResult => (
      alive() ? { ok: false, message } : { ok: false, cancelled: true }
    );
    try {
      const rows = await listFinancialAssistants();
      if (!alive()) {
        return { ok: false, cancelled: true };
      }
      const plan = planFinancialAssistantEntry(rows, langRef.current);
      if (plan.kind === "blocked") {
        return fail(plan.message);
      }
      let sessionId = plan.kind === "open" ? plan.sessionId : "";
      if (plan.kind === "open") {
        cache.setQueryData(queryKeys.financialAssistants(), rows);
      } else {
        const created = await createFinancialAssistant();
        if (!alive()) {
          return { ok: false, cancelled: true };
        }
        sessionId = created.assistant.directSessionId;
        cache.setQueryData(queryKeys.financialAssistants(), [created.assistant]);
      }
      if (!sessionId) {
        return fail(langRef.current === "zh"
          ? "会话还没准备好，请到 Agent 管理里查看。"
          : "The chat is not ready. Check Agent management.");
      }
      if (!alive()) {
        return { ok: false, cancelled: true };
      }
      openSessionRef.current(sessionId, {
        replace: options?.replace ?? true,
        telemetrySource: "financial_assistant_entry",
      });
      return { ok: true };
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : (langRef.current === "zh" ? "打开失败，请重试。" : "Could not open the chat. Retry.");
      return fail(message);
    }
  }, [cache]);

  return { open, cancel };
}
