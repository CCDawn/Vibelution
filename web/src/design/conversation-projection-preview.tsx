/** Deterministic inputs rendered by the production ConversationView, without a product session. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import type { ConversationMessage, SessionTurnItem } from "../api/types";
import { queryKeys } from "../api/queryKeys";
import { dictionary } from "../i18n/dictionary";
import { ConversationView } from "../components/conversation/ConversationView";
import { ActiveTurnStreamStateContext } from "../components/conversation/activeTurnStreamState";
import { VButton, VuiProvider } from "../components/vui";
import styles from "./conversation-projection-preview.styles";
import { MatchedConversationReplay } from "./conversation-matched-replay";
import "./tokens.css";
import "./base.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";

const sessionId = "visual-conversation";
const turnId = "visual-turn";
const timestamp = "2026-11-01T09:00:00Z";
const scenes = ["running", "waiting", "disconnected", "background", "completed", "failed", "stopped"] as const;
type Scene = typeof scenes[number];
const labels: Record<Scene, string> = { running: "并行运行", waiting: "等待输出", disconnected: "连接恢复", background: "后台任务", completed: "已结束", failed: "具体错误", stopped: "已停止" };
const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
// Preview chrome needs only local language/labels; do not bootstrap product auth.
client.setQueryData(queryKeys.configPublic(), { language: "zh" });
client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

function items(scene: Scene, assistantTools = false): SessionTurnItem[] {
  const running = scene === "running" || scene === "disconnected" || scene === "stopped";
  const base = { version: 3 as const, sessionId, turnId, revision: 1 };
  const assistantCalls: SessionTurnItem[] = [
    ["source_read", { path: "web/src/components/conversation/ConversationView.tsx" }],
    ["source_read", { path: "web/src/components/conversation/ConversationToolActivity.tsx" }],
    ["source_search", { query: "process disclosure" }],
    ["session_list", { agentId: "reviewer" }],
    ["dispatch", { agentId: "reviewer", projectId: "design-review" }],
    ["browser_read", { tabId: "preview-tab" }],
    ["agent_update", { agentId: "reviewer" }],
  ].flatMap(([action, args], index) => [
    { ...base, id: `assistant-reason:${index}`, itemId: `assistant-reason-${index}`, type: "reasoning" as const,
      sequence: 10 + index * 2, status: "completed" as const, text: `核对动作 ${index + 1} 的结果。` },
    { ...base, id: `assistant-call:${index}`, itemId: `assistant-call-${index}`, type: "tool_call" as const,
      sequence: 11 + index * 2, callId: `assistant-call-${index}`, toolName: "personal_assistant_action_tool",
      status: running && index >= 4 ? "running" as const : scene === "failed" && index === 4 ? "failed" as const : "completed" as const,
      input: JSON.stringify({ action, ...args as Record<string, unknown> }),
      output: scene === "failed" && index === 4 ? "派遣失败：指定 Agent 当前不可用。" : running && index >= 4 ? undefined : "已完成。" },
  ]);
  return [
    { ...base, id: "reason:1", itemId: "reason", type: "reasoning", sequence: 1, status: "completed", text: "先检查会话投影，再并行核对工具状态。" },
    { ...base, id: "note:1", itemId: "note", type: "agent_message", phase: "commentary", sequence: 2, status: "completed", text: "正在并行检查对话投影和样式。" },
    ...(assistantTools ? assistantCalls : [{
      ...base, id: "read:1", itemId: "read", type: "tool_call", sequence: 3,
      callId: "read-call", toolName: "read_file", status: running ? "running" : scene === "failed" ? "failed" : "completed",
      input: JSON.stringify({ path: "web/src/components/conversation/ConversationView.tsx" }),
      output: scene === "failed" ? "读取失败：测试文件暂不可用。" : running ? undefined : "已读取对话组件。",
    } as SessionTurnItem,
    {
      ...base, id: "search:1", itemId: "search", type: "tool_call", sequence: 4,
      callId: "search-call", toolName: "cli_tool", status: running ? "running" : "completed",
      input: JSON.stringify({ command: "rg border-l web/src/components/conversation" }),
      output: running ? undefined : "已核对状态、过程和错误区域。",
    } as SessionTurnItem]),
    ...(scene === "completed" || scene === "background" ? [{
      ...base, id: "answer:1", itemId: "answer", type: "agent_message" as const,
      phase: "final_answer" as const, sequence: 30, status: "completed" as const,
      text: "这是一组用于核对展示的合成对话。\n\n过程可以展开查看，最终回答独立显示；工具状态由各自的调用结果决定。",
    }] : []),
    ...(scene === "failed" ? [{
      ...base, id: "error:1", itemId: "error", type: "error" as const, sequence: 30,
      status: "failed" as const, code: "VISUAL_FIXTURE_READ_ERROR", text: "测试文件暂不可用，请检查路径后重试。",
    }] : []),
  ];
}

function Preview() {
  const requested = new URLSearchParams(location.search).get("scene");
  const [scene, setScene] = useState<Scene>(scenes.find((value) => value === requested) ?? "running");
  const assistantTools = new URLSearchParams(location.search).get("assistant") === "1";
  const allItems = items(scene, assistantTools);
  const running = scene === "running" || scene === "disconnected";
  const assistant: ConversationMessage = {
    id: "visual-message-live", role: "assistant", turnId, timestamp,
    status: running || scene === "waiting" ? "running" : scene === "failed" ? "failed" : "completed",
    metadata: running ? { kind: "session_live_overlay", turnId } : { turnId },
    turnItems: scene === "waiting" ? [] : running ? allItems.filter((item) => item.itemId === "reason" || item.itemId === "read") : allItems,
  };
  const active = running ? {
    ...assistant, id: "visual-message-active", metadata: { kind: "session_active_turn_layer", turnId },
    turnItems: allItems.filter((item) => item.itemId !== "reason" && item.itemId !== "read"),
  } : undefined;
  return (
    <main className={styles.page}>
      <nav aria-label="展示验证场景" className={styles.controls}>
        {scenes.map((value) => <VButton key={value} onPress={() => {
          history.replaceState(null, "", `?scene=${value}${assistantTools ? "&assistant=1" : ""}`);
          setScene(value);
        }}>{labels[value]}</VButton>)}
        <span className={styles.caption}>合成数据 · 真实对话组件 · 不连接产品会话</span>
      </nav>
      <section className={styles.proof} data-testid="conversation-proof" data-scene={scene}>
        <ActiveTurnStreamStateContext.Provider value={{ streamConnected: scene !== "disconnected", streamDisconnectedSinceMs: Date.parse("2026-11-01T09:00:08Z"), reconnectSessionStream: () => undefined }}>
        <ConversationView
          sessionId={sessionId} title="对话展示核对" phase={running || scene === "waiting" ? "responding" : "ready"}
          messages={[{ id: "visual-user", role: "user", content: "检查对话展示，保留具体错误和每个工具的真实状态。", timestamp }, assistant]}
          activeTurnMessage={active} assistantDisplayName="个人助理" assistantAvatarFallback="助"
          showHeader={false} showSessionOverview={false} showComposer={false} processDisplayMode="trace"
          autoScrollToLatest={false} composerValue="" composerPlaceholder="" composerDisabled={false} composerPending={false}
          defaultFileContext="workspace" onComposerChange={() => undefined} onSubmit={() => undefined}
          onStop={() => undefined}
        />
        </ActiveTurnStreamStateContext.Provider>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}><MemoryRouter><VuiProvider>{new URLSearchParams(location.search).get("matched") === "1"
    ? <MatchedConversationReplay /> : <Preview />}</VuiProvider></MemoryRouter></QueryClientProvider>,
);
