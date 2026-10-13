import { useEffect, useState, type ReactNode } from "react";
import { Activity, ArrowLeft, ChevronRight, Copy, Folder, GitBranch, Monitor } from "lucide-react";
import type { LauncherBranchInstance } from "../api/launcher";
import { VButton, VChip, VRouteLinkButton, VSurface, VTabs } from "../components/vui";
import { formatBackendStatus, formatFrontendStatus, formatGitStatus, instanceRuntimeState, instanceRuntimeStateLabel, instanceWindowOpen, type LifecyclePendingInput } from "./LauncherBranchInstancesPanel.model";
import { copyLauncherRegistryDiagnostics } from "./launcherRegistryDiagnostics";
import styles from "./LauncherBranchDetailPanel.styles";

export function launcherBranchDisplayName(item: LauncherBranchInstance): string {
  return item.branch || (item.shortName || item.id).replace(/^(branch\+|retired\+)/, "");
}

function Facts({ items }: { items: Array<[string, ReactNode]> }) {
  return <dl className={styles.facts}>{items.map(([label, value]) => <div key={label} className={styles.fact}><dt className={styles.factLabel}>{label}</dt><dd className={styles.factValue}>{value}</dd></div>)}</dl>;
}

export function LauncherBranchDetailPanel({ item, zh, pending, actions, onBack }: { item: LauncherBranchInstance; zh: boolean; pending?: LifecyclePendingInput; actions: ReactNode; onBack: () => void }) {
  const [tab, setTab] = useState("overview");
  const [fullPath, setFullPath] = useState(false);
  const [copyNotice, setCopyNotice] = useState("");
  useEffect(() => { setTab("overview"); setFullPath(false); setCopyNotice(""); }, [item.id]);
  const state = instanceRuntimeState(item, pending);
  const path = item.path || item.displayPath || "—";
  const shortPath = item.displayPath || path.replace(/\\/g, "/").split("/").filter(Boolean).slice(-2).join(" / ");
  const error = item.runtime.error;
  async function copyPath() {
    try {
      await copyLauncherRegistryDiagnostics(path);
      setCopyNotice(zh ? "工作区路径已复制。" : "Workspace path copied.");
    } catch {
      setFullPath(true);
      setCopyNotice(zh ? "复制未完成，已展开完整路径，可选中文本复制。" : "Copy unavailable. Select the expanded path to copy it.");
    }
  }
  return <div className={styles.root}>
    <div className={styles.breadcrumb}><span>Vibelution</span><ChevronRight size={13} aria-hidden="true" /><VButton variant="ghost" className={styles.breadcrumbButton} onPress={onBack}>{zh ? "分支" : "Branches"}</VButton><ChevronRight size={13} aria-hidden="true" /><span>{zh ? "详情" : "Details"}</span></div>
    <VButton variant="ghost" icon={<ArrowLeft size={14} />} className={styles.backButton} onPress={onBack}>{zh ? "返回分支列表" : "Back to branches"}</VButton>
    <div className={styles.headingRow}>
      <div className={styles.title}><span className={styles.branchIcon}><GitBranch size={20} aria-hidden="true" /></span><div className={styles.titleBody}>
        <h1 className={styles.heading}>{launcherBranchDisplayName(item)}</h1>
        <div className={styles.metadata}><VChip className={styles.statusChip} tone={state === "running" ? "success" : state === "failed" ? "danger" : state === "partial" ? "warning" : state === "stopped" ? "neutral" : "info"}>{instanceRuntimeStateLabel(state, zh)}</VChip><span>{item.current ? (zh ? "主工作区" : "Main workspace") : (zh ? "独立工作区" : "Isolated workspace")}</span></div>
      </div></div>
      <div className={styles.actions}>{actions}</div>
    </div>
    <VTabs className={styles.tabs} listClassName={styles.tabList} triggerClassName={styles.tabTrigger} aria-label={zh ? "分支详情" : "Branch details"} value={tab} onValueChange={setTab} items={[{ id: "overview", label: zh ? "概览" : "Overview" }, { id: "startup", label: zh ? "启动信息" : "Startup" }]} />
    <div className={styles.content}>
      {error && tab === "overview" ? <div role="status" className={styles.errorBox}><Activity size={17} className={styles.errorIcon} aria-hidden="true" /><p className={styles.errorMessage}>{error.message || error.code}</p><VButton variant="ghost" onPress={() => setTab("startup")}>{zh ? "查看原因" : "View reason"}</VButton></div> : null}
      {tab === "overview" ? <div className={styles.sections}>
        <VSurface tone="panel" padding="normal" className={styles.information}>
          <h2 className={styles.sectionHeading}><Monitor size={16} aria-hidden="true" />{zh ? "运行情况" : "Runtime"}</h2>
          <p className={styles.hint}>{zh ? "工作台、服务与构建状态" : "Workbench, services and build status"}</p>
          <Facts items={[
            [zh ? "运行状态" : "Runtime", instanceRuntimeStateLabel(state, zh)],
            [zh ? "窗口状态" : "Window", instanceWindowOpen(item) ? (zh ? "已打开" : "Open") : (zh ? "未打开" : "Closed")],
            [zh ? "后端" : "Backend", formatBackendStatus(item, zh)],
            [zh ? "前端" : "Frontend", formatFrontendStatus(item, zh)],
          ]} />
          {state === "stopped" ? <p className={styles.footnote}>{zh ? "工作区文件已保留，可随时重新启动。" : "Workspace files are retained and can be started again."}</p> : null}
        </VSurface>
        <VSurface tone="panel" padding="normal" className={styles.information}>
          <h2 className={styles.sectionHeading}><Folder size={16} aria-hidden="true" />{zh ? "工作区信息" : "Workspace"}</h2>
          <p className={styles.hint}>{zh ? "本地目录与当前代码版本" : "Local directory and code revision"}</p>
          <Facts items={[
            [zh ? "类型" : "Type", item.current ? (zh ? "主工作区" : "Main workspace") : (zh ? "任务分支" : "Task branch")],
            ["Git", formatGitStatus(item, zh)],
            [zh ? "提交" : "Commit", <code className={styles.code}>{item.head || "—"}</code>],
          ]} />
          <div className={styles.path}><div className={styles.pathHeading}><span>{zh ? "工作区路径" : "Workspace path"}</span><VButton variant="ghost" isIconOnly aria-label={zh ? "复制工作区路径" : "Copy workspace path"} title={zh ? "复制路径" : "Copy path"} icon={<Copy size={14} />} onPress={() => void copyPath()} /></div>
            <code title={path} className={fullPath ? styles.pathFull : styles.pathShort}>{fullPath ? path : shortPath}</code>
            <VButton variant="ghost" className={styles.pathToggle} onPress={() => setFullPath(!fullPath)}>{fullPath ? (zh ? "收起完整路径" : "Collapse path") : (zh ? "查看完整路径" : "Show full path")}</VButton>
            {copyNotice ? <p role="status" className={styles.copyNotice}>{copyNotice}</p> : null}
          </div>
        </VSurface>
      </div> : <VSurface tone="panel" padding="normal" className={styles.startup}>
        <h2 className={styles.sectionHeading}>{zh ? "启动信息" : "Startup"}</h2>
        <p>{zh ? "当前阶段" : "Current phase"}：{item.runtime.phase || instanceRuntimeStateLabel(state, zh)}</p>
        {error ? <div role="status" className={styles.errorBox}><div><p className={styles.errorMessage}>{error.message || error.code}</p><p className={styles.errorCode}>{error.code}</p></div></div> : <p className={styles.noError}>{zh ? "当前没有返回启动错误。" : "No startup error was reported."}</p>}
        <VRouteLinkButton to={`/launcher/tools?view=diagnostics&instance=${encodeURIComponent(item.id)}`} variant="secondary">{zh ? "查看运行诊断" : "View diagnostics"}</VRouteLinkButton>
      </VSurface>}
    </div>
  </div>;
}
