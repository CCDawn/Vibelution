import { useEffect, useRef, useState } from "react";
import { ChevronRight, PawPrint, Settings2 } from "lucide-react";
import { controlDesktopPet, desktopPetControlBridge, type DesktopPetState } from "../api/desktopPet";
import type { ConfigSummary } from "../api/types";
import { VNativeButton } from "../components/vui";
import type { ConfigSettingsGroup, ConfigSettingsGroupId } from "./ConfigSettingsNavigation";
import styles from "./ConfigSettingsIndex.styles";

function DesktopPetSettingsRow({ language }: { language: "zh" | "en" }) {
  const available = Boolean(desktopPetControlBridge());
  const [state, setState] = useState<DesktopPetState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const changing = useRef(false);
  const zh = language === "zh";
  useEffect(() => {
    if (!available) return;
    let active = true;
    const refresh = async () => {
      if (changing.current) return;
      const id = ++requestId.current;
      try {
        const next = await controlDesktopPet();
        if (active && id === requestId.current) { setState(next); setError(""); }
      } catch {
        if (active && id === requestId.current) { setState(null); setError(zh ? "无法读取桌宠状态，请重试" : "Pet status unavailable. Try again."); }
      }
    };
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 3000);
    window.addEventListener("focus", refresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [available, zh]);
  async function toggle() {
    if (!state || changing.current) return;
    changing.current = true; ++requestId.current;
    setBusy(true); setError("");
    try { setState(await controlDesktopPet(!state.open)); }
    catch { setError(zh ? "操作失败，请重试" : "Could not change pet state. Try again."); }
    finally { changing.current = false; setBusy(false); }
  }
  const label = !available ? (zh ? "需要桌面版更新" : "Desktop update required")
    : busy ? (zh ? "处理中…" : "Working…")
    : state?.busyElsewhere ? (zh ? "其他工作区使用中" : "Used by another workspace")
    : state ? (state.open ? (zh ? "已开启" : "On") : (zh ? "已关闭" : "Off")) : (zh ? "状态待确认" : "Checking status");
  return <>
    <VNativeButton className={styles.row} aria-pressed={state?.open ?? false}
      disabled={!available || !state || busy || state.busyElsewhere} onClick={() => void toggle()}>
      <PawPrint size={19} className={styles.icon} aria-hidden="true" />
      <span className={styles.copy}><strong className={styles.label}>{zh ? "桌面宠物" : "Desktop pet"}</strong>
        <span className={styles.hint}>{available ? (zh ? "点击开启或关闭；程序启动时默认关闭" : "Click to open or close. Off on startup.") : (zh ? "请在支持此功能的桌面版中打开设置" : "Open settings in an updated desktop app.")}</span></span>
      <span className={styles.value}>{label}</span>
    </VNativeButton>
    {error ? <p className={styles.feedback} role="status">{error}</p> : null}
  </>;
}

export function ConfigSettingsIndex({ groups, sections, language, onNavigate }: {
  groups: ConfigSettingsGroup[]; sections: ConfigSummary["sections"]; language: "zh" | "en";
  onNavigate: (group: ConfigSettingsGroupId, page: string, section: string) => void;
}) {
  const sectionMap = new Map(sections.map(section => [section.id, section]));
  return <div className={styles.root} aria-label={language === "zh" ? "设置功能列表" : "Settings features"}>
    {groups.map(group => <section className={styles.group} key={group.id}>
      <h2 className={styles.title}>{group.title}</h2>
      <div className={styles.rows}>
        {group.id === "avatar-pet" ? <DesktopPetSettingsRow language={language} /> : null}
        {group.pages.flatMap(page => page.memberSectionIds.map(id => {
          const section = sectionMap.get(id);
          if (!section) return null;
          return <VNativeButton key={id} className={styles.row} onClick={() => onNavigate(group.id, page.id, id)}>
            <Settings2 size={18} className={styles.icon} aria-hidden="true" />
            <span className={styles.copy}><strong className={styles.label}>{section.title}</strong>
              <span className={styles.hint}>{section.summary}</span></span>
            <ChevronRight size={16} className={styles.icon} aria-hidden="true" />
          </VNativeButton>;
        }))}
      </div>
    </section>)}
  </div>;
}
