/** Isolated verification of production components. Every API response is synthetic. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import type { AgentInstance, KernelTaskTimelinePayload, SessionDetail } from "../api/types";
import { queryKeys } from "../api/queryKeys";
import { ConversationView } from "../components/conversation/ConversationView";
import { VButton, VuiProvider } from "../components/vui";
import { AgentMessageChatRail } from "../routes/chat/AgentMessageChatRail";
import { ChatProjectBusSurface } from "../routes/chat/ChatProjectBusSurface";
import { useChatRouteSelection } from "../routes/chat/useChatRouteSelection";
import "./tokens.css";
import "./base.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./agent-message-sidebar-preview.css";
import styles from "./agent-message-sidebar-preview.styles";

const agents = new Map([...[ ["assistant", "个人助理"], ["reviewer", "审查助手"], ["tester", "测试助手"], ["researcher", "调研助手"] ].map(([agentId, displayName]) => [agentId, { agentId, displayName, agentCode: agentId } as AgentInstance] as const)]);
const stamp = "2026-11-01T12:00:00Z";
function event(id: string, body: string, recipients: string[], metadata: Record<string, unknown> = {}): KernelTaskTimelinePayload {
  return { taskId: `task-${id}`, task: { taskId: `task-${id}`, status: "succeeded" }, event: { eventId: id, senderAgentId: "assistant", sender: { id: "assistant", displayName: "个人助理" }, recipients, createdAt: stamp,
    semanticPayload: { semanticType: "agent.message", payload: { content: body, summary: body } }, metadata: { sourceSessionId: "fixture-source", ...metadata } },
    deliveries: recipients.map((targetAgentId) => ({ targetAgentId, targetSessionId: `session-${targetAgentId}`, inboxMessageId: `inbox-${id}`, status: "delivered", wake: { wakeStatus: targetAgentId === "researcher" ? "skipped_no_direct_session" : targetAgentId === "tester" ? "skipped_busy" : "started", reason: targetAgentId === "researcher" ? "AgentSessionUnavailable: branch is not started" : "" } })),
  } as unknown as KernelTaskTimelinePayload;
}
const timelines = [event("message-one", "请检查跨 Agent 消息的真实状态", ["reviewer"]), event("message-group", "核对左栏与群发的逐人回执", ["reviewer", "tester", "researcher"]), event("message-notice", "新版本的检查结果已归档", ["tester"], { requiresReply: false })];
const source = { id: "fixture-source", agentId: "assistant", title: "保留当前对话", ledgerSeq: 10,
  messages: [
    { id: "user-1", role: "user", content: "检查消息状态，保留我正在输入的内容。", timestamp: stamp },
    { id: "assistant-1", role: "assistant", turnId: "turn-one", status: "completed", timestamp: stamp, turnItems: [
      { version: 3, id: "body:1", itemId: "body", sessionId: "fixture-source", turnId: "turn-one", type: "agent_message", phase: "final_answer", sequence: 1, revision: 1, status: "completed", text: "跨 Agent 消息显示在左栏。查看回执时，当前对话和草稿继续保留。" },
      { version: 3, id: "failed:1", itemId: "failed", sessionId: "fixture-source", turnId: "turn-one", type: "tool_call", sequence: 2, revision: 1, status: "completed", toolName: "agent_message_tool", input: JSON.stringify({ content: "检查未启动分支", target_agent: "researcher", target_session: "not-started" }), output: JSON.stringify({ ok: false, error: "AgentSessionUnavailable", message: "The target branch is not started" }) },
    ] },
    { id: "reply-row", nodeId: "reply-journal-node", role: "user", content: "已完成核对，左栏身份与状态显示正常。", timestamp: "2026-11-01T12:01:00Z", metadata: { sourceSurface: "agent_inbox_reply", sourceAgentId: "reviewer", sourceSessionId: "session-reviewer", sourceTurnId: "reply-turn", replyToMessageId: "inbox-message-one" } },
  ],
} as unknown as SessionDetail;
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const requestUrl = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.href);
  if (!requestUrl.pathname.startsWith("/api/")) return nativeFetch(input, init);
  const method = init?.method || (input instanceof Request ? input.method : "GET");
  if (method !== "GET") return Response.json({ detail: "Writes disabled in isolated component verification" }, { status: 403 });
  if (requestUrl.pathname === "/api/control-token") return Response.json({ header: "X-Control-Token", controlToken: "isolated-preview-only" });
  if (requestUrl.pathname === "/api/kernel/tasks") return Response.json({ tasks: timelines.map((row) => ({ taskId: row.taskId, status: "succeeded" })), limit: 30 });
  const selected = timelines.find((row) => requestUrl.pathname === `/api/kernel/tasks/${row.taskId}/timeline`);
  if (selected) return Response.json(selected);
  if (requestUrl.pathname === "/api/project-agent-bus") return Response.json({ events: [], activeAgentCount: 4, updatedAt: stamp });
  if (requestUrl.pathname === "/api/sessions/fixture-source") return Response.json(source);
  const sourceAgent = [...agents.keys()].find((id) => requestUrl.pathname === `/api/sessions/session-${id}`);
  if (sourceAgent) return Response.json({ id: `session-${sourceAgent}`, agentId: sourceAgent, messages: [], ledgerSeq: 0 });
  return Response.json({ detail: "No synthetic response for this endpoint" }, { status: 404 });
};
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
client.setQueryData(queryKeys.session(source.id), source);
client.setQueryData(queryKeys.agents(), [...agents.values()]);
function Verification() {
  const route = useChatRouteSelection(), center = route.selection.kind === "project_bus";
  const [draft, setDraft] = useState("这是一份还没发送的草稿"), [broadcast, setBroadcast] = useState("");
  const [interrupt, setInterrupt] = useState(false), [dark, setDark] = useState(false);
  return <div className={styles.frame} data-route-session-id={route.selection.kind === "session" ? route.selection.sessionId : ""}>
    <aside className={styles.sidebar}>
      <AgentMessageChatRail lang="zh" sessionId={center ? null : source.id} agentsById={agents}><VButton onPress={() => route.openSession(source.id)}>保留当前对话</VButton></AgentMessageChatRail>
      <footer className={styles.footer}><span>隔离验收 · 合成数据</span>
        <VButton onPress={() => { timelines.unshift(event(`new-${timelines.length}`, "新增发送记录", ["tester"])); void client.invalidateQueries({ queryKey: queryKeys.agentMessageDirectory(30) }); }}>新增发送</VButton>
        <VButton onPress={() => { document.documentElement.dataset.theme = dark ? "light" : "dark"; setDark(!dark); }}>{dark ? "浅色" : "深色"}</VButton>
      </footer>
    </aside>
    <main className={styles.main} data-testid="native-message-main">
      {center ? <ChatProjectBusSurface lang="zh" projectBusTimeline={null} projectBusEvents={[]} projectBusDraft={broadcast} projectBusInterruptTargets={interrupt} projectBusRefreshing={false} projectBusRefreshError="" projectBusSendPending={false} projectBusRevokePending={false} projectBusInitialLoading={false} groupRoomActionError="" userDisplayName="你" chatMentionTargets={[]} formatTime={(value) => value}
        onProjectBusDraftChange={setBroadcast} onProjectBusInterruptTargetsChange={setInterrupt} onRefreshProjectBus={() => undefined} onSendProjectBusMessage={() => undefined} onRevokeProjectBusMessage={() => undefined} onOpenMentionTarget={() => undefined} />
        : <ConversationView sessionId={source.id} title="保留当前对话" phase="ready" messages={source.messages} assistantDisplayName="个人助理" assistantAvatarFallback="助" showHeader={false} showSessionOverview={false} processDisplayMode="trace" autoScrollToLatest={false}
          composerValue={draft} composerPlaceholder="保留当前草稿" composerDisabled={false} composerPending={false} defaultFileContext="workspace" onComposerChange={setDraft} onSubmit={() => undefined} onStop={() => undefined} />}
    </main>
  </div>;
}
document.documentElement.dataset.theme = "light";
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/chat?session=fixture-source"]}><VuiProvider><Verification /></VuiProvider></MemoryRouter></QueryClientProvider>);
