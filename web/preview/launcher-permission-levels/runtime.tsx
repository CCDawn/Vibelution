/** Actual Launcher route, isolated mock IPC. Never connects to a product host. */
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LauncherAssistantEmbeddedRoute } from "../../src/routes/desktopPet/LauncherAssistantRoute";
import { VuiProvider } from "../../src/components/vui";
import { queryKeys } from "../../src/api/queryKeys";
import { dictionary } from "../../src/i18n/dictionary";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

window.fetch = async () => { throw new Error("Isolated fixture: HTTP is disabled"); };
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
client.setQueryData(queryKeys.configPublic(), { language: "zh" });
client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
client.setQueryData(["i18n", "dictionary-domains", "chat,core"], dictionary);
const scene = new URLSearchParams(location.search).get("state");
let permission = { preset: "request_approval", revision: 0 };
let failedOnce = false;
const sessionId = "permission-runtime-fixture";
const bridge = {
  async invoke(request: { operation: string; [key: string]: unknown }) {
    switch (request.operation) {
      case "status": return {
        assistant: { agentId: "fixture-assistant", directSessionId: sessionId, displayName: "个人助理" },
        settings: { ok: true, verified: true, modelId: "fixture-model", modelChoices: [], displayName: "个人助理",
          preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
          ...(scene === "old-host" ? {} : { managementPermission: { ...permission } }) },
      };
      case "detail": return { id: sessionId, agentId: "fixture-assistant", status: scene === "busy" ? "running" : "ready", messages: [
        { id: "fixture-user", role: "user", content: "帮我创建资料搜集团队。", timestamp: "2026-11-03T00:00:00Z" },
      ] };
      case "config": return { language: "zh" };
      case "curation": return { sessionId, items: [] };
      case "dispatches": return { dispatches: [] };
      case "approvals": return [];
      case "setManagementPermissionPreset": {
        if (scene === "error" && !failedOnce) { failedOnce = true; throw new Error("ASSISTANT_PERMISSION_UNAVAILABLE"); }
        if (request.expectedRevision !== permission.revision) throw new Error("ASSISTANT_PERMISSION_CONFLICT");
        if (permission.preset !== request.preset) permission = { preset: String(request.preset), revision: permission.revision + 1 };
        return { ...permission };
      }
      default: throw new Error(`Isolated fixture refuses ${request.operation}`);
    }
  },
};
Object.assign(globalThis, { vibelutionLauncherAssistant: bridge });
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={client}><VuiProvider>
  <main className="permission-preview">
    <header className="permission-preview-heading"><strong>正式 Launcher 组件</strong><span>隔离验收 · 所有接口为模拟</span></header>
    <div className="permission-preview-conversation"><LauncherAssistantEmbeddedRoute /></div>
  </main>
</VuiProvider></QueryClientProvider>);
