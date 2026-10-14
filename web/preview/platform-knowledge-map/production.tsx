import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { VuiProvider, VWorkbenchFrame } from "../../src/components/vui";
import { PlatformKnowledgeGraphWorkbench } from "../../src/routes/memory/PlatformKnowledgeGraphWorkbench";
import "./preview.css";
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={client}><VuiProvider><div className="flex h-dvh flex-col"><p className="shrink-0 border-b border-[var(--vui-border-subtle)] p-2 text-vui-xs text-[var(--fg-secondary)]">正式组件隔离验收 · 仅测试数据</p><div className="min-h-0 flex-1"><VWorkbenchFrame><PlatformKnowledgeGraphWorkbench onAgentView={() => {}} /></VWorkbenchFrame></div></div></VuiProvider></QueryClientProvider>);
