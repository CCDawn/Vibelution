import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { VuiProvider } from "../../src/components/vui/VuiProvider";
import { VButton } from "../../src/components/vui";
import { ChatCenterTabStrip } from "../../src/routes/chat/ChatCenterTabStrip";
import { ChatTokenSpeedIndicator } from "../../src/routes/chat/ChatTokenSpeedIndicator";
import { ActiveTurnLayersStoreProvider, createActiveTurnLayersStore } from "../../src/routes/chat/activeTurnLayersStore";
import type { ActiveTurnLayerState } from "../../src/routes/chatActiveTurnLayer";
import styles from "../../src/routes/ChatCodingRoute.styles";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "./preview.tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "../../src/design/workbench-frame.css";

function App() {
  const store = useMemo(createActiveTurnLayersStore, []);
  const [mode, setMode] = useState("等待输出");
  const [session, setSession] = useState("s1");
  const [light, setLight] = useState(false);
  useEffect(() => { document.documentElement.dataset.theme = light ? "light" : "dark"; }, [light]);
  useEffect(() => {
    let count = 100;
    const push = () => {
      const layer: ActiveTurnLayerState = { id: "live", sessionId: session, turnId: "t", status: mode === "完成" ? "completed" : "running",
        updatedAt: "", ledgerSeq: count, turnItems: mode === "等待输出" ? [] : [{ id: "text", itemId: "text", version: 3,
          sessionId: session, turnId: "t", revision: count, sequence: 1, status: "running", type: "agent_message", phase: "final_answer", text: "文".repeat(count) }] };
      if (mode === "工具执行") layer.turnItems.push({ id: "tool", itemId: "tool", version: 3, sessionId: session, turnId: "t", revision: 1,
        sequence: 2, status: "running", type: "tool_call", callId: "c", toolName: "example", output: "不计入速度" });
      store.setActiveTurnLayersBySession({ [session]: layer });
    };
    push();
    if (mode !== "连续输出") return;
    const timer = window.setInterval(() => { count += 4; push(); }, 100);
    return () => window.clearInterval(timer);
  }, [mode, session, store]);
  return <ActiveTurnLayersStoreProvider store={store}>
    <main className="min-h-screen bg-vui-surface-chat text-[var(--fg-primary)]">
      <ChatCenterTabStrip styles={styles} lang="zh" agentSessionLabel="当前会话" chatReturnTarget={null} chatReturnLabel=""
        groupPanelActive={false} projectBusActive={false} showSessionTabs={false} showAgentFallbackTab workspaceActiveTab="agent"
        sessionTabs={null} fileTabs={null} leftOverlayVisible rightOverlayVisible statusRailAvailable={false}
        conversationIndexOverlayOpen={false} statusRailOverlayOpen={false}
        onActivateAgentFallbackTab={() => {}} onToggleLeftOverlay={() => {}} onToggleRightOverlay={() => {}}
        tokenSpeedControl={<ChatTokenSpeedIndicator key={session} sessionId={session} lang="zh"/>}
        sessionBrowserControl={<VButton variant="ghost" density="compact">会话</VButton>}
        sessionActionsControl={<VButton variant="ghost" density="compact">更多</VButton>}/>
      <div className="mx-auto max-w-3xl space-y-5 p-5">
        <p>真实顶栏组件 · 确定性模拟流 · 无模型请求</p>
        <div className="flex flex-wrap gap-2">{["等待输出", "连续输出", "暂停输出", "工具执行", "完成"].map(value =>
          <VButton key={value} onPress={() => setMode(value)}>{value}</VButton>)}</div>
        <div className="flex flex-wrap gap-2">
          <VButton onPress={() => setSession(current => current === "s1" ? "s2" : "s1")}>切换会话</VButton>
          <VButton onPress={() => setLight(current => !current)}>切换主题</VButton>
        </div>
        <p>当前：{mode} · {session}</p>
        <p>顶栏仅保留速度表与速度。无输出显示 —；连续输出约 ≈40.0 tok/s。</p>
      </div>
    </main>
  </ActiveTurnLayersStoreProvider>;
}
createRoot(document.getElementById("root")!).render(<VuiProvider><App/></VuiProvider>);
