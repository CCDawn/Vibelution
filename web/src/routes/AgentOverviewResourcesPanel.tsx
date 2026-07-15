import { Boxes } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./AgentOverviewResourcesPanel.styles";

export type AgentOverviewResourceView = {
  id: string;
  label: string;
  value: string;
  route: string;
};

export type AgentOverviewResourcesPanelProps = {
  title: string;
  emptyLabel: string;
  openLabel: string;
  resources: AgentOverviewResourceView[];
  onOpenRoute: (route: string) => void;
};

export function AgentOverviewResourcesPanel({ title, emptyLabel, openLabel, resources, onOpenRoute }: AgentOverviewResourcesPanelProps) {
  return (
    <section className={styles.section} aria-label={title}>
      <div className={styles.header}>
        <h3 className={styles.title}>{title}</h3>
        <Boxes size={16} aria-hidden="true" />
      </div>
      {resources.length ? (
        <div className={styles.list}>
          {resources.slice(0, 4).map((resource) => (
            <div key={resource.id} className={styles.item}>
              <div className={styles.itemText}>
                <span>{resource.label}</span>
                <strong title={resource.value}>{resource.value}</strong>
              </div>
              <VButton type="button" variant="ghost" onPress={() => onOpenRoute(resource.route)}>{openLabel}</VButton>
            </div>
          ))}
        </div>
      ) : (
        <p className={styles.empty}>{emptyLabel}</p>
      )}
    </section>
  );
}
