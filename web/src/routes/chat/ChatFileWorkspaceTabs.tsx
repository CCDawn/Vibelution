import { X } from "lucide-react";

import { VButton } from "../../components/vui";
import styles from "./ChatFileWorkspaceTabs.styles";

type ChatFileWorkspaceTabsProps = {
  activeTab: string;
  closePreviewTabLabel: string;
  hidden: boolean;
  openTabs: string[];
  onCloseTab: (tabPath: string) => void;
  onOpenTab: (tabPath: string) => void;
};

function fileTabName(tabPath: string) {
  return tabPath.split("/").at(-1) || tabPath;
}

export function ChatFileWorkspaceTabs({
  activeTab,
  closePreviewTabLabel,
  hidden,
  openTabs,
  onCloseTab,
  onOpenTab,
}: ChatFileWorkspaceTabsProps) {
  if (hidden) {
    return null;
  }

  return (
    <>
      {openTabs.map((tabPath) => {
        const tabName = fileTabName(tabPath);
        return (
          <div
            key={tabPath}
            className={activeTab === tabPath ? `${styles.fileTab} ${styles.fileTabActive}` : styles.fileTab}
          >
            <VButton
              type="button"
              className={styles.fileTabButton}
              onClick={() => onOpenTab(tabPath)}
            >
              {tabName}
            </VButton>
            <VButton
              type="button"
              className={styles.fileTabClose}
              onClick={() => onCloseTab(tabPath)}
              title={closePreviewTabLabel}
              aria-label={`${closePreviewTabLabel} ${tabName}`}
            >
              <X size={14} />
            </VButton>
          </div>
        );
      })}
    </>
  );
}
