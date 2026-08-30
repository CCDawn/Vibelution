import type { VirtualHumanCompanion } from "../../api/types";
import { CompanionPortrait } from "./CompanionPortrait";
import { CompanionProactiveSettingsPopover } from "./CompanionProactiveSettingsPopover";
import { currentLifeActivityLabel } from "./companionPresentation";
import styles from "./CompanionChatRails.styles";

export function CompanionConversationHeader({
  companion,
  lang,
}: {
  companion: VirtualHumanCompanion;
  lang: "zh" | "en";
}) {
  const activity = currentLifeActivityLabel(companion.snapshot, lang);
  const paused = Boolean(companion.snapshot.state?.lifePaused);

  return (
    <div className={styles.conversationHeader} data-companion-conversation-header="true">
      <div className={styles.conversationIdentity}>
        <CompanionPortrait companion={companion} compact className={styles.conversationAvatar} />
        <div className={styles.conversationIdentityCopy}>
          <strong>{companion.displayName}</strong>
          <span>
            {paused ? (lang === "zh" ? "生活已暂停" : "Life paused") : (lang === "zh" ? "在线" : "Online")}
            <i aria-hidden="true">·</i>
            {activity}
          </span>
        </div>
      </div>
      <CompanionProactiveSettingsPopover companion={companion} lang={lang} />
    </div>
  );
}
