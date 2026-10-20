/** Isolated presentation fixture: actual transcript/composer, no live transport. */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ExternalLink, Plus, Sparkles, X } from "lucide-react";
import { VDropdownMenu, VIconButton, VuiProvider } from "../../src/components/vui";
import { ConversationView } from "../../src/components/conversation/ConversationView";
import type { AgentPermissionPreset, ConversationMessage, SessionLlmModelOption } from "../../src/api/types";
import { queryKeys } from "../../src/api/queryKeys";
import { buildComposerContextRingModel } from "../../src/routes/chat/composerContextModel";
import styles from "../../src/routes/desktopPet/DesktopAssistantRoute.styles";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/route-css/desktop-pet.tailwind.css";

const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
client.setQueryData(queryKeys.configPublic(), { language: "zh" });
const modelName = new URLSearchParams(location.search).has("long") ? "deepseek-official-long-model-name-for-window-overflow-check" : "deepseek-flash";
const model: SessionLlmModelOption = { modelId: modelName, modelRef: modelName, label: modelName, model: modelName,
  providerId: "mock", providerLabel: "本地模拟", providerKind: "relay", apiKeyConfigured: true, missingApiKey: false,
  supportsReasoningEffort: false, reasoningEffortValues: [], reasoningEffortOptions: [], defaultReasoningEffort: "", isDefault: true };
const text = "可以，先从最重要的事开始。\n\n1. 先定一件必须完成的事\n2. 把零散的事放到一起处理\n3. 留一点空档，别把一天排满\n\n今天有哪些事在等着你？";
const messages: ConversationMessage[] = [
  { id: "user", role: "user", content: "今天事情有点多，帮我理一理。", timestamp: "2026-10-20T02:24:00Z" },
  { id: "answer", role: "assistant", status: "completed", timestamp: "2026-10-20T02:24:01Z", turnId: "preview",
    turnItems: [{ id: "answer-item", itemId: "answer-item", sessionId: "preview", turnId: "preview", version: 3,
      revision: 1, sequence: 1, type: "agent_message", phase: "final_answer", text, status: "completed", terminal: true }] },
];
const ring = buildComposerContextRingModel({ usageUsed: 3000, usageLimit: 100000, hitPercent: 0, detailAvailable: true, segments: [], lang: "zh" });

function App() {
  const [draft, setDraft] = useState("");
  const [permission, setPermission] = useState<AgentPermissionPreset>("request_approval");
  const scene = new URLSearchParams(location.search).get("state");
  return <VuiProvider><section className={styles.chatWindow} data-assistant-chat="compact" data-expanded="true" style={{ height: "100dvh" }}>
    <header className={styles.chatHeader}>
      <span className={styles.chatAvatar}><Sparkles size={18}/></span>
      <div className={styles.chatIdentity}><h1 className={styles.chatTitle}>个人助理</h1><span className={styles.chatStatus}>本地模拟 · 未连接真实会话</span></div>
      <div className={styles.chatActions}><VIconButton variant="ghost" label="返回工作台（模拟）" icon={<ExternalLink size={14}/>}/><VIconButton variant="ghost" label="关闭聊天（模拟）" icon={<X size={14}/>}/></div>
    </header>
    <div className={styles.chatBody}><ConversationView sessionId="preview" title="个人助理" phase="ready" messages={scene === "empty" || scene === "loading" ? [] : messages}
      transcriptPending={scene === "loading"} showHeader={false} showSessionOverview={false} showMentalSnapshots={false}
      composerVariant="codex" assistantDisplayName="个人助理" defaultFileContext="" composerValue={draft} composerPlaceholder="说点什么，或交给我一件事…"
      composerDisabled={false} composerPending={false} composerError={scene === "error" ? "连接暂时中断，请稍后重试。" : undefined}
      onComposerChange={setDraft} onSubmit={() => setDraft("")}
      composerLeadingControl={<VDropdownMenu trigger={<VIconButton label="更多选项" icon={<Plus size={15}/>} variant="ghost"/>} items={[{ id: "mock", label: "附件与引用（模拟）" }]}/>}
      permissionControl={{ value: permission, onChange: setPermission, disabled: false, pending: false }}
      turnModelControl={{ sessionId: "preview", agentId: "preview-agent", configRevision: 1, model, currentReasoningEffort: "", onSave: () => undefined }}
      composerContextRing={ring}/></div>
  </section></VuiProvider>;
}
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={client}><App/></QueryClientProvider>);
