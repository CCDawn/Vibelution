import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { createFinancialAssistant, listFinancialAssistants } from "../api/financialAssistant";
import { VButton, VDenseOpsPage, VStateSurface } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { ChatCodingRoute } from "./ChatCodingRoute";
import { planFinancialAssistantEntry } from "./finance/financialAssistantEntry";
import styles from "./FinanceRoute.styles";

export function FinanceRoute() {
  const location = useLocation();
  const sessionFromUrl = new URLSearchParams(location.search).get("session") || "";
  if (sessionFromUrl) {
    return <ChatCodingRoute />;
  }
  return <FinanceEntryGate />;
}

function FinanceEntryGate() {
  const { lang } = useShellI18n();
  const zh = lang === "zh";
  const [sessionId, setSessionId] = useState("");
  const [failure, setFailure] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const rows = await listFinancialAssistants();
        if (!active) {
          return;
        }
        const plan = planFinancialAssistantEntry(rows, lang);
        if (plan.kind === "blocked") {
          setFailure(plan.message);
          return;
        }
        const nextId = plan.kind === "open"
          ? plan.sessionId
          : (await createFinancialAssistant()).assistant.directSessionId;
        if (!active) {
          return;
        }
        if (!nextId) {
          setFailure(zh ? "会话还没准备好，请到 Agent 管理里查看。" : "The chat is not ready. Check Agent management.");
          return;
        }
        setSessionId(nextId);
      } catch (error) {
        if (active) {
          setFailure(error instanceof Error ? error.message : (zh ? "打开失败，请重试。" : "Could not open the chat. Retry."));
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [attempt, lang, zh]);

  if (sessionId) {
    return <Navigate to={`/finance?session=${encodeURIComponent(sessionId)}`} replace />;
  }
  return (
    <VDenseOpsPage
      ariaLabel={zh ? "炒股智能体" : "Investment assistant"}
      title={zh ? "炒股智能体" : "Investment assistant"}
      meta={failure ? (zh ? "还没打开" : "Not opened") : (zh ? "正在打开这个助手" : "Opening this assistant")}
      bodyClassName={styles.body}
    >
      <div data-vui-domain-recipe="financial-assistant-entry">
        {failure ? (
          <VStateSurface
            title={zh ? "还没打开这个助手" : "This assistant did not open"}
            tone="error"
            actions={<VButton onPress={() => { setFailure(""); setAttempt((current) => current + 1); }}>{zh ? "重试" : "Retry"}</VButton>}
          >
            {failure}
          </VStateSurface>
        ) : (
          <VStateSurface title={zh ? "正在打开这个助手" : "Opening this assistant"} tone="loading" busy />
        )}
      </div>
    </VDenseOpsPage>
  );
}
