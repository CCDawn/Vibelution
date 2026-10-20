import { useEffect, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { VuiProvider } from "../../src/components/vui/VuiProvider";
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
  useEffect(() => {
    const session = "preview-session";
    let count = 100;
    const push = () => {
      const layer: ActiveTurnLayerState = { id: "live", sessionId: session, turnId: "t", status: "running",
        updatedAt: "", ledgerSeq: count, turnItems: [{ id: "text", itemId: "text", version: 3,
          sessionId: session, turnId: "t", revision: count, sequence: 1, status: "running", type: "agent_message", phase: "final_answer", text: "文".repeat(count) }] };
      store.setActiveTurnLayersBySession({ [session]: layer });
    };
    push();
    // Automatic simulated output keeps the presentation free of test controls.
    const timer = window.setInterval(() => { count += 4; push(); }, 100);
    return () => window.clearInterval(timer);
  }, [store]);
  return <ActiveTurnLayersStoreProvider store={store}>
    <main className="min-h-screen bg-vui-surface-chat text-[var(--fg-primary)]">
      <ChatCenterTabStrip styles={styles} lang="zh" agentSessionLabel="当前会话" chatReturnTarget={null} chatReturnLabel=""
        groupPanelActive={false} projectBusActive={false} showSessionTabs={false} showAgentFallbackTab={false} workspaceActiveTab="agent"
        sessionTabs={null} fileTabs={null} leftOverlayVisible rightOverlayVisible statusRailAvailable={false}
        conversationIndexOverlayOpen={false} statusRailOverlayOpen={false}
        onActivateAgentFallbackTab={() => {}} onToggleLeftOverlay={() => {}} onToggleRightOverlay={() => {}}
        tokenSpeedControl={<ChatTokenSpeedIndicator sessionId="preview-session" lang="zh"/>}/>
    </main>
  </ActiveTurnLayersStoreProvider>;
}
createRoot(document.getElementById("root")!).render(<VuiProvider><App/></VuiProvider>);
