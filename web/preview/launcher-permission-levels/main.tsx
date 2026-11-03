/** Isolated real-component preview. All choices, saves and actions are simulated. */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConversationView } from "../../src/components/conversation/ConversationView";
import { PermissionControl } from "./PermissionControl";
import { VConfirmDialog, VuiProvider } from "../../src/components/vui";
import { LauncherAssistantModelControl } from "../../src/routes/desktopPet/LauncherAssistantModelControl";
import { ChatComposerPlusMenu } from "../../src/routes/chat/ChatComposerPlusMenu";
import { queryKeys } from "../../src/api/queryKeys";
import type { AgentPermissionPreset, ConversationMessage } from "../../src/api/types";
import type { ConversationViewProps } from "../../src/components/conversation/conversationViewTypes";
import { dictionary } from "../../src/i18n/dictionary";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

// No live bridge is installed, and the fixture refuses every backend request.
window.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  throw new Error(`Preview has no backend transport: ${new URL(url, location.href).pathname} (${init?.method || "GET"})`);
};
const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
const runtimeApi: NonNullable<ConversationViewProps["runtimeApi"]> = {
  cacheKey: "launcher-permission-preview",
  fetchConfigBootstrap: async () => { throw new Error("Preview config is already seeded"); },
  fetchMessageCuration: async () => ({ sessionId: "permission-preview", items: [] }),
  setMessageCuration: async () => { throw new Error("Preview does not write message curation"); },
};
client.setQueryData(queryKeys.configPublic(), { language: "zh" });
client.setQueryData([runtimeApi.cacheKey, "config"], { language: "zh" });
client.setQueryData([runtimeApi.cacheKey, "curation", "permission-preview"], { items: [] });
client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
client.setQueryData(["i18n", "dictionary-domains", "chat,core"], dictionary);

const messages: ConversationMessage[] = [
  { id: "preview-user", role: "user", content: "帮我创建一个资料搜集团队，配置成员并开始收集。", timestamp: "2026-11-03T00:00:00Z" },
  { id: "preview-answer", role: "assistant", turnId: "preview-turn", status: "completed", timestamp: "2026-11-03T00:00:01Z",
    turnItems: [{ id: "preview-answer-item", itemId: "preview-answer-item", version: 3, sessionId: "permission-preview",
      turnId: "preview-turn", revision: 1, sequence: 1, type: "agent_message", phase: "final_answer", status: "completed", terminal: true,
      text: "可以。你可以在输入框下方选择助理的操作权限，之后随时调整。\n\n这只是界面预览，尚未创建团队或执行任何操作。" }] },
];

function App() {
  const scene = new URLSearchParams(location.search).get("state");
  const [permission, setPermission] = useState<AgentPermissionPreset>("auto_review");
  const [fullAccessOpen, setFullAccessOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(scene === "pending");
  const [notice, setNotice] = useState(scene === "error" ? "权限未保存，仍使用当前档位。可重新选择。" : "");
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const unavailable = scene === "unavailable";
  const save = (value: AgentPermissionPreset) => {
    if (value === "full_access") { setFullAccessOpen(true); return; }
    setPending(true); setNotice("");
    window.setTimeout(() => { setPermission(value); setPending(false); }, 350);
  };
  return <VuiProvider><main className="permission-preview">
    <header className="permission-preview-heading"><strong>个人助理</strong><span>对话区局部预览 · 所有操作为模拟</span></header>
    <div className="permission-preview-conversation"><ConversationView runtimeApi={runtimeApi}
      sessionId="permission-preview" title="个人助理" phase="ready" messages={messages}
      showHeader={false} showSessionOverview={false} showMentalSnapshots={false} assistantDisplayName="个人助理"
      defaultFileContext="" density="default" composerVariant="codex" composerValue={draft}
      composerPlaceholder="和个人助理聊一聊…" onComposerChange={setDraft}
      onSubmit={() => setNotice("预览不会发送消息，输入内容已保留。")}
      composerLeadingControl={<ChatComposerPlusMenu lang="zh" showCapabilities={false} showReferences={false}
        attachmentDisabled sessionReferences={[]} />}
      composerModelControl={<LauncherAssistantModelControl lang="zh" modelId="preview-model"
        modelDisplay="DeepSeek V4.1 Flash · 官方" pending={false} selectionDisabled={false}
        onModelChange={() => setNotice("模型切换仅为模拟。")} onOpenSettings={() => setModelSettingsOpen(true)} />}
    /></div>
    <div className="permission-preview-footer" data-preview-permission-footer>
      <div className="permission-preview-footer-row">
        <PermissionControl value={permission}
          disabled={unavailable} pending={pending} onChange={save} />
        <span className="permission-preview-scope">仅 Launcher 助理</span>
      </div>
      {unavailable || notice ? <p className="permission-preview-notice" role="status">{unavailable ? "当前版本暂不支持切换权限，请更新 Launcher。" : notice}</p> : null}
    </div>
    <VConfirmDialog open={fullAccessOpen} onOpenChange={setFullAccessOpen} title="启用完全访问权限？" size="sm"
      description="助理将直接执行已授权项目内的管理操作，包括重启和永久删除。项目及数据访问范围仍按已有授权限制。"
      confirmLabel="启用完全访问" cancelLabel="取消" tone="danger"
      onConfirm={() => { setPermission("full_access"); setFullAccessOpen(false); setNotice(""); }} />
    <VConfirmDialog open={modelSettingsOpen} onOpenChange={setModelSettingsOpen} title="模型设置（模拟）"
      description="正式界面继续使用原有模型设置入口，预览不会打开真实配置。" confirmLabel="知道了"
      onConfirm={() => setModelSettingsOpen(false)} />
  </main></VuiProvider>;
}
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
