import { useRef, useState } from "react";
import { Activity, ArrowDownRight, ArrowUpCircle, CalendarDays, Folder, LayoutDashboard, ListTodo, MessageCircle, Monitor, Palette, Settings2, ShieldCheck, SlidersHorizontal, Wrench } from "lucide-react";
import { useLocation } from "react-router-dom";
import type { LauncherBranchInstance } from "../api/launcher";
import { returnLauncherToDesktop } from "../api/launcher";
import { VButton, VRouteLinkButton } from "../components/vui";
import { launcherAssistantPanelLabel, launcherAssistantPanelPath, resolveLauncherAssistantPanel, type LauncherAssistantPanel } from "./launcherNavigationModel";
import styles from "./LauncherNavigation.styles";

const assistantEntries = [
  ["dialogue", MessageCircle], ["overview", LayoutDashboard], ["affairs", CalendarDays], ["dispatches", ListTodo],
  ["computer", Monitor], ["preferences", SlidersHorizontal], ["assistant-settings", Palette],
] as const;
const launcherEntries = [
  { id:"branches", zh:"项目与分支", en:"Projects & branches", to:"/launcher", Icon:Folder },
  { id:"diagnostics", zh:"诊断", en:"Diagnostics", to:"/launcher/tools?view=diagnostics", Icon:Activity },
  { id:"maintenance", zh:"维护", en:"Maintenance", to:"/launcher/tools?view=maintenance", Icon:Wrench },
  { id:"settings", zh:"启动设置", en:"Startup settings", to:"/launcher?view=settings", Icon:Settings2 },
  { id:"updates", zh:"版本更新", en:"Updates", to:"/launcher/updates", Icon:ArrowUpCircle },
] as const;
export function LauncherNavigation({ lang, onNavigate, updateAvailable = false }: { lang:"zh"|"en"; items:LauncherBranchInstance[]; onNavigate?:()=>void; updateAvailable?:boolean }) {
  const location = useLocation();
  const pathname = location.pathname.replace(/\/+$/, "");
  const [returning,setReturning] = useState(false);
  const returnGate = useRef(false);
  const [error,setError] = useState("");
  const assistant = pathname.endsWith("/assistant");
  const panel = resolveLauncherAssistantPanel(location.search);
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
        {assistantEntries.map(([id,Icon]) => <VRouteLinkButton key={id} to={launcherAssistantPanelPath(id as LauncherAssistantPanel)} chrome="shell-nav" aria-current={assistant && panel === id ? "page" : undefined} className={`${styles.link} ${assistant && panel === id ? styles.selectedLink : styles.idleLink}`} icon={<Icon size={17} aria-hidden="true"/>} onClick={onNavigate}>{launcherAssistantPanelLabel(id,lang)}</VRouteLinkButton>)}
      </div>
      <div className={styles.group}><p className={styles.groupLabel}>Launcher</p>{launcherEntries.map(({id,zh,en,to,Icon}) => <VRouteLinkButton key={id} to={to} chrome="shell-nav" aria-current={!assistant && selected === id ? "page" : undefined} className={`${styles.link} ${!assistant && selected === id ? styles.selectedLink : styles.idleLink}`} icon={<Icon size={17} aria-hidden="true"/>} onClick={onNavigate}>{lang === "zh" ? zh : en}{id === "updates" && updateAvailable ? <span className={styles.updateBadge} role="status">{lang === "zh" ? "有新版" : "New"}</span> : null}</VRouteLinkButton>)}</div>
    </div>
    <div className={styles.footer}><VButton variant="ghost" className={styles.returnButton} icon={<ArrowDownRight size={16}/>} isPending={returning} onClick={() => void returnToDesktop()}>{lang === "zh" ? "回到桌面" : "Return to desktop"}</VButton>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}<span className={styles.resident}><ShieldCheck size={13}/>{lang === "zh" ? "关闭窗口不会停止任务" : "Closing this window keeps tasks running"}</span>
    </div>
  </nav>;
}
