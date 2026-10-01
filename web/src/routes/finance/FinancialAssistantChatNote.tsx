import { VRouteLinkButton, VStateSurface } from "../../components/vui";
import { agentCenterConfigRoute, agentCenterMemoryRoute } from "../agentCenterRoutes";
import { financialAssistantBoundary } from "./financialAssistantEntry";
import noteStyles from "./FinancialAssistantChatNote.styles";
import { useFinancialAssistants } from "./useFinancialAssistants";

export function FinancialAssistantChatNote({
  sessionId,
  lang,
}: {
  sessionId?: string | null;
  lang: "zh" | "en";
}) {
  const assistants = useFinancialAssistants(Boolean(sessionId));
  const row = assistants.data?.find((item) => item.directSessionId === sessionId && item.status === "active");
  if (!sessionId || !row) {
    return null;
  }
  const [capability, boundary] = financialAssistantBoundary(lang);
  const returnTo = `/chat?session=${encodeURIComponent(sessionId)}`;
  const zh = lang === "zh";
  return (
    <VStateSurface
      density="compact"
      tone="info"
      title={zh ? "炒股智能体" : "Investment assistant"}
      data-financial-assistant-note="chat"
      actions={(
        <div className={noteStyles.actions}>
          <VRouteLinkButton to={agentCenterConfigRoute({
            agentId: row.agentId,
            returnTo,
            returnLabel: zh ? "炒股智能体" : "Investment assistant",
          })}>
            {zh ? "身份与模型配置" : "Identity and model settings"}
          </VRouteLinkButton>
          {row.knowledgeBaseId ? (
            <VRouteLinkButton to={agentCenterMemoryRoute({
              agentId: row.agentId,
              knowledgeBaseId: row.knowledgeBaseId,
              returnTo,
              returnLabel: zh ? "炒股智能体" : "Investment assistant",
            })}>
              {zh ? "财报知识库" : "Report library"}
            </VRouteLinkButton>
          ) : null}
        </div>
      )}
    >
      <p>{capability}</p>
      <p>{boundary}</p>
    </VStateSurface>
  );
}
