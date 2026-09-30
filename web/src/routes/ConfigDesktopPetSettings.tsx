import { useEffect, useRef, useState } from "react";
import { controlDesktopPet, desktopPetControlBridge, type DesktopPetState } from "../api/desktopPet";
import { Cat } from "lucide-react";
import { VButton, VSettingsRow, VSwitch } from "../components/vui";
import styles from "./ConfigDesktopPetSettings.styles";

/** One desktop bridge owner, reused by the directory and the companion category. */
export function ConfigDesktopPetSettings({ language, compact = false }: { language: "zh" | "en"; compact?: boolean }) {
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
  if (compact) return <div data-testid="desktop-pet-settings-compact">
    <div className={styles.compactRow} title={label}>
      <Cat size={16} aria-hidden="true" /><span className={styles.compactLabel}>{zh ? "桌面宠物" : "Desktop pet"}</span>
      <span className={styles.compactStatus} role="status">{!available ? (zh ? "仅桌面版" : "Desktop only") : label}</span>
      <VSwitch aria-label={zh ? "桌面宠物" : "Desktop pet"} isSelected={state?.open ?? false} isDisabled={!available || !state || busy || state.busyElsewhere} onChange={() => void toggle()} />
    </div>
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
  </div>;
  return <VSettingsRow
    testId="desktop-pet-settings"
    label={zh ? "桌面宠物" : "Desktop pet"}
    description={available
      ? (zh ? "程序启动时默认关闭，可随时在这里重新开启。" : "Off on startup. Reopen here at any time.")
      : (zh ? "请在支持此功能的桌面版中打开设置。" : "Open settings in an updated desktop app.")}
    control={<VButton
      aria-label={zh ? "桌面宠物" : "Desktop pet"}
      aria-pressed={state?.open ?? false}
      isDisabled={!available || !state || busy || state.busyElsewhere}
      isPending={busy}
      variant="secondary"
      onPress={() => void toggle()}
    >{state?.open ? (zh ? "关闭桌宠" : "Close pet") : (zh ? "启动桌宠" : "Open pet")}</VButton>}
    status={<span className={styles.status} role="status">{label}</span>}
    footer={error ? <p className={styles.error} role="alert">{error}</p> : undefined}
  />;
}
