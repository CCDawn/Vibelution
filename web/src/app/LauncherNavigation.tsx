import styles from "./LauncherNavigation.styles";
import { Activity, Box, GitBranch, Settings2, Wrench } from "lucide-react";
import { useLocation } from "react-router-dom";
import type { LauncherBranchInstance } from "../api/launcher";
import { VRouteLinkButton } from "../components/vui";
import { instanceRuntimeState } from "../routes/LauncherBranchInstancesPanel.model";

/** Stable destinations; lifecycle operations remain owned by their existing routes. */
export function LauncherNavigation({ lang, items }: { lang: "zh" | "en"; items: LauncherBranchInstance[] }) {
  const location = useLocation();
  const view = new URLSearchParams(location.search).get("view");
  const selected = location.pathname.endsWith("/tools") ? (view === "maintenance" ? "maintenance" : "diagnostics") : view === "settings" ? "settings" : "branches";
  const links = [
    { id: "branches", label: lang === "zh" ? "分支" : "Branches", to: "/launcher", Icon: Box },
    { id: "diagnostics", label: lang === "zh" ? "诊断" : "Diagnostics", to: "/launcher/tools?view=diagnostics", Icon: Activity },
    { id: "maintenance", label: lang === "zh" ? "维护" : "Maintenance", to: "/launcher/tools?view=maintenance", Icon: Wrench },
    { id: "settings", label: lang === "zh" ? "设置" : "Settings", to: "/launcher?view=settings", Icon: Settings2 },
  ];
  const running = items.filter((item) => instanceRuntimeState(item) === "running").length;
  return <nav aria-label={lang === "zh" ? "Launcher 功能导航" : "Launcher navigation"} className={styles.root}>
    <div className={styles.project}><p className={styles.projectLabel}>{lang === "zh" ? "本地项目" : "Local project"}</p><p className={styles.projectName}><GitBranch size={16} aria-hidden="true" />Vibelution</p></div>
    {links.map(({ id, label, to, Icon }) => <div key={id} className={id === "settings" ? styles.settingsItem : ""}>
      {id === "settings" ? <p className={styles.runningCount}>{lang === "zh" ? `本地运行 · ${running} 个工作区` : `${running} running workspaces`}</p> : null}
      <VRouteLinkButton to={to} chrome="shell-nav" aria-current={selected === id ? "page" : undefined} className={`${styles.link} ${selected === id ? styles.selectedLink : styles.idleLink}`} icon={<Icon size={17} aria-hidden="true" />}>{label}</VRouteLinkButton>
    </div>)}
  </nav>;
}
