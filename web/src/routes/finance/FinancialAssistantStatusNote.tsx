import { VStateSurface } from "../../components/vui";
import { financialConnectionFacts } from "./financialAssistantEntry";
import { useFinancialAssistants } from "./useFinancialAssistants";

export function FinancialAssistantStatusNote({
  agentId = "",
  lang,
}: {
  agentId?: string;
  lang: "zh" | "en";
}) {
  const normalizedAgentId = agentId.trim();
  const assistants = useFinancialAssistants(Boolean(normalizedAgentId));
  const row = assistants.data?.find((item) => item.agentId === normalizedAgentId);
  if (!row) {
    return null;
  }
  return (
    <VStateSurface
      density="compact"
      tone="info"
      title={lang === "zh" ? "连接状态" : "Connection status"}
      data-financial-assistant-note="status"
      facts={financialConnectionFacts(row, lang)}
    />
  );
}
