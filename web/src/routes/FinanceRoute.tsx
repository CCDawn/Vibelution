import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { VButton, VDenseOpsPage, VStateSurface } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./FinanceRoute.styles";
import { useOpenFinancialAssistantChat } from "./finance/useOpenFinancialAssistantChat";

function entryErrorFromState(state: unknown) {
  if (!state || typeof state !== "object") {
    return "";
  }
  const message = (state as { financialEntryError?: unknown }).financialEntryError;
  return typeof message === "string" ? message : "";
}

export function FinanceRoute() {
  const { lang } = useShellI18n();
  const location = useLocation();
  const presetError = entryErrorFromState(location.state);
  const { open, cancel } = useOpenFinancialAssistantChat();
  const [failure, setFailure] = useState(presetError);
  const zh = lang === "zh";
  useEffect(() => {
    if (presetError) {
      return undefined;
    }
    let active = true;
    void open({ replace: true }).then((result) => {
      if (active && !result.ok && "message" in result) {
        setFailure(result.message);
      }
    });
    return () => {
      active = false;
      cancel();
    };
  }, [cancel, open, presetError]);
  const retry = () => {
    setFailure("");
    void open({ replace: true }).then((result) => {
      if (!result.ok && "message" in result) {
        setFailure(result.message);
      }
    });
  };

  return (
    <VDenseOpsPage
      ariaLabel={zh ? "炒股智能体" : "Investment assistant"}
      title={zh ? "炒股智能体" : "Investment assistant"}
      meta={zh ? "正在打开对话" : "Opening chat"}
      bodyClassName={styles.body}
    >
      <div className={styles.sections} data-vui-domain-recipe="financial-assistant-entry">
        {failure ? (
          <VStateSurface
            title={zh ? "还没打开对话" : "Chat did not open"}
            tone="error"
            actions={<VButton onPress={retry}>{zh ? "重试" : "Retry"}</VButton>}
          >
            {failure}
          </VStateSurface>
        ) : (
          <VStateSurface title={zh ? "正在打开对话" : "Opening chat"} tone="loading" busy />
        )}
      </div>
    </VDenseOpsPage>
  );
}
