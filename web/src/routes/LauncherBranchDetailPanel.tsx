import { useState, type ReactNode } from "react";
import type { LauncherBranchInstance } from "../api/launcher";
import { VButton, VRouteLinkButton, VTabs } from "../components/vui";
import { formatBackendStatus, formatFrontendStatus, formatGitStatus, instanceRuntimeState, instanceRuntimeStateLabel, instanceWindowOpen, type LifecyclePendingInput } from "./LauncherBranchInstancesPanel.model";

export function launcherBranchDisplayName(item: LauncherBranchInstance): string {
  return item.branch || (item.shortName || item.id).replace(/^(branch\+|retired\+)/, "");
}

export function LauncherBranchDetailPanel({ item, zh, pending, actions, onBack }: { item: LauncherBranchInstance; zh: boolean; pending?: LifecyclePendingInput; actions: ReactNode; onBack: () => void }) {
  const [tab, setTab] = useState("overview");
  const state = instanceRuntimeState(item, pending);
  const facts = [
    [zh ? "运行状态" : "Runtime", instanceRuntimeStateLabel(state, zh)],
    [zh ? "窗口状态" : "Window", instanceWindowOpen(item) ? (zh ? "已打开" : "Open") : (zh ? "未打开" : "Closed")],
    [zh ? "工作区路径" : "Workspace", item.path || item.displayPath || "—"],
    [zh ? "后端" : "Backend", formatBackendStatus(item, zh)],
    [zh ? "前端" : "Frontend", formatFrontendStatus(item, zh)],
    ["Git", formatGitStatus(item, zh)],
    [zh ? "提交" : "Commit", item.head || "—"],
  ];
  return <div className="flex min-h-0 flex-1 flex-col px-7 py-4 max-[640px]:px-4">
    <VButton variant="ghost" className="mb-4 !px-0" onPress={onBack}>{zh ? "← 返回分支列表" : "← Back to branches"}</VButton>
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3"><h2 className="m-0 min-w-0 break-all text-lg font-semibold">{launcherBranchDisplayName(item)}</h2>{actions}</div>
    <VTabs aria-label={zh ? "分支详情" : "Branch details"} value={tab} onValueChange={setTab} items={[{ id: "overview", label: zh ? "概览" : "Overview" }, { id: "startup", label: zh ? "启动信息" : "Startup" }]} />
    <div className="min-h-0 flex-1 overflow-auto pt-5">
      {tab === "overview" ? <dl className="m-0 grid grid-cols-[100px_minmax(0,1fr)] gap-x-5 gap-y-4 text-vui-sm">{facts.map(([label, value]) => <div key={label} className="contents"><dt className="text-vui-fg-secondary">{label}</dt><dd className="m-0 break-all">{value}</dd></div>)}</dl> : <div className="space-y-4 text-vui-sm">
        <p>{zh ? "当前阶段" : "Current phase"}：{item.runtime.phase || instanceRuntimeStateLabel(state, zh)}</p>
        {item.runtime.error ? <div role="status" className="rounded-md border border-vui-border-subtle p-4"><p className="m-0 text-[var(--state-error)]">{item.runtime.error.message || item.runtime.error.code}</p><p className="mb-0 mt-2 text-vui-xs text-vui-fg-secondary">{item.runtime.error.code}</p></div> : <p className="text-vui-fg-secondary">{zh ? "当前没有返回启动错误。" : "No startup error was reported."}</p>}
        <VRouteLinkButton to={`/launcher/tools?view=diagnostics&instance=${encodeURIComponent(item.id)}`} variant="secondary">{zh ? "查看运行诊断" : "View diagnostics"}</VRouteLinkButton>
      </div>}
    </div>
  </div>;
}
