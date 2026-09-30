import { Activity, ChevronRight, Settings2 } from "lucide-react";
import { ConfigDesktopPetSettings } from "./ConfigDesktopPetSettings";
import type { ConfigSummary } from "../api/types";
import { VNativeButton, VRouteLinkButton } from "../components/vui";
import type { ConfigSettingsGroup, ConfigSettingsGroupId } from "./ConfigSettingsNavigation";
import styles from "./ConfigSettingsIndex.styles";


export function ConfigSettingsIndex({ groups, sections, language, onNavigate, showUsage = true }: {
  groups: ConfigSettingsGroup[]; sections: ConfigSummary["sections"]; language: "zh" | "en";
  onNavigate: (group: ConfigSettingsGroupId, page: string, section: string) => void;
  showUsage?: boolean;
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
    {showUsage && <section className={styles.group} aria-labelledby="settings-usage-group-title">
      <h2 className={styles.title} id="settings-usage-group-title">
        {language === "zh" ? "使用与诊断" : "Usage and diagnostics"}
      </h2>
      <div className={styles.rows}>
        <VRouteLinkButton
          to="/usage"
          variant="ghost"
          className={`${styles.row} ${styles.usageLink}`}
          icon={<Activity size={18} className={styles.icon} aria-hidden="true" />}
          trailingIcon={<ChevronRight size={16} className={styles.icon} aria-hidden="true" />}
        >
          <span className={styles.copy}>
            <strong className={styles.label}>{language === "zh" ? "用量统计" : "Usage statistics"}</strong>
            <span className={styles.hint}>
              {language === "zh" ? "查看 Token 用量与请求统计" : "Review token usage and request statistics"}
            </span>
          </span>
        </VRouteLinkButton>
      </div>
    </section>}
  </div>;
}
