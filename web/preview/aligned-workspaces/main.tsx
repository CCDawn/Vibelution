import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { VButton, VuiProvider, VWorkbenchFrame } from "../../src/components/vui";
import { SkillsRoute } from "../../src/routes/SkillsRoute";
import { MemoryRoute } from "../../src/routes/MemoryRoute";
import type { MemoryRouteView } from "../../src/routes/memory/useMemoryWorkbenchQueries";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../tools-management/preview.tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "../../src/design/workbench-frame.css";

const pages = [
  ["skills", "Skill"], ["personal", "个人记忆"], ["team", "团队记忆"],
  ["library", "整个记忆库"], ["graph", "知识图谱"], ["knowledge", "知识"], ["manage", "记忆管理"], ["cleanup", "清理"],
] as const;
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } });
function Preview() {
  // The real MemoryRoute owns its URL params; preview navigation must not compete with it.
  const [page, setPage] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("page") || "skills";
    return pages.some(([id]) => id === requested) ? requested : "skills";
  });
  return <div className="flex h-dvh min-h-0 min-w-0 flex-col overflow-hidden bg-vui-surface-rail text-vui-fg-primary">
    <header className="flex min-h-11 shrink-0 items-center gap-2 px-2">
      <nav aria-label="验收页面" className="flex min-w-0 flex-1 gap-1 overflow-auto">
        {pages.map(([id, label]) => <VButton key={id} variant="ghost" aria-pressed={page === id}
          className={`shrink-0 !border-transparent !bg-transparent !shadow-none ${page === id ? "!bg-[var(--vui-selection-bg)]" : ""}`}
          onPress={() => setPage(id)}>{label}</VButton>)}
      </nav><span className="whitespace-nowrap text-vui-2xs text-vui-fg-tertiary max-md:hidden">正式组件 · 安全样例 · 写操作禁用</span>
    </header>
    <VWorkbenchFrame>{page === "skills" ? <SkillsRoute/> : <MemoryRoute forcedView={page as MemoryRouteView}/>}</VWorkbenchFrame>
  </div>;
}
const root = createRoot(document.getElementById("root")!);
root.render(<VuiProvider><QueryClientProvider client={queryClient}><BrowserRouter><Preview/></BrowserRouter></QueryClientProvider></VuiProvider>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
