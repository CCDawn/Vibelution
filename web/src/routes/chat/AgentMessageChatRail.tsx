import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, MessagesSquare } from "lucide-react";
import type { AgentInstance } from "../../api/types";
import { AgentMessageDetail, AgentMessageSidebar, type AgentMessageSidebarHandle } from "../../components/agent-messages";
import { VButton, VDialog } from "../../components/vui";
import { currentConversationMessages } from "./agentMessageRecords";
import { loadMoreAgentMessages, selectAgentMessage, useAgentMessageSelection } from "./agentMessageSelectionStore";
import { useAgentMessageRecords } from "./useAgentMessageRecords";
import { useChatRouteSelection } from "./useChatRouteSelection";

export function AgentMessageChatRail({ children, sessionId, agentsById, lang, disabled = false, revealConversations = false }: {
  children: ReactNode; sessionId: string | null; agentsById: Map<string, AgentInstance>; lang: "zh" | "en"; disabled?: boolean;
  revealConversations?: boolean;
}) {
  const route = useChatRouteSelection();
  const center = route.selection.kind === "project_bus";
  const [catalogOpen, setCatalogOpen] = useState(false), [detailOpen, setDetailOpen] = useState(false);
  const sidebarRef = useRef<AgentMessageSidebarHandle>(null);
  const selectedId = useAgentMessageSelection();
  const model = useAgentMessageRecords({ enabled: !disabled && !catalogOpen, sessionId: sessionId || "", agentsById });
  const current = currentConversationMessages(model.records, sessionId || "");
  const visible = center ? model.records : current;
  const selected = model.records.find((record) => record.id === selectedId || record.aliases?.includes(selectedId || ""));
  const canonicalId = selected?.id || selectedId;
  useEffect(() => { setCatalogOpen(false); setDetailOpen(false); }, [center]);
  useEffect(() => { if (revealConversations) setCatalogOpen(true); }, [revealConversations]);
  useEffect(() => {
    if (!selectedId && visible.length) selectAgentMessage(visible[0].id);
  }, [selectedId, visible]);
  if (disabled) return <>{children}</>;
  if (catalogOpen) return <>
    <VButton className="mx-3 my-1 shrink-0 justify-start text-xs" onPress={() => setCatalogOpen(false)}><MessagesSquare size={14} />{lang === "zh" ? "跨 Agent 消息" : "Agent messages"}</VButton>
    {children}
  </>;
  const choose = (id: string) => {
    selectAgentMessage(id);
    sidebarRef.current?.locate(id);
    if (!center) setDetailOpen(true);
  };
  return <div className="flex min-h-0 flex-1 flex-col" data-testid="agent-message-chat-rail">
    <VButton className="mx-3 my-1 shrink-0 justify-start text-xs" onPress={() => setCatalogOpen(true)}><ArrowLeft size={13} />{lang === "zh" ? "会话列表" : "Conversation list"}</VButton>
    <AgentMessageSidebar ref={sidebarRef} records={visible} selectedId={canonicalId} onSelect={choose} lang={lang}
      className="min-h-0 flex-1 !border-r-0" scope={center ? "all" : "current"}
      currentScopeAvailable={Boolean(sessionId || selected?.sourceSessionId)}
      onScopeChange={(scope) => {
        if (scope === "all") { setDetailOpen(false); route.openProjectBus({ telemetrySource: "agent_message_sidebar" }); }
        else if (selected?.sourceSessionId && !sessionId) route.openSession(selected.sourceSessionId, { telemetrySource: "agent_message_sidebar_source" });
      }}
      loading={model.loading} error={model.error} onRefresh={model.refresh}
      footer={<div className="grid gap-2 text-[11px] text-vui-fg-tertiary">
        <span>{lang === "zh" ? `已检查最近 ${model.scanned} 条发送任务；历史按需加载。` : `Checked ${model.scanned} recent tasks; load older records on demand.`}</span>
        {model.hasMore ? <VButton onPress={loadMoreAgentMessages}>{lang === "zh" ? "加载更多发送记录" : "Load older sends"}</VButton> : null}
        {model.limit >= 300 ? <span>{lang === "zh" ? "当前目录最多覆盖最近 300 条任务；来源会话历史另行读取。" : "Directory covers the latest 300 tasks; source history is read separately."}</span> : null}
      </div>} />
    <VDialog open={detailOpen && !center} onOpenChange={setDetailOpen} title={lang === "zh" ? "跨 Agent 消息详情" : "Agent message details"}
      size="xl" contentClassName="h-[min(78dvh,760px)] min-h-0 overflow-hidden p-0">
      <AgentMessageDetail records={model.records} selectedId={canonicalId} onSelect={choose} lang={lang} />
    </VDialog>
  </div>;
}
