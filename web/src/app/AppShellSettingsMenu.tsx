import { useState } from "react";
import { Activity, ArrowLeft, Check, ChevronRight, Cpu, ExternalLink, Moon, RefreshCw, ScrollText, SlidersHorizontal, Sun, Wrench } from "lucide-react";
import { VButton, VRouteLinkButton } from "../components/vui";
import { ConfigDesktopPetSettings } from "../routes/ConfigDesktopPetSettings";
import styles from "./AppShellSettingsMenu.styles";

export type AppShellSettingsMenuProps = {
  lang: "zh" | "en";
  theme: "light" | "dark";
  onThemeChange: (theme: "light" | "dark") => void;
  onClose: () => void;
  onRefresh: () => void;
  refreshDisabled: boolean;
};

/** Navigation and maintenance are separate levels; lifecycle remains owned by AppShell. */
export function AppShellSettingsMenu({ lang, theme, onThemeChange, onClose, onRefresh, refreshDisabled }: AppShellSettingsMenuProps) {
  const [page, setPage] = useState<"home" | "appearance" | "advanced">("home");
  const zh = lang === "zh";
  return <div className={styles.body} data-testid="shell-settings-menu">
    <div className={styles.heading}>
      {page !== "home" ? <VButton variant="ghost" className={styles.back} aria-label={zh ? "返回设置" : "Back to settings"} onPress={() => setPage("home")}><ArrowLeft size={15} /></VButton> : null}
      {page === "home" ? (zh ? "设置" : "Settings") : page === "appearance" ? (zh ? "外观" : "Appearance") : (zh ? "高级与诊断" : "Advanced and diagnostics")}
    </div>
    {page === "home" ? <>
      <VRouteLinkButton to="/config" variant="ghost" className={styles.row} onClick={onClose} icon={<SlidersHorizontal size={16} />}><span className={styles.label}>{zh ? "全部设置" : "All settings"}</span><ChevronRight size={14} /></VRouteLinkButton>
      <VButton variant="ghost" contentLayout="plain" className={styles.row} onPress={() => setPage("appearance")}>
        {theme === "light" ? <Sun size={16} /> : <Moon size={16} />}<span className={styles.label}>{zh ? "外观" : "Appearance"}</span><span className={styles.value}>{theme === "light" ? (zh ? "浅色" : "Light") : (zh ? "深色" : "Dark")}</span><ChevronRight size={14} />
      </VButton>
      <ConfigDesktopPetSettings language={lang} compact />
      <VRouteLinkButton to="/usage" variant="ghost" className={styles.row} onClick={onClose} icon={<Activity size={16} />}><span className={styles.label}>{zh ? "用量统计" : "Usage"}</span><ChevronRight size={14} /></VRouteLinkButton>
      <div className={styles.divider} />
      <VButton variant="ghost" contentLayout="plain" className={styles.row} onPress={() => setPage("advanced")}><Wrench size={16} /><span className={styles.label}>{zh ? "高级与诊断" : "Advanced and diagnostics"}</span><ChevronRight size={14} /></VButton>
    </> : page === "appearance" ? <>
      {(["light", "dark"] as const).map((value) => <VButton key={value} variant="ghost" contentLayout="plain" className={styles.row} aria-pressed={theme === value} onPress={() => onThemeChange(value)}>{value === "light" ? <Sun size={16} /> : <Moon size={16} />}<span className={styles.label}>{value === "light" ? (zh ? "浅色" : "Light") : (zh ? "深色" : "Dark")}</span>{theme === value ? <Check size={15} /> : null}</VButton>)}
    </> : <>
      <VRouteLinkButton to="/kernel" variant="ghost" className={styles.row} onClick={onClose} icon={<Cpu size={16} />}><span className={styles.label}>{zh ? "运行内核" : "Runtime kernel"}</span><ChevronRight size={14} /></VRouteLinkButton>
      <VRouteLinkButton to="/logs" variant="ghost" className={styles.row} onClick={onClose} icon={<ScrollText size={16} />}><span className={styles.label}>{zh ? "查看日志" : "View logs"}</span><ChevronRight size={14} /></VRouteLinkButton>
      <a href="/launcher" target="_blank" rel="noreferrer" className={styles.row} onClick={onClose}><ExternalLink size={16} /><span className={styles.label}>{zh ? "打开启动器" : "Open launcher"}</span><ExternalLink size={13} /></a>
      <div className={styles.divider} />
      <VButton variant="ghost" contentLayout="plain" className={styles.row} onPress={onRefresh} isDisabled={refreshDisabled}><RefreshCw size={16} /><span className={styles.label}>{zh ? "重新加载界面" : "Reload interface"}</span></VButton>
      <p className={styles.hint}>{zh ? "仅在界面异常时使用，不重启后台服务。" : "For interface issues only. Does not restart background services."}</p>
    </>}
  </div>;
}
