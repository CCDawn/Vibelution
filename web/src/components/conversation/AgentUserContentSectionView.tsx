import React, { ReactNode } from "react";

import styles from "./AgentUserContentSectionView.styles";

type AgentUserContentSectionViewProps = {
  userContentSectionIds?: string;
  children: ReactNode;
};

export function AgentUserContentSectionView({
  userContentSectionIds,
  children,
}: AgentUserContentSectionViewProps) {
  return (
    <div
      className={styles.userMessageBody}
      data-agent-content-section-ids={userContentSectionIds}
      data-agent-content-channel={userContentSectionIds ? "user" : undefined}
    >
      {children}
    </div>
  );
}
