import "../../design/route-css/desktop-pet.tailwind.css";
import { useState } from "react";
import { ChevronDown, Monitor, Settings2 } from "lucide-react";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { VButton, VCheckbox, VDialog, VDropdownMenu } from "../../components/vui";
import { DesktopPetCharacter } from "../desktopPet/DesktopPetCharacter";
import { readPetPreferences, savePetPreferences, type DesktopPetPreferences } from "../desktopPet/desktopPetPreferences";
import { useAssistantActivity } from "./useAssistantActivity";
import styles from "./PersonalAssistantCharacterRail.styles";

export function PersonalAssistantCharacterRail({ assistant, onOpenDesktop, desktopPending }: {
  assistant: PersonalAssistant; onOpenDesktop: () => void; desktopPending: boolean;
}) {
  const [preferences, setPreferences] = useState(readPetPreferences);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState("");
  const activity = useAssistantActivity({ enabled: true, assistant, reading: true,
    showCompletion: preferences.showCompletion, idleMessage: preferences.idleMessage });
  function update(patch: Partial<DesktopPetPreferences>) {
    const next = { ...preferences, ...patch };
    setPreferences(next);
    setError(savePetPreferences(next) ? "" : "设置仅本次生效，无法保存到本机。");
  }
  return <aside className={styles.root} aria-label="个人助理角色" data-tone={activity.tone}>
    <header className={styles.header}><span>个人助理</span></header>
    <div className={styles.portrait}><DesktopPetCharacter characterId={preferences.characterId}
      name={preferences.characterId === "dafeiyu" ? "大肥鲸" : "小洛"} tone={activity.tone} animationState={activity.animationState} /></div>
    <div className={styles.identity}><h2>{preferences.characterId === "dafeiyu" ? "大肥鲸" : "小洛"}</h2>
      <p className={styles.status} role="status"><i className={styles.dot} />{activity.statusText}</p></div>
    {activity.unreadCount ? <VButton variant="secondary" className={styles.unread} onClick={activity.markRead}>查看 {activity.unreadCount} 条新消息</VButton> : null}
    <p className={styles.line}>陪你理清思路，也帮你把事情做好。</p>
    <div className={styles.actions}><VButton variant="secondary" className={styles.desktop} icon={<Monitor size={14} />}
      isPending={desktopPending} onClick={onOpenDesktop}>切换桌面模式</VButton>
      <VButton variant="ghost" icon={<Settings2 size={14} />} onClick={() => setSettingsOpen(true)}>助理设置</VButton></div>
    <VDialog open={settingsOpen} onOpenChange={setSettingsOpen} title="助理设置" size="sm">
      <div className={styles.settings}>
        <VDropdownMenu trigger={<VButton variant="secondary" icon={<ChevronDown size={13} />}>角色外观：{preferences.characterId === "dafeiyu" ? "大肥鲸" : "小洛"}</VButton>}
          items={[{ id: "dafeiyu", label: "大肥鲸", onSelect: () => update({ characterId: "dafeiyu" }) },
            { id: "xiaoluo", label: "小洛", onSelect: () => update({ characterId: "xiaoluo" }) }]} />
        <VCheckbox isSelected={preferences.showCompletion} onChange={showCompletion => update({ showCompletion })}>显示完成庆祝动作</VCheckbox>
        {error ? <p role="alert">{error}</p> : null}
      </div>
    </VDialog>
  </aside>;
}
