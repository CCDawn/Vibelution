import "../../design/route-css/desktop-pet.tailwind.css";
import { useState } from "react";
import { Monitor, Settings2 } from "lucide-react";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { VButton, VCheckbox } from "../../components/vui";
import { DesktopPetCharacter } from "../desktopPet/DesktopPetCharacter";
import type { DesktopPetPreferences } from "../desktopPet/desktopPetPreferences";
import { usePetPreferences } from "../desktopPet/usePetPreferences";
import { PersonalAssistantSettings } from "./PersonalAssistantSettings";
import { useAssistantActivity } from "./useAssistantActivity";
import styles from "./PersonalAssistantCharacterRail.styles";

export function PersonalAssistantCharacterRail({ assistant, onOpenDesktop, desktopPending }: {
  assistant: PersonalAssistant; onOpenDesktop: () => void; desktopPending: boolean;
}) {
  const { preferences, updatePreferences } = usePetPreferences();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState("");
  const activity = useAssistantActivity({ enabled: true, assistant, reading: true,
    showCompletion: preferences.showCompletion, idleMessage: preferences.idleMessage });
  async function update(patch: Partial<DesktopPetPreferences>) {
    const result = await updatePreferences(patch);
    setError(!result.local ? "设置仅本次生效，无法保存到本机。" : !result.backend ? "设置已暂存本机，尚未同步到助理。" : "");
  }
  return <aside className={styles.root} aria-label="个人助理角色" data-tone={activity.tone}>
    <header className={styles.header}><span>个人助理</span></header>
    <div className={styles.portrait}><DesktopPetCharacter characterId={preferences.characterId}
      name={preferences.characterId === "dafeiyu" ? "大肥鲸" : "小洛"} tone={activity.tone} animationState={activity.animationState} /></div>
    <div className={styles.identity}><h2>{assistant.displayName}</h2>
      <p className={styles.status} role="status"><i className={styles.dot} />{activity.statusText}</p></div>
    {activity.unreadCount ? <VButton variant="secondary" className={styles.unread} onClick={activity.markRead}>查看 {activity.unreadCount} 条新消息</VButton> : null}
    <p className={styles.line}>陪你理清思路，也帮你把事情做好。</p>
    <div className={styles.actions}><VButton variant="secondary" className={styles.desktop} icon={<Monitor size={14} />}
      isPending={desktopPending} onClick={onOpenDesktop}>切换桌面模式</VButton>
      <VButton variant="ghost" icon={<Settings2 size={14} />} onClick={() => setSettingsOpen(true)}>助理设置</VButton></div>
    <PersonalAssistantSettings open={settingsOpen} onOpenChange={setSettingsOpen}>
      <div className={styles.settings}>
        <VCheckbox isSelected={preferences.showCompletion} onChange={showCompletion => update({ showCompletion })}>显示完成庆祝动作</VCheckbox>
        {error ? <p role="alert">{error}</p> : null}
      </div>
    </PersonalAssistantSettings>
  </aside>;
}
