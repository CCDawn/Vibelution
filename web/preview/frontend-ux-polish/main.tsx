import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { VButton, VuiProvider } from "../../src/components/vui";
import { queryKeys } from "../../src/api/queryKeys";
import { AgentsPreview } from "./AgentsPreview";
import { ControlsPreview } from "./ControlsPreview";
import { MemoryPreview } from "./MemoryPreview";
import { ModelsPreview } from "./ModelsPreview";
import { TeamsPreview, launchFixture, PREVIEW_TEAM_ID } from "./TeamsPreview";
import { createPreviewFetch } from "./previewApiFixture";
import "./preview.css";

// This origin is an isolated fixture: never forward a request to the shared runtime.
window.fetch = createPreviewFetch(window.location.href, launchFixture);

const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false } } });
client.setQueryData(queryKeys.configPublic(), { language: "zh" });
client.setQueryData(queryKeys.researchWorkflowLaunchOptions(launchFixture.workflowId, PREVIEW_TEAM_ID), launchFixture);

const tabs = [
  { id: "teams", label: "团队选题" }, { id: "agents", label: "Agent 导航" },
  { id: "memory", label: "记忆归属" }, { id: "models", label: "模型库" }, { id: "controls", label: "工具与输入区" },
] as const;
type TabId = typeof tabs[number]["id"];

function App() {
  const [active, setActive] = useState<TabId>(() => {
    const candidate = new URLSearchParams(window.location.search).get("view");
    return tabs.find((tab) => tab.id === candidate)?.id ?? "teams";
  });
  const content = active === "teams" ? <TeamsPreview /> : active === "agents" ? <AgentsPreview />
    : active === "memory" ? <MemoryPreview /> : active === "models" ? <ModelsPreview /> : <ControlsPreview />;
  return <div className="ux-preview"><header className="ux-preview-bar"><span>隔离验收 · 全部为模拟数据</span>
    <nav aria-label="前端修复预览"><VButton density="compact" variant="ghost" onClick={() => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
    }}>切换主题</VButton>{tabs.map((tab) => <VButton key={tab.id} density="compact" variant={active === tab.id ? "primary" : "secondary"}
      aria-pressed={active === tab.id} onClick={() => setActive(tab.id)}>{tab.label}</VButton>)}</nav>
  </header><main className="ux-preview-content">{content}</main></div>;
}

const root = createRoot(document.getElementById("root")!);
root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/agents"]}><VuiProvider><App /></VuiProvider></MemoryRouter></QueryClientProvider>);
if (import.meta.hot) import.meta.hot.dispose(() => { root.unmount(); client.clear(); });
