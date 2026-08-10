import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Plus, X } from "lucide-react";

import { VButton, VSurface } from "../components/vui";
import {
  parseChatSelectionSearch,
  serializeChatSelectionSearch,
  selectChatAgent,
  selectChatRoom,
  selectChatSession,
  type ChatSelectionProjection,
} from "../routes/chat/chatSelectionProjection";
import "./chat-selection-persistence-preview.css";
import { chatSelectionPersistencePreviewStyles as styles } from "./chat-selection-persistence-preview.styles";

type Agent = { id: string; name: string; model: string; sessions: Array<{ id: string; title: string }> };

const agents: Agent[] = [
  { id: "agent-gpt", name: "gpt", model: "Relay GPT-5.6 Luna", sessions: [{ id: "session-gpt", title: "代码审查 · 今天" }, { id: "session-gpt-2", title: "重构讨论 · 昨天" }] },
  { id: "agent-luna", name: "terra", model: "terra GPT-5.6-terra", sessions: [{ id: "session-luna", title: "资料提炼 · 08/08" }, { id: "session-luna-2", title: "实验计划 · 08/07" }] },
  { id: "agent-flash", name: "DeepSeek flash", model: "DeepSeek V4 Flash", sessions: [{ id: "session-flash", title: "快速问答 · 08/06" }] },
];

const initialSelection = parseChatSelectionSearch(window.location.search);

function App() {
  const [selection, setSelection] = useState<ChatSelectionProjection>({
    agentId: initialSelection.agentId ?? "agent-luna",
    sessionId: initialSelection.sessionId ?? "session-luna",
    roomId: initialSelection.roomId ?? null,
    tabId: initialSelection.tabId ?? "agent",
  });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const currentAgent = agents.find((agent) => agent.id === selection.agentId) ?? agents[0];
  const currentSession = currentAgent.sessions.find((session) => session.id === selection.sessionId);
  const projectedSearch = useMemo(() => serializeChatSelectionSearch("?view=chat", selection), [selection]);

  function commit(next: ChatSelectionProjection) {
    setSelection(next);
    window.history.replaceState({}, "", `${window.location.pathname}${serializeChatSelectionSearch("?view=chat", next)}`);
  }

  function refreshWithoutJump() {
    setIsRefreshing(true);
    window.setTimeout(() => setIsRefreshing(false), 700);
  }

  return (
    <main className={styles.selectionPreview}>
      <header className={styles.selectionTopbar}>
        <div>
          <p className={styles.eyebrow}>CHAT · 选择投影预览</p>
          <h1>Agent 与会话切换</h1>
          <p className={styles.subtitle}>选中状态同时投影到 Agent、会话和 Tab；刷新时保持当前项，不回落到第一项。</p>
        </div>
        <div className={styles.topActions}>
          <VButton variant="secondary" density="compact" onPress={refreshWithoutJump} isPending={isRefreshing}>
            模拟后台刷新
          </VButton>
          <span className={styles.sourceChip}>URL 优先 · 本地回退</span>
        </div>
      </header>

      <nav className={styles.conversationTabStrip} aria-label="打开的会话" role="tablist">
        {currentAgent.sessions.map((session) => {
          const active = selection.sessionId === session.id;
          return (
            <div key={session.id} className={[styles.conversationTab, active ? styles.conversationTabActive : ""].join(" ")} data-selected={active ? "true" : "false"}>
              <VButton
                variant="ghost"
                contentLayout="plain"
                className={styles.conversationTabMain}
                role="tab"
                aria-selected={active}
                onPress={() => commit(selectChatSession(selection, session.id, currentAgent.id))}
              >
                <span className={styles.conversationTabIcon} aria-hidden="true">▣</span>
                <span className={styles.conversationTabTitle}>{session.title}</span>
              </VButton>
              <VButton
                variant="ghost"
                contentLayout="plain"
                className={styles.conversationTabClose}
                aria-label={`关闭 ${session.title}`}
                onPress={() => undefined}
              >
                <X size={13} aria-hidden="true" />
              </VButton>
            </div>
          );
        })}
        <VButton
          variant="ghost"
          contentLayout="plain"
          className={styles.conversationTabNew}
          aria-label="新建会话"
          onPress={() => undefined}
        >
          <Plus size={15} aria-hidden="true" />
        </VButton>
      </nav>

      <div className={styles.selectionGrid}>
        <VSurface as="aside" tone="card" elevation="panel" padding="none" className={styles.directoryPanel} aria-label="Agent 目录">
          <div className={styles.panelHeading}><strong>Agent</strong><span>{agents.length}</span></div>
          <div className={styles.rows}>
            {agents.map((agent) => {
              const active = selection.agentId === agent.id;
              return (
                <VButton
                  key={agent.id}
                  variant="ghost"
                  contentLayout="plain"
                  className={[styles.selectionRow, active ? styles.selectionRowActive : ""].join(" ")}
                  aria-current={active ? "page" : undefined}
                  data-selected={active ? "true" : "false"}
                  onPress={() => commit(selectChatAgent(selection, agent.id, agent.sessions[0]?.id))}
                >
                  <span className={styles.avatar}>{agent.name.slice(0, 1).toUpperCase()}</span>
                  <span className={styles.rowCopy}><strong>{agent.name}</strong><small>{agent.model} · {agent.sessions.length} 个会话</small></span>
                  <span className={styles.rowCheck} aria-hidden="true">{active ? "✓" : ""}</span>
                </VButton>
              );
            })}
          </div>
        </VSurface>

        <VSurface as="section" tone="panel" elevation="panel" padding="none" className={styles.sessionPanel} aria-label="会话列表">
          <div className={styles.panelHeading}><strong>{currentAgent.name} 的会话</strong><span>{currentAgent.sessions.length}</span></div>
          <div className={styles.rows}>
            {currentAgent.sessions.map((session) => {
              const active = selection.sessionId === session.id;
              return (
                <VButton
                  key={session.id}
                  variant="ghost"
                  contentLayout="plain"
                  className={[styles.selectionRow, styles.sessionSelectionRow, active ? styles.selectionRowActive : ""].join(" ")}
                  aria-current={active ? "page" : undefined}
                  data-selected={active ? "true" : "false"}
                  onPress={() => commit(selectChatSession(selection, session.id, currentAgent.id))}
                >
                  <span className={styles.sessionMark}>◷</span>
                  <span className={styles.rowCopy}><strong>{session.title}</strong><small>{session.id}</small></span>
                  <span className={styles.rowCheck} aria-hidden="true">{active ? "✓" : ""}</span>
                </VButton>
              );
            })}
          </div>
        </VSurface>

        <VSurface as="section" tone="glass" elevation="panel" padding="normal" className={styles.projectionPanel} aria-label="当前选择投影">
          <p className={styles.eyebrow}>当前持久投影</p>
          <h2>{selection.roomId ? "团队房间" : currentSession?.title ?? currentAgent.name}</h2>
          <dl className={styles.projectionList}>
            <div><dt>Agent</dt><dd>{selection.agentId ?? "—"}</dd></div>
            <div><dt>Session</dt><dd>{selection.sessionId ?? "—"}</dd></div>
            <div><dt>URL</dt><dd>{projectedSearch}</dd></div>
          </dl>
          <div className={styles.tabStrip} role="tablist" aria-label="会话 Tab">
            <VButton variant="secondary" density="compact" role="tab" aria-selected={selection.tabId === "agent"} data-selected={selection.tabId === "agent" ? "true" : "false"} onPress={() => commit({ ...selection, tabId: "agent" })}>Agent 对话</VButton>
            <VButton variant="secondary" density="compact" role="tab" aria-selected={selection.tabId === "files"} data-selected={selection.tabId === "files" ? "true" : "false"} onPress={() => commit({ ...selection, tabId: "files" })}>文件预览</VButton>
          </div>
          <VButton variant="secondary" density="compact" onPress={() => commit(selectChatRoom(selection, "room-research"))}>切换到团队房间</VButton>
          <p className={styles.previewNote}>这是隔离设计预览，未连接正式 API；选中行的灰色洗色、URL 更新和后台刷新保持是本次正式实现契约。</p>
        </VSurface>
      </div>
    </main>
  );
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(<StrictMode><App /></StrictMode>);
}
