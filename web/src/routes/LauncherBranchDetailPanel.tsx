import styles from "./LauncherBranchDetailPanel.styles";
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
  return <div className={styles.root}>
    <VButton variant="ghost" className={styles.backButton} onPress={onBack}>{zh ? "← 返回分支列表" : "← Back to branches"}</VButton>
    <div className={styles.headingRow}><h2 className={styles.heading}>{launcherBranchDisplayName(item)}</h2>{actions}</div>
    <VTabs aria-label={zh ? "分支详情" : "Branch details"} value={tab} onValueChange={setTab} items={[{ id: "overview", label: zh ? "概览" : "Overview" }, { id: "startup", label: zh ? "启动信息" : "Startup" }]} />
    <div className={styles.content}>
      {tab === "overview" ? <dl className={styles.facts}>{facts.map(([label, value]) => <div key={label} className={styles.fact}><dt className={styles.factLabel}>{label}</dt><dd className={styles.factValue}>{value}</dd></div>)}</dl> : <div className={styles.startup}>
        <p>{zh ? "当前阶段" : "Current phase"}：{item.runtime.phase || instanceRuntimeStateLabel(state, zh)}</p>
        {item.runtime.error ? <div role="status" className={styles.errorBox}><p className={styles.errorMessage}>{item.runtime.error.message || item.runtime.error.code}</p><p className={styles.errorCode}>{item.runtime.error.code}</p></div> : <p className={styles.noError}>{zh ? "当前没有返回启动错误。" : "No startup error was reported."}</p>}
        <VRouteLinkButton to={`/launcher/tools?view=diagnostics&instance=${encodeURIComponent(item.id)}`} variant="secondary">{zh ? "查看运行诊断" : "View diagnostics"}</VRouteLinkButton>
      </div>}
    </div>
  </div>;
}
