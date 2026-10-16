import { useEffect, useState, type ReactNode } from "react";

import { VTabs } from "../../components/vui";
import styles from "./TeamInspectorTabs.styles";

export type TeamInspectorTabsProps = {
  lang: "zh" | "en";
  selectedNodeId?: string;
  /** Optional selection event token, including selecting the same node again. */
  selectionRevision?: number;
  members: ReactNode;
  tasks: ReactNode;
  records: ReactNode;
};

/** Organization inspector sections share one mounted instance of each form/board. */
export function TeamInspectorTabs({
  lang,
  selectedNodeId,
  selectionRevision,
  members,
  tasks,
  records,
}: TeamInspectorTabsProps) {
  const [activeTab, setActiveTab] = useState("members");

  useEffect(() => {
    if (selectedNodeId) setActiveTab("members");
  }, [selectedNodeId, selectionRevision]);

  const sections = [
    { id: "members", label: lang === "zh" ? "成员" : "Members", content: members },
    { id: "tasks", label: lang === "zh" ? "任务" : "Tasks", content: tasks },
    { id: "records", label: lang === "zh" ? "记录" : "Records", content: records },
  ];

  return (
    <div className={styles.root} data-team-inspector-tabs>
      <VTabs
        aria-label={lang === "zh" ? "团队详情" : "Team details"}
        value={activeTab}
        onValueChange={setActiveTab}
        keepPanelsMounted
        items={sections.map(({ id, label, content }) => ({
          id,
          label,
          content: <div data-team-inspector-section={id}>{content}</div>,
        }))}
        listClassName={styles.list}
        triggerClassName={styles.trigger}
      />
    </div>
  );
}
