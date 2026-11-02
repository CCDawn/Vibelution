import { useRef, useState } from "react";
import { Activity, ArrowDownRight, ArrowUpCircle, Folder, ListTodo, MessageCircle, Settings2, Wrench } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import type { LauncherBranchInstance } from "../api/launcher";
import { returnLauncherToDesktop } from "../api/launcher";
import { VButton, VDropdownMenu, VRouteLinkButton } from "../components/vui";
import { launcherAssistantPanelLabel, launcherAssistantPanelPath, resolveLauncherAssistantPanel } from "./launcherNavigationModel";
import styles from "./LauncherNavigation.styles";

const assistantEntries = [
  ["dialogue", MessageCircle],
  ["tasks", ListTodo],
] as const;
const settingsEntries = [
  { id:"diagnostics", zh:"诊断", en:"Diagnostics", to:"/launcher/tools?view=diagnostics", Icon:Activity },
  { id:"maintenance", zh:"维护", en:"Maintenance", to:"/launcher/tools?view=maintenance", Icon:Wrench },
  { id:"settings", zh:"启动设置", en:"Startup settings", to:"/launcher?view=settings", Icon:Settings2 },
  { id:"updates", zh:"版本更新", en:"Updates", to:"/launcher/updates", Icon:ArrowUpCircle },
] as const;
export function LauncherNavigation({ lang, onNavigate, updateAvailable = false, updateFailed = false }: { lang:"zh"|"en"; items:LauncherBranchInstance[]; onNavigate?:()=>void; updateAvailable?:boolean; updateFailed?:boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const pathname = location.pathname.replace(/\/+$/, "");
  const [returning,setReturning] = useState(false);
  const returnGate = useRef(false);
  const [error,setError] = useState("");
  const assistant = pathname.endsWith("/assistant");
  const assistantPanel = resolveLauncherAssistantPanel(location.search) === "tasks" ? "tasks" : "dialogue";
  const view = new URLSearchParams(location.search).get("view");
  const selected = pathname.endsWith("/updates") ? "updates" : pathname.endsWith("/tools") ? view === "maintenance" ? "maintenance" : "diagnostics" : view === "settings" ? "settings" : "branches";
  async function returnToDesktop() {
    if(returnGate.current) return;
    returnGate.current = true;
    setReturning(true);setError("");
    try { await returnLauncherToDesktop(); } catch(error) { setError(error instanceof Error ? error.message : String(error)); } finally { returnGate.current = false; setReturning(false); }
  }
  return <nav aria-label={lang === "zh" ? "Launcher 功能导航" : "Launcher navigation"} className={styles.root}>
    <div className={styles.scroll}>
      <div className={styles.group} aria-label={lang === "zh" ? "个人助理功能" : "Assistant features"}><p className={styles.groupLabel}>{lang === "zh" ? "个人助理" : "Personal assistant"}</p>
        {assistantEntries.map(([id,Icon]) => <VRouteLinkButton key={id} to={launcherAssistantPanelPath(id)} chrome="shell-nav" aria-current={assistant && assistantPanel === id ? "page" : undefined} className={`${styles.link} ${assistant && assistantPanel === id ? styles.selectedLink : styles.idleLink}`} icon={<Icon size={17} aria-hidden="true"/>} onClick={onNavigate}>{launcherAssistantPanelLabel(id,lang)}</VRouteLinkButton>)}
      </div>
      <div className={styles.group}><p className={styles.groupLabel}>Launcher</p><VRouteLinkButton to="/launcher" chrome="shell-nav" aria-current={!assistant && selected === "branches" ? "page" : undefined} className={`${styles.link} ${!assistant && selected === "branches" ? styles.selectedLink : styles.idleLink}`} icon={<Folder size={17} aria-hidden="true"/>} onClick={onNavigate}>{lang === "zh" ? "项目与分支" : "Projects & branches"}</VRouteLinkButton></div>
    </div>
    <div className={styles.footer}>
      {updateAvailable || updateFailed ? <VRouteLinkButton to="/launcher/updates" chrome="shell-nav" aria-current={selected === "updates" ? "page" : undefined} className={`${styles.link} ${styles.updateLink} ${selected === "updates" ? styles.selectedLink : styles.idleLink}`} icon={<ArrowUpCircle size={17} aria-hidden="true"/>} trailingIcon={<span className={styles.updateBadge}>{updateFailed ? (lang === "zh" ? "失败" : "Failed") : (lang === "zh" ? "有新版" : "New")}</span>} onClick={onNavigate}>{lang === "zh" ? "更新" : "Update"}</VRouteLinkButton> : null}
      <VDropdownMenu side="top" align="start" aria-label={lang === "zh" ? "设置" : "Settings"}
      trigger={<VButton variant="ghost" className={styles.returnButton} aria-current={!assistant && selected !== "branches" && !(selected === "updates" && (updateAvailable || updateFailed)) ? "page" : undefined} icon={<Settings2 size={16} aria-hidden="true" />}>{lang === "zh" ? "设置" : "Settings"}</VButton>}
      items={settingsEntries.map(({ id, zh, en, to, Icon }) => ({ id, label: lang === "zh" ? zh : en, icon: <Icon size={16} />, onSelect: () => { navigate(to); onNavigate?.(); } }))} />
      <VButton variant="ghost" className={styles.returnButton} icon={<ArrowDownRight size={16}/>} isPending={returning} onClick={() => void returnToDesktop()}>{lang === "zh" ? "回到桌面" : "Return to desktop"}</VButton>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
    </div>
  </nav>;
}
