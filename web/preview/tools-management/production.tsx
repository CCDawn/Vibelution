import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArrowLeft, Bell, GitBranch, Settings } from "lucide-react";
import { VButton, VIconButton, VWorkbenchFrame } from "../../src/components/vui";
import { VuiProvider } from "../../src/components/vui/VuiProvider";
import { ToolsRoute } from "../../src/routes/ToolsRoute";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "./preview.tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "../../src/design/workbench-frame.css";

const quiet = "!border-transparent !bg-none !bg-transparent !shadow-none";
const queryClient = new QueryClient({defaultOptions:{queries:{retry:false}}});
createRoot(document.getElementById("root")!).render(<VuiProvider><QueryClientProvider client={queryClient}><BrowserRouter><div className="flex h-dvh min-h-0 min-w-0 flex-col overflow-hidden bg-vui-surface-rail text-vui-fg-primary"><header className="flex h-11 shrink-0 items-center gap-2 px-2"><VIconButton label="返回" className={quiet} icon={<ArrowLeft size={16}/>}/><nav className="flex min-w-0 flex-1 gap-1 overflow-auto">{["对话","智能体","团队","进化","记忆库","Agent 管理"].map(label=><VButton variant="ghost" className={`${quiet} shrink-0 ${label==="Agent 管理" ? "!bg-[var(--vui-selection-bg)]" : ""}`} key={label}>{label}</VButton>)}</nav><span className="mr-2 whitespace-nowrap text-vui-2xs text-vui-fg-tertiary max-md:hidden">正式组件 · 只读验收</span><div className="flex max-md:hidden"><VIconButton label="变更" icon={<GitBranch size={16}/>} className={quiet}/><VIconButton label="通知" icon={<Bell size={16}/>} className={quiet}/><VIconButton label="设置" icon={<Settings size={16}/>} className={quiet}/></div></header><VWorkbenchFrame><ToolsRoute/></VWorkbenchFrame></div></BrowserRouter></QueryClientProvider></VuiProvider>);
