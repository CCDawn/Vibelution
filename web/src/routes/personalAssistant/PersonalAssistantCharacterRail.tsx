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
import { useShellI18n } from "../../i18n/useShellI18n";
import { PERSONAL_ASSISTANT_COPY } from "./personalAssistantCopy";
import styles from "./PersonalAssistantCharacterRail.styles";

export function PersonalAssistantCharacterRail({ assistant, onOpenDesktop, desktopPending }: {
  assistant: PersonalAssistant; onOpenDesktop: () => void; desktopPending: boolean;
}) {
  const { lang } = useShellI18n();
  const copy = PERSONAL_ASSISTANT_COPY[lang];
  const { preferences, updatePreferences } = usePetPreferences();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState<"" | "temporarySettings" | "unsyncedSettings">("");
  const activity = useAssistantActivity({ enabled: true, assistant, reading: true,
    showCompletion: preferences.showCompletion, idleMessage: preferences.idleMessage });
  async function update(patch: Partial<DesktopPetPreferences>) {
    const result = await updatePreferences(patch);
    setError(!result.local ? "temporarySettings" : !result.backend ? "unsyncedSettings" : "");
  }
  return <aside className={styles.root} aria-label={copy.characterRail} data-tone={activity.tone}>
    <header className={styles.header}><span>{copy.assistant}</span></header>
    <div className={styles.portrait}><DesktopPetCharacter characterId={preferences.characterId}
      name={preferences.characterId === "dafeiyu" ? copy.whale : copy.xiaoluo} tone={activity.tone} animationState={activity.animationState} /></div>
    <div className={styles.identity}><h2>{assistant.displayName}</h2>
      <p className={styles.status} role="status"><i className={styles.dot} />{activity.statusText}</p></div>
    {activity.unreadCount ? <VButton variant="secondary" className={styles.unread} onClick={activity.markRead}>{copy.unread(activity.unreadCount)}</VButton> : null}
    <p className={styles.line}>{copy.tagline}</p>
    <div className={styles.actions}><VButton variant="secondary" className={styles.desktop} icon={<Monitor size={14} />}
      isPending={desktopPending} onClick={onOpenDesktop}>{copy.switchDesktop}</VButton>
      <VButton variant="ghost" icon={<Settings2 size={14} />} onClick={() => setSettingsOpen(true)}>{copy.settings}</VButton></div>
    <PersonalAssistantSettings open={settingsOpen} onOpenChange={setSettingsOpen}>
      <div className={styles.settings}>
        <VCheckbox isSelected={preferences.showCompletion} onChange={showCompletion => update({ showCompletion })}>{copy.showCompletion}</VCheckbox>
        {error ? <p role="alert">{copy[error]}</p> : null}
      </div>
    </PersonalAssistantSettings>
  </aside>;
}
