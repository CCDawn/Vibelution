import { ChevronRight, Settings2 } from "lucide-react";
import { ConfigDesktopPetSettings } from "./ConfigDesktopPetSettings";
import type { ConfigSummary } from "../api/types";
import { VNativeButton } from "../components/vui";
import type { ConfigSettingsGroup, ConfigSettingsGroupId } from "./ConfigSettingsNavigation";
import styles from "./ConfigSettingsIndex.styles";


export function ConfigSettingsIndex({ groups, sections, language, onNavigate }: {
  groups: ConfigSettingsGroup[]; sections: ConfigSummary["sections"]; language: "zh" | "en";
  onNavigate: (group: ConfigSettingsGroupId, page: string, section: string) => void;
}) {
  const sectionMap = new Map(sections.map(section => [section.id, section]));
  return <div className={styles.root} aria-label={language === "zh" ? "设置功能列表" : "Settings features"}>
    {groups.map(group => <section className={styles.group} key={group.id}>
      <h2 className={styles.title}>{group.title}</h2>
      <div className={styles.rows}>
        {group.id === "avatar-pet" ? <ConfigDesktopPetSettings language={language} /> : null}
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
