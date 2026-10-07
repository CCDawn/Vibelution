import type { ReactNode } from "react";

import { VButton } from "../../components/vui";
import styles from "./ChatSidePane.styles";

export type ChatSidePaneTab = "changes" | "git";

type ChatSidePaneProps = {
  className: string;
  lang: "zh" | "en";
  tab: ChatSidePaneTab;
  onTab: (tab: ChatSidePaneTab) => void;
  children: ReactNode;
};

/**
 * Right column for an ordinary chat. Changes and the repository share one pane.
 */
export function ChatSidePane({
  className,
  lang,
  tab,
  onTab,
  children,
}: ChatSidePaneProps) {
  const changesLabel = lang === "zh" ? "改动" : "Changes";
  const repositoryLabel = lang === "zh" ? "仓库" : "Repository";
  return (
    <section
      id="chat-status-pane"
      className={`${styles.shell} ${className}`}
      aria-label={lang === "zh" ? "右侧栏" : "Right column"}
    >
      <div role="tablist" aria-label={lang === "zh" ? "右侧栏" : "Right column"} className={styles.tabs}>
        <VButton
          type="button"
          role="tab"
          aria-selected={tab === "changes"}
          contentLayout="plain"
          className={tab === "changes" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => onTab("changes")}
        >
          {changesLabel}
        </VButton>
        <VButton
          type="button"
          role="tab"
          aria-selected={tab === "git"}
          contentLayout="plain"
          className={tab === "git" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => onTab("git")}
        >
          {repositoryLabel}
        </VButton>
      </div>
      <div className={styles.body}>{children}</div>
    </section>
  );
}
